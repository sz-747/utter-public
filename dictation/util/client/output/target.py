"""Is there somewhere to type? Decide before typing a dictation.

Only clear cases count as "nowhere": the desktop or taskbar is in front, or
keyboard focus sits on a menu, button, list item or similar control (e.g. Alt
was pressed by accident and the menu bar has focus). Everything else, including
terminals, editors, browsers and windows UI Automation cannot read, is treated
as typeable, so dictation behaves exactly as before there.
"""
from __future__ import annotations

import threading

from . import logger

# UI Automation control types that never accept typed text.
_NOT_TEXT = {
    50000: 'button', 50002: 'checkbox', 50005: 'link', 50006: 'image', 50007: 'list item',
    50009: 'menu', 50010: 'menu bar', 50011: 'menu item', 50013: 'radio button', 50014: 'scroll bar',
    50015: 'slider', 50019: 'tab', 50024: 'tree item', 50031: 'split button', 50037: 'title bar',
    50038: 'separator',
}
# Foreground windows that are not an app you can type into.
_SHELL_CLASSES = {'Progman': 'the desktop', 'WorkerW': 'the desktop', 'Shell_TrayWnd': 'the taskbar',
                  'Shell_SecondaryTrayWnd': 'the taskbar'}


def classify(foreground_class: str | None, control_type: int | None) -> tuple[bool, str]:
    """(typeable, reason). Pure, so it can be tested without a desktop."""
    if foreground_class in _SHELL_CLASSES:
        return False, f'{_SHELL_CLASSES[foreground_class]} was selected'
    if control_type in _NOT_TEXT:
        return False, f'a {_NOT_TEXT[control_type]} had focus, not a text box'
    return True, ''


def _probe(result: dict) -> None:
    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        result['class'] = win32gui.GetClassName(hwnd) if hwnd else None
        import comtypes
        comtypes.CoInitialize()
        try:
            from util.client.learn.uia_text import UiaReader
            element = UiaReader().focused()
            result['control'] = element.CurrentControlType if element is not None else None
        finally:
            comtypes.CoUninitialize()
    except Exception as e:
        result['error'] = str(e)


def check(timeout: float = 0.4) -> tuple[bool, str]:
    """Typeable unless clearly not; any error or slow app means 'typeable' (today's behaviour)."""
    result: dict = {}
    worker = threading.Thread(target=_probe, args=(result,), daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive() or 'error' in result:
        logger.debug(f"Focus check skipped:{result.get('error', 'timeout')}")
        return True, ''
    return classify(result.get('class'), result.get('control'))
