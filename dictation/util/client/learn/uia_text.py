"""Read the text of an app's input field through Windows UI Automation.

All calls must stay on the thread that called `UiaReader()`, which must have
initialised COM. Nothing read here is stored; callers keep only learned words.
"""
from __future__ import annotations

_MAX_CHARS = 200_000
_UIA_VALUE_PATTERN = 10002
_UIA_TEXT_PATTERN = 10014


class UiaReader:
    def __init__(self):
        import comtypes.client
        comtypes.client.GetModule('UIAutomationCore.dll')
        from comtypes.gen import UIAutomationClient as uia
        self._uia = uia
        self._automation = comtypes.client.CreateObject(uia.CUIAutomation, interface=uia.IUIAutomation)

    def focused(self):
        try:
            return self._automation.GetFocusedElement()
        except Exception:
            return None

    def from_handle(self, hwnd):
        return self._automation.ElementFromHandle(hwnd)

    @staticmethod
    def is_password(element) -> bool:
        try:
            return bool(element.CurrentIsPassword)
        except Exception:
            return True

    @staticmethod
    def process_id(element):
        try:
            return element.CurrentProcessId
        except Exception:
            return None

    def text(self, element):
        """Full text of the element, or None when it exposes none (or is gone)."""
        uia = self._uia
        try:
            pattern = element.GetCurrentPattern(_UIA_TEXT_PATTERN)
            if pattern:
                text_pattern = pattern.QueryInterface(uia.IUIAutomationTextPattern)
                return text_pattern.DocumentRange.GetText(_MAX_CHARS)
        except Exception:
            pass
        try:
            pattern = element.GetCurrentPattern(_UIA_VALUE_PATTERN)
            if pattern:
                return pattern.QueryInterface(uia.IUIAutomationValuePattern).CurrentValue
        except Exception:
            pass
        return None
