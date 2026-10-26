"""Join back-to-back dictations into one passage.

When a second dictation follows the first in one go, it should start a new
sentence. If it lands in the same window and nothing was typed or clicked
since the last output, the cursor is still right after that text, so the new
text gets '. ' in front and a capital first letter.

The shortcut listeners report real key presses and clicks through
`note_user_input`; keys the dictation client sends itself are marked injected
and skipped.
"""
from __future__ import annotations

import threading

_lock = threading.Lock()
_window = None
_last_text = ''
_touched = True
_watching = False


def watch() -> None:
    """Called once both keyboard and mouse input are being watched."""
    global _watching
    _watching = True


def note_user_input() -> None:
    global _touched
    _touched = True


def remember(window, text: str) -> None:
    """Record what was just typed and where."""
    global _window, _last_text, _touched
    with _lock:
        _window, _last_text, _touched = window, text or '', False


def window_key(window_info) -> tuple | None:
    if not window_info or not window_info.get('hwnd'):
        return None
    return window_info['hwnd'], window_info.get('process_name', '')


def join(previous: str, text: str) -> tuple[str, str]:
    """(separator to type first, new text) when `text` continues right after `previous`."""
    previous = previous.rstrip()
    if not previous or not text[:1].isalnum():
        return '', text
    if previous[-1] in ';:':
        return ' ', text
    sep = ' ' if previous[-1] in '.!?' else '. '
    return sep, text[:1].upper() + text[1:]


def prepare(window, text: str) -> tuple[str, str]:
    """join() against the last output, or ('', text) when the cursor may have moved."""
    with _lock:
        joined = _watching and not _touched and window is not None and window == _window
        previous = _last_text
    return join(previous, text) if joined else ('', text)
