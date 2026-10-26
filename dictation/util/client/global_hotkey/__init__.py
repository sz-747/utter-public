# coding: utf-8
"""
Global hotkey submodule.

Listens for global hotkeys with pynput GlobalHotKeys.
"""

from .. import logger
from util.client.global_hotkey.global_hotkey import (
    GlobalHotkeyManager,
    get_global_hotkey_manager,
)

__all__ = [
    'logger',
    'GlobalHotkeyManager',
    'get_global_hotkey_manager',
]
