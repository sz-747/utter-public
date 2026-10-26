# coding: utf-8
"""
shortcut submodule

Shortcut handling. ShortcutManager manages every shortcut (keyboard and mouse).
"""

from .. import logger
from util.client.shortcut.shortcut_config import Shortcut, CommonShortcuts
from util.client.shortcut.shortcut_manager import ShortcutManager

__all__ = [
    'logger',
    'Shortcut',
    'CommonShortcuts',
    'ShortcutManager',
]
