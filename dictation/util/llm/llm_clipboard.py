"""
LLM clipboard helpers

One interface for clipboard work:
1. Read the clipboard safely (several encodings)
2. Write the clipboard safely
3. Context manager that saves and restores the clipboard
4. Paste text (simulates Ctrl+V)

Kept for backward compatibility; the implementation now lives in util.client.clipboard
"""
# Import from the new location for backward compatibility
from util.client.clipboard import (
    safe_paste,
    safe_copy,
    paste_text,
    keep_output_clipboard,
    should_keep_output_clipboard,
    save_and_restore_clipboard,
    copy_to_clipboard,
    CLIPBOARD_ENCODINGS
)

__all__ = [
    'safe_paste',
    'safe_copy',
    'paste_text',
    'keep_output_clipboard',
    'should_keep_output_clipboard',
    'save_and_restore_clipboard',
    'copy_to_clipboard',
    'CLIPBOARD_ENCODINGS'
]
