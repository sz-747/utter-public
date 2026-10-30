"""
LLM custom exceptions

The exception hierarchy of the LLM module
"""
from openai import AuthenticationError, RateLimitError, APITimeoutError, APIConnectionError, APIError


# ======================================================================
# --- Base exception ---

class LLMException(Exception):
    """Base exception of the LLM module"""

    pass


# ======================================================================
# --- OpenAI SDK exception wrappers ---

class OpenAIErrorWrapper(LLMException):
    """Base wrapper for OpenAI SDK exceptions"""

    def __init__(self, original_error: Exception, provider: str = 'unknown'):
        self.original_error = original_error
        self.provider = provider
        super().__init__(f"[{provider}] {type(original_error).__name__}: {str(original_error)}")


# user_message: why polish was skipped, then what to do; the notice puts "Typed without AI polish:" first,
# because the dictation itself was typed as heard.
class AuthenticationErrorWrapper(OpenAIErrorWrapper):
    """Authentication failed (401)"""
    user_message = "the provider rejected the API key.\nCheck the provider key configuration."


class RateLimitErrorWrapper(OpenAIErrorWrapper):
    """Rate limited (429)"""
    user_message = "the model server is rate limiting requests."


class TimeoutErrorWrapper(OpenAIErrorWrapper):
    """Request timed out"""
    user_message = "the model server took too long."


class ConnectionErrorWrapper(OpenAIErrorWrapper):
    """Connection failed"""
    user_message = "the model server isn't answering.\nStart it (Ollama: ollama serve; LM Studio: lms server start), check your provider connection, or turn AI polish off in Utter."
    starting_message = "Ollama wasn't running.\nStarting it now; your next dictation will be polished."
    starting = False          # True when the client has just started a local Ollama (util/llm/local_server.py)


class APIResponseErrorWrapper(OpenAIErrorWrapper):
    """API response error (4xx, 5xx)"""
    user_message = "the provider returned an error.\nCheck the model name and provider's model catalog."


# OpenAI exception map
OPENAI_EXCEPTION_MAP = {
    AuthenticationError: AuthenticationErrorWrapper,
    RateLimitError: RateLimitErrorWrapper,
    APITimeoutError: TimeoutErrorWrapper,
    APIConnectionError: ConnectionErrorWrapper,
    APIError: APIResponseErrorWrapper,
}


def wrap_openai_error(error: Exception, provider: str = 'unknown') -> LLMException:
    """
    Wrap an OpenAI SDK exception in a custom exception

    Args:
        error: the original OpenAI SDK exception
        provider: API provider name

    Returns:
        The wrapped exception
    """
    error_type = type(error)
    wrapper_class = OPENAI_EXCEPTION_MAP.get(error_type)

    if wrapper_class:
        return wrapper_class(error, provider)
    else:
        # Unknown exception type: use the generic wrapper
        return OpenAIErrorWrapper(error, provider)


# ======================================================================
# --- Role exceptions ---

class RoleException(LLMException):
    """Role settings exception"""

    pass


class RoleNotFoundError(RoleException):
    """Role not found"""

    def __init__(self, role_name: str):
        self.role_name = role_name
        super().__init__(f"Role not found: {role_name}")


class RoleLoadError(RoleException):
    """Role failed to load"""

    def __init__(self, file_path: str, reason: str):
        self.file_path = file_path
        self.reason = reason
        super().__init__(f"Could not load role: {file_path}, reason: {reason}")


class InvalidRoleConfigError(RoleException):
    """Invalid role settings"""

    def __init__(self, role_name: str, missing_fields: list):
        self.role_name = role_name
        self.missing_fields = missing_fields
        super().__init__(f"Invalid role settings '{role_name}', missing fields: {', '.join(missing_fields)}")


# ======================================================================
# --- Context exceptions ---

class ContextException(LLMException):
    """Context management exception"""

    pass


class ContextExpiredError(ContextException):
    """Context expired"""

    pass


# ======================================================================
# --- API exceptions ---

class APIException(LLMException):
    """API call exception"""

    pass


class APIConnectionError(APIException):
    """API connection failed"""

    def __init__(self, provider: str, api_url: str, reason: str):
        self.provider = provider
        self.api_url = api_url
        self.reason = reason
        super().__init__(f"Could not connect to the API ({provider}): {api_url}, reason: {reason}")


class APIResponseError(APIException):
    """API response error"""

    def __init__(self, provider: str, status_code: int = None, reason: str = None):
        self.provider = provider
        self.status_code = status_code
        self.reason = reason
        msg = f"API response error ({provider})"
        if status_code:
            msg += f", status code: {status_code}"
        if reason:
            msg += f", reason: {reason}"
        super().__init__(msg)


class StreamInterruptedError(APIException):
    """Streaming output was interrupted"""

    def __init__(self, chunks_received: int = 0):
        self.chunks_received = chunks_received
        super().__init__(f"Streaming output was interrupted after {chunks_received} chunks")


# ======================================================================
# --- RAG exceptions ---

class RAGException(LLMException):
    """RAG search exception"""

    pass


class HotwordsLoadError(RAGException):
    """Hotwords failed to load"""

    def __init__(self, file_path: str, reason: str):
        self.file_path = file_path
        self.reason = reason
        super().__init__(f"Could not load hotwords: {file_path}, reason: {reason}")
