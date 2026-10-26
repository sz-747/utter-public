"""
LLM module

Everything LLM-related: role management, message building, context management and so on"""

from util import get_logger
logger = get_logger('client')

# Core handler
from .llm_handler import LLMHandler, get_handler, init_llm_system

# Role settings and loading
from .llm_role_config import RoleConfig
from .llm_role_loader import RoleLoader

# Context management
from .llm_context import ContextManager

# Message building and client pool
from .llm_message_builder import MessageBuilder
from .llm_client_pool import ClientPool

# Clipboard / selected text
from .llm_clipboard import copy_to_clipboard
from .llm_get_selection import (
    get_selected_text,
    record_selection_usage
)

# Monitoring and output
from .llm_watcher import LLMFileWatcher
from .llm_stop_monitor import reset, should_stop

from .llm_output_toast import handle_toast_mode
from .llm_output_typing import handle_typing_mode

from .llm_process_text import llm_process_text, LLMResult

__all__ = [
    # Core
    'LLMHandler',
    'get_handler',
    'init_llm_system',

    # Role management
    'RoleConfig',
    'RoleLoader',

    # Context
    'ContextManager',

    # Components
    'MessageBuilder',
    'ClientPool',

    # Clipboard / selected text
    'get_selected_text',
    'record_selection_usage',
    'copy_to_clipboard',

    # Monitoring
    'LLMFileWatcher',
    'reset',
    'should_stop',

    # Output
    'handle_toast_mode',
    'handle_typing_mode',

    # Main entry point
    'llm_process_text',
    'LLMResult',
]
