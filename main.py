"""
Utter: a desktop window for the dictation client in dictation/.

Live status, insights, dictionary and settings. Closing the window leaves
dictation running in the background.

    .venv\\Scripts\\pythonw.exe main.py
"""
import ctypes
import os
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
os.chdir(BASE_DIR)
sys.path.insert(0, str(BASE_DIR))

TITLE = 'Utter'
ICON = BASE_DIR / 'assets' / 'utter.ico'
_mutex = None


def _already_running() -> bool:
    """Single instance: bring the open window forward instead of opening another."""
    global _mutex
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    _mutex = kernel32.CreateMutexW(None, False, 'Local\\UtterDesktopApp')
    if ctypes.get_last_error() != 183:  # ERROR_ALREADY_EXISTS
        return False
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, TITLE)
    if hwnd:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    return True


def _set_window_icon():
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, TITLE)
    if not hwnd or not ICON.exists():
        return
    for size, which in ((16, 0), (32, 1)):  # ICON_SMALL, ICON_BIG
        handle = user32.LoadImageW(None, str(ICON), 1, size, size, 0x10)  # IMAGE_ICON, LR_LOADFROMFILE
        if handle:
            user32.SendMessageW(hwnd, 0x80, which, handle)  # WM_SETICON


def main():
    if _already_running():
        return
    # Own taskbar identity instead of grouping under python.exe.
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('Utter.Desktop')

    from utter import engine
    from utter.api import Api
    import webview
    from util import app_settings

    settings = {**app_settings.APP_DEFAULTS, **app_settings.load()}
    if settings.get('start_engine_with_app') and not engine.client_status()['running']:
        engine.start_engine()

    background = '#151817' if settings.get('theme') == 'dark' else '#F4F2EC'
    api = Api()
    # Read today's calendar now, so the Notetaker page does not wait ~2 s for Google when first opened.
    import threading
    threading.Thread(target=api.get_today_meetings, daemon=True, name='calendar-warm').start()
    window = webview.create_window(
        TITLE, str(BASE_DIR / 'utter' / 'web' / 'index.html'), js_api=api,
        width=1240, height=820, min_size=(980, 660), background_color=background)
    window.events.shown += _set_window_icon
    window.events.shown += lambda: _watch_calls(webview, api, window)
    _zoom(api, window)
    webview.start(storage_path=str(BASE_DIR / '.webview'))


def _zoom(api, window):
    """Ctrl+Plus, Ctrl+Minus, Ctrl+0 and Ctrl+wheel make everything bigger or smaller.

    pywebview turns off the browser's own shortcuts (which would also bring back reload and
    print), so the page catches the keys and asks for a zoom level; WebView2 scales the page.
    The level is kept in state/window.json and applied again whenever the page loads.
    """
    def apply(factor):
        from System import Func, Type     # .NET is loaded only once webview.start() has run
        form = window.native

        def set_zoom():
            form.webview.ZoomFactor = float(factor)
        form.Invoke(Func[Type](set_zoom))

    api._apply_zoom = apply
    window.events.loaded += lambda: apply(api.get_zoom())


def _watch_calls(webview, api, window):
    """When a call starts (Google Meet, Zoom, Teams), a small window on top offers to take notes.
    It sits bottom-right like a Windows notification, clear of browser tabs; drag it anywhere.

    The window is made the first time it is needed and afterwards only hidden and shown, and it is
    pinned on top every time it shows: a second popup made after the first was destroyed was not
    kept on top (pywebview on WinForms), so a call's popup sat behind the browser. It cannot be
    made hidden up front either: pywebview's show() then waits forever for a first "shown" event.
    """
    width, height = 470, 76
    popup = {'window': None}

    def pin(win):
        user32 = ctypes.WinDLL('user32')
        user32.SetWindowPos.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [ctypes.c_int] * 4 + [ctypes.c_uint]
        # HWND_TOPMOST; SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        user32.SetWindowPos(win.native.Handle.ToInt64(), -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010 | 0x0040)

    def show():
        if popup['window'] is None:
            screen = webview.screens[0]
            popup['window'] = webview.create_window(
                'Utter call', str(BASE_DIR / 'utter' / 'web' / 'popup.html'), js_api=api,
                width=width, height=height, x=screen.x + screen.width - width - 24,
                y=screen.y + screen.height - height - 72,
                frameless=True, on_top=True, resizable=False, focus=False, background_color='#141716')
        else:
            popup['window'].show()
        pin(popup['window'])

    def hide():
        if popup['window'] is not None:
            popup['window'].hide()

    def open_main():
        window.restore()
        window.show()
        window.evaluate_js("showPage('notetaker')")

    api._start_call_watch(show, hide, open_main)


if __name__ == '__main__':
    main()
