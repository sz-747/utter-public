"""Notice when a call starts, so the Notetaker can offer to take notes.

A call is an app that is using the microphone right now (Windows records this
per app in the privacy "consent store") plus a window that names the meeting:
- Google Meet in a browser: a window titled "Meet - <code or name>", or, for a
  Meet tab behind another tab, a tab with that name (read through UI Automation
  only while the browser is using the microphone).
- Zoom, Microsoft Teams or Telegram desktop apps: the app itself using the
  microphone. Telegram also uses it for voice messages, so it counts only after
  VOICE_MESSAGE_SECONDS; a longer voice message still gets an offer.
Nothing is recorded or sent; this only reads window and tab titles and the registry.
"""
from __future__ import annotations

import re
import time
import winreg

_CONSENT = r'Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone'
BROWSERS = {'chrome.exe', 'msedge.exe', 'brave.exe', 'firefox.exe', 'arc.exe', 'opera.exe', 'vivaldi.exe'}
APPS = {'zoom.exe': 'Zoom', 'ms-teams.exe': 'Microsoft Teams', 'teams.exe': 'Microsoft Teams', 'telegram.exe': 'Telegram'}
PACKAGED_APPS = {'MSTeams': 'Microsoft Teams', 'TelegramMessengerLLP.TelegramDesktop': 'Telegram'}
VOICE_MESSAGE_APPS = ('telegram.exe', 'TelegramMessengerLLP.TelegramDesktop')
VOICE_MESSAGE_SECONDS = 10
# "Meet - abc-defg-hij and 6 more pages - Personal - Microsoft Edge" -> "abc-defg-hij"
_MEET_TITLE = re.compile(r'^Meet\s*[-–—]\s*(?P<name>.+?)(?:\s+and \d+ more pages?)?\s+[-–—]\s+.*$')
# A tab has no browser name after it: "Meet - abc-defg-hij", sometimes "... - Camera or microphone recording"
_MEET_TAB = re.compile(r'^Meet\s*[-–—]\s*(?P<name>.+?)(?:\s+[-–—]\s+.*)?$')
MEET_CODE = re.compile(r'\b[a-z]{3}-[a-z]{4}-[a-z]{3}\b')
_FILETIME_UNIX_START = 11644473600            # seconds from 1601, where Windows file times start, to 1970
_TAB_ITEM = 50019                             # UI Automation control type


def apps_using_microphone() -> dict[str, int]:
    """Lower-case exe names (desktop apps) and package names (Store apps) using the microphone now,
    each with the Windows file time it started."""
    using = {}
    for sub in ('NonPackaged', ''):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, f'{_CONSENT}\\{sub}' if sub else _CONSENT)
        except OSError:
            continue
        with key:
            for i in range(10_000):
                try:
                    name = winreg.EnumKey(key, i)
                except OSError:
                    break
                if name == 'NonPackaged':
                    continue
                try:
                    with winreg.OpenKey(key, name) as app:
                        start = winreg.QueryValueEx(app, 'LastUsedTimeStart')[0]
                        stop = winreg.QueryValueEx(app, 'LastUsedTimeStop')[0]
                except OSError:
                    continue
                if start and not stop:           # started and not stopped: in use now
                    using[name.rsplit('#', 1)[-1].lower() if sub else name] = start
    return using


def without_short_use(mic_users: dict[str, int], now: float | None = None) -> set[str]:
    """Drop apps whose short microphone use is not a call: a voice message just started."""
    filetime = ((now if now is not None else time.time()) + _FILETIME_UNIX_START) * 10_000_000
    return {name for name, start in mic_users.items()
            if not name.startswith(VOICE_MESSAGE_APPS) or filetime - start >= VOICE_MESSAGE_SECONDS * 10_000_000}


def visible_windows() -> list[tuple[str, str]]:
    """(lower-case exe name, title) of every visible titled window."""
    import psutil
    import win32gui
    import win32process
    found = []

    def each(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                try:
                    exe = psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1]).name().lower()
                except (psutil.Error, OSError):
                    return True
                found.append((exe, title))
        return True

    win32gui.EnumWindows(each, None)
    return found


def browser_tabs(mic_users: set[str]) -> list[tuple[str, str]]:
    """(exe, tab name) of every tab in the browsers using the microphone; empty if tabs cannot be read."""
    try:
        import comtypes
        import comtypes.client
        import psutil
        import win32gui
        import win32process
        comtypes.CoInitialize()
        comtypes.client.GetModule('UIAutomationCore.dll')
        from comtypes.gen.UIAutomationClient import (CUIAutomation, IUIAutomation, TreeScope_Descendants,
                                                     UIA_ControlTypePropertyId)
        uia = comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)
        condition = uia.CreatePropertyCondition(UIA_ControlTypePropertyId, _TAB_ITEM)
        handles = []

        def each(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
                try:
                    exe = psutil.Process(win32process.GetWindowThreadProcessId(hwnd)[1]).name().lower()
                except (psutil.Error, OSError):
                    return True
                if exe in BROWSERS and exe in mic_users:
                    handles.append((exe, hwnd))
            return True

        win32gui.EnumWindows(each, None)
        tabs = []
        for exe, hwnd in handles:
            found = uia.ElementFromHandle(hwnd).FindAll(TreeScope_Descendants, condition)
            tabs += [(exe, found.GetElement(i).CurrentName or '') for i in range(found.Length)]
        return tabs
    except Exception:                         # the window title check still works
        return []


def _meet_call(name: str) -> dict:
    name = name.strip()
    code = MEET_CODE.search(name)
    return {'key': f'meet:{name}', 'app': 'Google Meet', 'name': name, 'code': code.group(0) if code else None}


def find_call(mic_users: set[str], windows: list[tuple[str, str]], tabs: list[tuple[str, str]] = ()) -> dict | None:
    """The call going on now, as {'key', 'app', 'name', 'code'}, or None."""
    for found, pattern in ((windows, _MEET_TITLE), (tabs, _MEET_TAB)):
        for exe, title in found:
            if exe in BROWSERS and exe in mic_users:
                match = pattern.match(title)
                if match:
                    return _meet_call(match.group('name'))
    for exe, app in APPS.items():
        if exe in mic_users:
            return {'key': exe, 'app': app, 'name': None, 'code': None}
    for package in mic_users:
        for prefix, app in PACKAGED_APPS.items():
            if package.startswith(prefix):
                return {'key': package, 'app': app, 'name': None, 'code': None}
    return None


def current_call() -> dict | None:
    mic_users = without_short_use(apps_using_microphone())
    windows = visible_windows()
    call = find_call(mic_users, windows)
    if (call and call['app'] == 'Google Meet') or not mic_users & BROWSERS:
        return call
    return find_call(mic_users, windows, browser_tabs(mic_users))
