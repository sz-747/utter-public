"""Keep a dictation going to the window it was meant for.

The target is the window in front when the result arrives. Just before typing, if one of this
client's own windows (status pill, toast) is in front instead, the target gets the foreground back;
any other change is logged, so a dictation that never lands can be traced to where it went.
"""
from __future__ import annotations

import os

from . import logger

_target: dict = {}


def remember(window_info: dict | None) -> None:
    """Record the window the coming dictation is for."""
    _target.clear()
    if window_info and window_info.get('hwnd'):
        _target.update(window_info)


def decide(target_hwnd: int, now_hwnd: int, now_pid: int, own_pid: int) -> str:
    """'ok' (target in front), 'restore' (our own window or nothing in front), or 'moved' (another app)."""
    if not target_hwnd or now_hwnd == target_hwnd:
        return 'ok'
    if not now_hwnd or now_pid == own_pid:
        return 'restore'
    return 'moved'


def before_typing() -> None:
    """Call right before typing or pasting a dictation. Never raises."""
    target = _target.get('hwnd')
    if not target:
        return
    try:
        import win32gui
        import win32process

        now = win32gui.GetForegroundWindow()
        now_pid = win32process.GetWindowThreadProcessId(now)[1] if now else 0
        action = decide(target, now, now_pid, os.getpid())
        if action == 'ok':
            return
        name = _target.get('process_name') or _target.get('title') or 'the target window'
        if action == 'restore':
            win32gui.SetForegroundWindow(target)
            landed = win32gui.GetForegroundWindow() == target
            logger.info(f"Typing target {name} had lost the foreground to this client's own window; "
                        f"gave it back ({'ok' if landed else 'failed'})")
        else:
            logger.info(f"Foreground moved before typing: {name} -> {win32gui.GetWindowText(now)!r}")
    except Exception as e:
        logger.info(f"Could not check the typing target: {e}")
