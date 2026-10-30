"""
LLM processing engine

Features:
1. Makes the LLM API call
2. Handles streaming output
3. Updates the context history
4. Wraps and handles errors in one place
5. Accurate generation timing (from the first token)
"""
import time
from typing import Callable, Optional, Dict, Any, List, Tuple
from util.llm.llm_role_config import RoleConfig
from util.llm.llm_interfaces import IContextManager
from util.llm.llm_client_pool import ClientPool, local_server_listening
from util.llm.llm_exceptions import (
    APIException,
    wrap_openai_error, OpenAIErrorWrapper,
    TimeoutErrorWrapper, ConnectionErrorWrapper
)
from util.llm.llm_error_handler import note_llm_success
from . import logger


class LLMProcessor:
    """LLM processing engine - makes the API call and streams the output"""

    def __init__(self, client_pool: ClientPool):
        """
        Args:
            client_pool: client pool
        """
        self.client_pool = client_pool

    def process(
        self,
        role_config: RoleConfig,
        messages: List[Dict[str, str]],
        callback: Optional[Callable[[str], None]] = None,
        should_stop_check: Optional[Callable[[], bool]] = None,
        context_manager: Optional[IContextManager] = None
    ) -> Tuple[str, int, float]:
        """
        Run LLM processing

        Args:
            role_config: role settings
            messages: message list
            callback: streaming output callback
            should_stop_check: function that says whether to stop
            context_manager: context manager (to update the history)

        Returns:
            (processed text, output token count, generation time in seconds)
        """
        logger.info(f"Starting LLM processing, model: {role_config.model}")

        # A local model server that is off fails at once instead of after the client's slow retries
        api_url = ClientPool.api_url_for(role_config.provider, role_config.api_url)
        if not local_server_listening(api_url):
            error = ConnectionErrorWrapper(
                ConnectionRefusedError(f'nothing is listening at {api_url}'), role_config.provider
            )
            if role_config.provider == 'ollama':
                from util.llm.local_server import start_ollama
                error.starting = start_ollama()      # this dictation is typed as heard; the next is polished
            logger.error(f"LLM API call failed: {error}")
            raise error

        # Get the client
        logger.debug(f"Getting the LLM client, provider: {role_config.provider}, API: {role_config.api_url}")
        client = self.client_pool.get_client(
            provider=role_config.provider,
            api_url=role_config.api_url,
            api_key=role_config.api_key
        )

        # Build the request parameters
        request_params = self._build_request_params(role_config, messages)

        try:
            result = self._stream_request(
                client,
                request_params,
                callback,
                should_stop_check,
                role_config,
                context_manager,
                messages
            )
            note_llm_success()
            return result

        except OpenAIErrorWrapper:
            # Already-wrapped OpenAI exception: re-raise as is
            raise
        except Exception as e:
            # Already-wrapped exceptions
            if isinstance(e, (OpenAIErrorWrapper, APIException)):
                raise

            # Native Ollama SDK exceptions
            if role_config.provider == 'ollama':
                try:
                    import ollama
                    if isinstance(e, (ollama.ResponseError, ollama.RequestError)):
                        error_msg = f"Ollama API call failed: {e}"
                        logger.error(error_msg)
                        raise APIException(error_msg, role_config.provider) from e
                except ImportError:
                    pass

            # Wrap native OpenAI SDK exceptions
            import openai

            # httpx timeouts (raised while reading the stream)
            if 'httpx' in str(type(e).__module__):
                error_type = type(e).__name__
                if 'Timeout' in error_type or 'timeout' in error_type:
                    # httpx.ReadTimeout or httpx.TimeoutException
                    wrapped_error = TimeoutErrorWrapper(e, role_config.provider)
                    logger.error(f"LLM API request timed out: {wrapped_error}")
                    raise wrapped_error from e

            if isinstance(e, (
                openai.AuthenticationError,
                openai.RateLimitError,
                openai.APITimeoutError,
                openai.APIConnectionError,
                openai.APIError
            )):
                wrapped_error = wrap_openai_error(e, role_config.provider)
                logger.error(f"LLM API call failed: {wrapped_error}")
                raise wrapped_error from e

            # Anything unexpected: wrap it in an APIException and raise
            import traceback
            error_msg = f"LLM processing failed: {e}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            raise APIException(error_msg, role_config.provider) from e

    def _build_request_params(
        self,
        role_config: RoleConfig,
        messages: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """Build the request parameters in one place"""
        params = {
            'model': role_config.model,
            'messages': messages,
            'temperature': role_config.temperature,
            'top_p': role_config.top_p,
        }

        if role_config.max_tokens > 0:
            params['max_tokens'] = role_config.max_tokens
            # Map to num_predict for Ollama
            if role_config.provider == 'ollama':
                params['num_predict'] = role_config.max_tokens

        # Stop sequences
        if role_config.stop:
            stop_list = role_config.stop
            if isinstance(stop_list, str):
                stop_list = [s.strip() for s in stop_list.split(',')]
            params['stop'] = stop_list

        # Merge the extra options
        if role_config.extra_options:
            params.update(role_config.extra_options)

        return params

    def _stream_request(
        self,
        client: Any,
        request_params: Dict[str, Any],
        callback: Optional[Callable[[str], None]],
        should_stop_check: Optional[Callable[[], bool]],
        role_config: RoleConfig,
        context_manager: Optional[IContextManager],
        messages: List[Dict[str, str]]
    ) -> Tuple[str, int, float]:
        """Run the streaming request with the right engine"""

        if role_config.provider == 'ollama':
            result = self._process_ollama_stream(
                client, role_config, messages, callback, should_stop_check
            )
        else:
            result = self._process_openai_stream(
                client, request_params, callback, should_stop_check
            )

        full_response, total_tokens, generation_time = result

        # Estimate tokens as a fallback (for providers such as Ollama that return no usage)
        if total_tokens == 0 and full_response:
            from util.llm.llm_constants import estimate_tokens
            total_tokens = estimate_tokens(full_response)
            result = (full_response, total_tokens, generation_time)

        # Update the history
        if role_config.enable_history and context_manager:
            context_manager.add_message('user', messages[-1]['content'])
            context_manager.add_message('assistant', full_response)
            logger.debug(f"Updated the history")

        return result

    def _process_ollama_stream(
        self,
        client: Any,
        role_config: RoleConfig,
        messages: List[Dict[str, str]],
        callback: Optional[Callable[[str], None]],
        should_stop_check: Optional[Callable[[], bool]]
    ) -> Tuple[str, int, float]:
        """Handle a native Ollama stream"""

        # 1. Build the parameters and pick out the Ollama options
        params = self._build_request_params(role_config, messages)
        ollama_options = {
            k: v for k, v in params.items()
            if k in ['temperature', 'top_p', 'stop', 'num_predict']
        }

        # 2. Send the request
        chat_kwargs = {
            'model': role_config.model,
            'messages': messages,
            'stream': True,
            'options': ollama_options,
        }

        # Say thinking is off, too: left out, thinking models such as Qwen 3.5 think by default,
        # and one spent 11 s thinking and returned no text; with think=False it answered in 0.3 s
        try:
            import inspect
            supports_think = 'think' in inspect.signature(client.chat).parameters
        except (TypeError, ValueError):
            supports_think = False

        if supports_think:
            chat_kwargs['think'] = bool(role_config.enable_thinking)
        elif role_config.enable_thinking:
            logger.warning("This Ollama SDK does not support the think parameter; skipped the thinking switch")

        # keep_alive: how long the model stays loaded when idle (Ollama's default is 5 minutes)
        keep_alive = (role_config.extra_options or {}).get('keep_alive')
        if keep_alive is not None:
            chat_kwargs['keep_alive'] = keep_alive

        stream = client.chat(**chat_kwargs)

        # 3. Read the stream
        full_response, total_tokens, generation_start_time = "", 0, None

        for chunk in stream:
            if should_stop_check and should_stop_check():
                break

            if hasattr(chunk, 'message') and chunk.message.content:
                content = chunk.message.content
                full_response += content
                if generation_start_time is None:
                    generation_start_time = time.time()
                if callback:
                    callback(content)

            if hasattr(chunk, 'done') and chunk.done:
                total_tokens = getattr(chunk, 'eval_count', 0)

        generation_time = time.time() - generation_start_time if generation_start_time else 0.0
        return full_response.strip(), total_tokens, generation_time

    def _process_openai_stream(
        self,
        client: Any,
        params: Dict[str, Any],
        callback: Optional[Callable[[str], None]],
        should_stop_check: Optional[Callable[[], bool]]
    ) -> Tuple[str, int, float]:
        """Handle an OpenAI-compatible API stream"""

        # Drop the Ollama-only parameter
        openai_params = {k: v for k, v in params.items() if k != 'num_predict'}
        openai_params['stream'] = True

        stream = client.chat.completions.create(**openai_params)

        full_response, total_tokens, generation_start_time = "", 0, None

        for chunk in stream:
            if should_stop_check and should_stop_check():
                try: stream.close()
                except: pass
                break

            if chunk.choices and chunk.choices[0].delta.content:
                content = chunk.choices[0].delta.content
                full_response += content
                if generation_start_time is None:
                    generation_start_time = time.time()
                if callback:
                    callback(content)

            if hasattr(chunk, 'usage') and chunk.usage:
                total_tokens = getattr(chunk.usage, 'completion_tokens', 0)

        generation_time = time.time() - generation_start_time if generation_start_time else 0.0
        return full_response.strip(), total_tokens, generation_time
