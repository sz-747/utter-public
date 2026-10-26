"""
Foreground window detector

Finds out which application is in the foreground (Windows), for Insights and the edit watcher
"""


def get_active_window_info() -> dict:
    """
    Return information about the foreground window

    Returns:
        A dict with the window info (empty if it cannot be read):
        - title: window title
        - class_name: window class name
        - process_name: process name
        - app_name: application name (best guess)
    """
    try:
        import win32gui
        import win32process

        hwnd = win32gui.GetForegroundWindow()

        # Window title
        title = win32gui.GetWindowText(hwnd)

        # Window class name
        class_name = win32gui.GetClassName(hwnd)

        # Process ID and process name
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            import psutil
            process = psutil.Process(pid)
            process_name = process.name()
        except:
            process_name = ""

        # Guess the application name
        app_name = _guess_app_name(title, class_name, process_name)

        return {
            'hwnd': hwnd,
            'title': title,
            'class_name': class_name,
            'process_name': process_name,
            'app_name': app_name
        }
    except ImportError:
        # Dependencies not installed: return nothing
        return {}
    except Exception:
        return {}


def _guess_app_name(title: str, class_name: str, process_name: str) -> str:
    """
    Guess the application name from the window info

    Args:
        title: window title
        class_name: window class name
        process_name: process name

    Returns:
        The guessed application name
    """
    # Prefer the process name
    if process_name:
        # Drop the .exe suffix
        name = process_name.replace('.exe', '').lower()
        return name

    # Then the class name
    if class_name:
        # Common Windows class names
        class_mappings = {
            'chrome': 'Chrome',
            'msedge': 'Edge',
            'firefox': 'Firefox',
            'notepad': 'Notepad',
            'notepad++': 'Notepad++',
            'vscode': 'VSCode',
            'winword': 'Word',
            'xlmain': 'Excel',
            'pptmain': 'PowerPoint',
            'wndclass_desktop_glass': 'Desktop',
        }

        class_lower = class_name.lower()
        for key, value in class_mappings.items():
            if key in class_lower:
                return value

    # Finally, the first word of the title
    if title:
        first_word = title.split()[0]
        return first_word

    return ''


def is_likely_editor(window_info: dict) -> bool:
    """
    Is the current window probably an editor?

    Args:
        window_info: window info dict

    Returns:
        True if it is probably an editor
    """
    if not window_info:
        return True  # Default to the safe side

    title = window_info.get('title', '').lower()
    class_name = window_info.get('class_name', '').lower()
    process_name = window_info.get('process_name', '').lower()

    # Editor keywords
    editor_keywords = [
        'visual studio', 'vscode', 'vim', 'nano', 'emacs',
        'notepad', 'sublime', 'atom', 'intellij', 'pycharm',
        'webstorm', 'idea', 'editor'
    ]

    # Check the title
    for keyword in editor_keywords:
        if keyword in title or keyword in class_name or keyword in process_name:
            return True

    return False


def is_likely_browser(window_info: dict) -> bool:
    """
    Is the current window probably a browser?

    Args:
        window_info: window info dict

    Returns:
        True if it is probably a browser
    """
    if not window_info:
        return False

    class_name = window_info.get('class_name', '').lower()
    process_name = window_info.get('process_name', '').lower()

    browser_keywords = ['chrome', 'firefox', 'edge', 'safari', 'opera', 'brave']

    for keyword in browser_keywords:
        if keyword in class_name or keyword in process_name:
            return True

    return False
