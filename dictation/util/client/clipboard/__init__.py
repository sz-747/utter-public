# coding: utf-8
"""
Clipboard package

One place for clipboard operations:
1. Read the clipboard safely (tries several encodings)
2. Write to the clipboard safely
3. A context manager that saves and restores the clipboard
4. Paste text (simulates Ctrl+V)
"""

from .. import logger
from util.client.clipboard.clipboard import (
    safe_paste,
    safe_copy,
    copy_to_clipboard,
    keep_output_clipboard,
    should_keep_output_clipboard,
    save_and_restore_clipboard,
    paste_text,
    CLIPBOARD_ENCODINGS,
)

__all__ = [
    'logger',
    'safe_paste',
    'safe_copy',
    'copy_to_clipboard',
    'keep_output_clipboard',
    'should_keep_output_clipboard',
    'save_and_restore_clipboard',
    'paste_text',
    'CLIPBOARD_ENCODINGS',
]
