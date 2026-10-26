"""Notice when a call starts, so the Notetaker can offer to take notes.

A call is an app that is using the microphone right now (Windows records this
per app in the privacy "consent store") plus a window that names the meeting:
- Google Meet in a browser: a window titled "Meet - <code or name>". Only the
  active tab shows in a browser's title, so a Meet tab behind another tab is
  missed until it is brought to the front.
- Zoom or Microsoft Teams desktop apps: the app itself using the microphone.
Nothing is recorded or sent; this only reads window titles and the registry.
"""
from __future__ import annotations

import re
import winreg

_CONSENT = r'Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone'
BROWSERS = {'chrome.exe', 'msedge.exe', 'brave.exe', 'firefox.exe', 'arc.exe', 'opera.exe', 'vivaldi.exe'}
APPS = {'zoom.exe': 'Zoom', 'ms-teams.exe': 'Microsoft Teams', 'teams.exe': 'Microsoft Teams'}
PACKAGED_APPS = {'MSTeams': 'Microsoft Teams'}
# "Meet - abc-defg-hij and 6 more pages - Personal - Microsoft Edge" -> "abc-defg-hij"
_MEET_TITLE = re.compile(r'^Meet\s*[-–—]\s*(?P<name>.+?)(?:\s+and \d+ more pages?)?\s+[-–—]\s+.*$')
MEET_CODE = re.compile(r'\b[a-z]{3}-[a-z]{4}-[a-z]{3}\b')


def apps_using_microphone() -> set[str]:
    """Lower-case exe names (desktop apps) and package names (Store apps) using the microphone now."""
    using = set()
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
                    using.add(name.rsplit('#', 1)[-1].lower() if sub else name)
    return using


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


def find_call(mic_users: set[str], windows: list[tuple[str, str]]) -> dict | None:
    """The call going on now, as {'key', 'app', 'name', 'code'}, or None."""
    for exe, title in windows:
        if exe in BROWSERS and exe in mic_users:
            match = _MEET_TITLE.match(title)
            if match:
                name = match.group('name').strip()
                code = MEET_CODE.search(name)
                return {'key': f'meet:{name}', 'app': 'Google Meet', 'name': name, 'code': code.group(0) if code else None}
    for exe, app in APPS.items():
        if exe in mic_users:
            return {'key': exe, 'app': app, 'name': None, 'code': None}
    for package in mic_users:
        for prefix, app in PACKAGED_APPS.items():
            if package.startswith(prefix):
                return {'key': package, 'app': app, 'name': None, 'code': None}
    return None


def current_call() -> dict | None:
    return find_call(apps_using_microphone(), visible_windows())
