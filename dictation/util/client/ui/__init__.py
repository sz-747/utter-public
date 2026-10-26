# coding: utf-8
"""
Client UI facade

The single entry point the client uses for UI features.
Importing it injects the client logger into the shared UI module
and re-exports the common UI components.
"""

from .. import logger
import util.ui

# 1. Inject the client logger into the shared UI module
util.ui.set_ui_logger(logger)

# 2. Export the client-only UI components
from util.client.ui.tips import TipsDisplay
from util.client.ui.recording_status_bar import (
    show_recording_status,
    show_thinking_status,
    hide_recording_status,
)

# 3. Re-export the shared UI components
# so other client modules only need `from util.client.ui import ...`
from util.ui import (
    toast,
    toast_stream,
    ToastMessage,
    ToastMessageManager,
    ToastMessageManager,
    enable_min_to_tray,
    stop_tray,
)

# 4. Export the menu handlers (used by Startup)
from util.ui.rectify_menu_handler import on_add_rectify_record
from util.ui.hotword_menu_handler import on_add_hotword
from util.ui.context_menu_handler import on_edit_context

__all__ = [
    'logger',
    'TipsDisplay',
    'show_recording_status',
    'show_thinking_status',
    'hide_recording_status',
    'toast',
    'toast_stream',
    'ToastMessage',
    'ToastMessageManager',
    'enable_min_to_tray',
    'stop_tray',
    'on_add_rectify_record',
    'on_add_hotword',
    'on_edit_context',
]
