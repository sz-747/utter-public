"""
LLM handler - coordinator

Features:
1. Coordinates the components (role loading, context management, client pool, message building)
2. Offers one processing interface
3. Streaming output
"""

from typing import Dict, Tuple, Optional, Any
from pathlib import Path

from util.llm.llm_role_loader import RoleLoader
from util.llm.llm_context import ContextManager
from util.llm.llm_watcher import LLMFileWatcher
from util.llm.llm_role_config import RoleConfig
from util.llm.llm_client_pool import ClientPool
from util.llm.llm_message_builder import MessageBuilder
from util.llm.llm_role_detector import RoleDetector
from util.llm.llm_processor import LLMProcessor
from util.llm.llm_get_selection import get_selected_text, record_selection_usage
from util.llm.llm_process_text import LLMResult
from . import logger
from util.hotword import get_hotword_manager


# ======================================================================
# --- LLM handler (coordinator) ---

class LLMHandler:
    """LLM polish handler (coordinator)"""

    def __init__(self, hotwords_file: str = 'hot.txt'):
        logger.info("Setting up the LLM handler")

        # Hotword manager singleton
        self.hotword_manager = get_hotword_manager()

        # Role management
        self.role_loader = RoleLoader()
        self.roles = self.role_loader.get_roles()
        logger.info(f"Loaded roles: {list(self.roles.keys())}")

        # Context manager pool
        self.context_managers: Dict[str, ContextManager] = {}
        self._init_context_managers()

        # Client pool
        self.client_pool = ClientPool()

        # Message builder (gets rectify_rag from the HotwordManager itself)
        self.message_builder = MessageBuilder()

        # Role detector
        self.role_detector = RoleDetector(self.role_loader)

        # LLM processing engine
        self.processor = LLMProcessor(self.client_pool)

    def _init_context_managers(self):
        """Create a context manager for each role with history enabled"""
        for role_name, role_config in self.roles.items():
            if role_config.enable_history:
                self.context_managers[role_name] = ContextManager(
                    max_length=role_config.max_context_length,
                )

    def reload_roles(self):
        """Reload all roles (keeping their history)"""
        logger.info("Reloading role settings")
        # Save the old history
        old_contexts = {}
        for role_name, ctx in self.context_managers.items():
            old_contexts[role_name] = {
                'history': ctx.history.copy(),
                'last_interaction': ctx.last_interaction
            }

        # Clear and reload
        self.context_managers.clear()
        self.client_pool.clear()
        self.role_loader.load_all_roles()
        self.roles = self.role_loader.get_roles()
        logger.info(f"Roles after reload: {list(self.roles.keys())}")
        self._init_context_managers()

        # Restore the history
        for role_name, ctx in self.context_managers.items():
            if role_name in old_contexts:
                ctx.history = old_contexts[role_name]['history']
                ctx.last_interaction = old_contexts[role_name]['last_interaction']
                logger.debug(f"Restored the history of role '{role_name}': {len(ctx.history)} messages")

    def clear_history(self):
        """Clear the conversation history of every role"""
        logger.info("Clearing the conversation history of all roles...")
        count = 0
        for role_name, manager in self.context_managers.items():
            manager.clear()
            count += 1
        logger.info(f"Cleared the conversation history of {count} roles")

    def detect_role(self, text: str) -> Tuple[Optional[RoleConfig], str]:
        """Check whether the text starts with a role prefix

        Args:
            text: input text

        Returns:
            (role_config, content) - role_config is a RoleConfig, content is the text without the prefix
        """
        return self.role_detector.detect(text)

    def process(self, role_config: RoleConfig, content: str, matched_hotwords=None, callback=None, should_stop_check=None) -> Tuple[str, int, float]:
        """Run the actual LLM call (internal)

        Args:
            role_config: role settings
            content: the input without the prefix
            matched_hotwords: [(hotword, score), ...] from the hot_phoneme search
            callback: callback for streaming output
            should_stop_check: function that returns True when processing should stop

        Returns:
            (processed text, output token count, generation time in seconds)
        """
        # Role name (empty string -> the default role name)
        role_name = role_config.name or RoleConfig.DEFAULT_ROLE_NAME
        logger.debug(f"Starting LLM processing [role: {role_name}] [content length: {len(content)}]")

        # Context manager (if history is enabled)
        context_manager = self.context_managers.get(role_name) if role_config.enable_history else None
        if context_manager:
            logger.debug(f"Role '{role_name}' has history enabled, {len(context_manager.history)} messages so far")

        # Selected text (if enabled)
        selection_text = get_selected_text(role_config)

        # Build the messages
        messages = self.message_builder.build_messages(
            role_config, content, context_manager,
            hotwords=matched_hotwords,
            selection_text=selection_text
        )

        # Run the request through the LLM processing engine
        result_text, token_count, gen_time = self.processor.process(
            role_config=role_config,
            messages=messages,
            callback=callback,
            should_stop_check=should_stop_check,
            context_manager=context_manager
        )

        # Record the selected text used (to detect repeats next time)
        record_selection_usage(role_config, selection_text)

        return result_text, token_count, gen_time

    async def process_and_output(self, text: str, paste: bool = None, matched_hotwords=None, prefix: str = '') -> Optional[LLMResult]:
        """
        Single entry point: process the input text and output it as configured (typing or pop-up)

        Args:
            text: the full original text to polish (may include a prefix)
            paste: force paste mode (None follows the settings)
            matched_hotwords: matching hotwords
            prefix: separator typed first when continuing the previous dictation (e.g. '. '); not part of the result
        """
        import time
        from util.llm.llm_output_typing import handle_typing_mode, output_text
        from util.llm.llm_output_toast import handle_toast_mode
        from util.client.output.text_output import TextOutput

        start_time = time.time()

        # 1. Detect the role
        role_config, content = self.detect_role(text)

        # 2. No role that needs processing
        if not role_config:

            # Type it out
            await output_text(prefix + text, paste)

            # Update the global state and broadcast over UDP
            from util.client.state import get_state
            get_state().set_output_text(text)

            return LLMResult(result=text, role_name=None, processed=False,
                                token_count=0, polish_time=0, input_text=text)


        # 4. Dispatch by output mode
        if role_config.output_mode == 'toast':
            result, token_count, gen_time = await handle_toast_mode(text, role_config, matched_hotwords, content)
        else: # typing
            result, token_count, gen_time = await handle_typing_mode(text, paste, matched_hotwords, role_config, content, prefix)

        # 5. Post-processing
        # Update the global state (even if interrupted, record what was output)
        if result:
            from util.client.state import get_state
            get_state().set_output_text(result)

        return LLMResult(
            result=result,
            role_name=role_config.name or RoleConfig.DEFAULT_ROLE_NAME,
            processed=True,
            token_count=token_count,
            polish_time=time.time() - start_time,
            input_text=content,
            generation_time=gen_time
        )


# ======================================================================
# --- Global instances ---

_handler: Optional[LLMHandler] = None
_watcher: Optional[LLMFileWatcher] = None


def get_handler() -> LLMHandler:
    """Return the LLM handler (singleton)"""
    global _handler, _watcher

    if _handler is None:
        _handler = LLMHandler()
        # Create the watcher with callbacks, to keep it decoupled
        _watcher = LLMFileWatcher(
            on_roles_reload=lambda: _handler.reload_roles(),
            get_roles=lambda: _handler.roles,
        )
        _watcher.start()

    return _handler


def init_llm_system():
    """Set up the LLM system (convenience function)"""
    from config_client import ClientConfig as Config
    if Config.llm_enabled:
        try:
            get_handler()
        except Exception as e:
            from util.client.state import console
            console.print(f'[red]LLM system failed to start: {e}[/]')
            logger.error(f"LLM system failed to start: {e}", exc_info=True)


async def llm_process_text(text: str, paste: bool = None, matched_hotwords=None) -> Optional[LLMResult]:
    """Polish the text and output it (main external entry point)"""
    handler = get_handler()
    return await handler.process_and_output(text, paste, matched_hotwords)


def clear_llm_history():
    """Clear the LLM conversation history (convenience function)"""
    handler = get_handler()
    handler.clear_history()


# ======================================================================
# --- Test ---

if __name__ == "__main__":
    print("=" * 60)
    print("LLM handler - test mode")
    print("=" * 60)

    import asyncio

    async def run_test_cases():
        handler = get_handler()
        print(f"\nLoaded roles: {list(handler.roles.keys())}")

        test_cases = [
            "uh, I want to see the files in the current folder",
            "command show the files in the current folder",
            "Python read a file",
        ]

        print("\n--- Test cases ---\n")
        for test_text in test_cases:
            print(f"Input: {test_text}")
            print(f"Output: ", end='', flush=True)
            result = await llm_process_text(test_text)
            print()
            print("-" * 40)

    asyncio.run(run_test_cases())
