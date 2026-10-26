# coding: utf-8
"""
Tray icon module

Lets the console window minimize to the system tray.
Works on Windows only.

Features:
- Disables the console window's close button (prevents closing it by accident)
- Hides the window to the tray when it is minimized
- Double-clicking the tray icon shows or hides the window
- The tray menu has an Exit item

Note: pystray cannot be imported on Linux without a GUI, so it is imported lazily.
"""

import os
import sys
import time
import threading
import platform
from typing import Optional
from . import logger, set_ui_logger

# Exit callback (passed in by the main program)
_exit_callback = None

# Whether the tray is available (checked in enable_min_to_tray)
_tray_available = None

def _set_exit_callback(callback):
    """Set the exit callback"""
    global _exit_callback
    _exit_callback = callback

def _get_exit_callback():
    return _exit_callback


def _check_tray_available() -> bool:
    """
    Check whether the tray icon can be used

    Returns:
        bool: True if it is available
    """
    global _tray_available

    if _tray_available is not None:
        return _tray_available

    # Not supported outside Windows
    if platform.system() != 'Windows':
        _tray_available = False
        return False

    # Try to import pystray
    try:
        import pystray
        from PIL import Image
        _tray_available = True
    except ImportError as e:
        logger.warning(f"Tray icon unavailable: {e}")
        _tray_available = False
    except Exception as e:
        logger.warning(f"Could not check tray icon support: {e}")
        _tray_available = False

    return _tray_available


# Windows API (initialized lazily)
_win_api_initialized = False
user32 = None
kernel32 = None

SW_HIDE = 0
SW_RESTORE = 9
SW_SHOW = 5
SC_CLOSE = 0xF060
MF_BYCOMMAND = 0x00000000


def _init_win_api():
    """Initialize the Windows API"""
    global _win_api_initialized, user32, kernel32

    if _win_api_initialized:
        return

    if platform.system() != 'Windows':
        return

    try:
        import ctypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        _win_api_initialized = True
    except Exception as e:
        logger.warning(f"Could not initialize the Windows API: {e}")


# Globals
_tray_instance: Optional['_TraySystem'] = None
_lock = threading.Lock()


def _get_console_hwnd() -> int:
    """Get the console window handle"""
    _init_win_api()
    if kernel32 is None:
        return 0
    return kernel32.GetConsoleWindow()


def _disable_close_button(hwnd: int) -> None:
    """Disable the window's close button"""
    if user32 is None:
        return
    h_menu = user32.GetSystemMenu(hwnd, False)
    if h_menu:
        user32.DeleteMenu(h_menu, SC_CLOSE, MF_BYCOMMAND)


def _enable_close_button(hwnd: int) -> None:
    """Restore the window's close button"""
    if user32 is None:
        return
    user32.GetSystemMenu(hwnd, True)


def _is_window_minimized(hwnd: int) -> bool:
    """Check whether the window is minimized"""
    if user32 is None:
        return False
    return user32.IsIconic(hwnd) != 0


def _is_window_visible(hwnd: int) -> bool:
    """Check whether the window is visible"""
    if user32 is None:
        return False
    return user32.IsWindowVisible(hwnd) != 0


def _create_icon(icon_path: Optional[str] = None):
    """
    Create the tray icon image

    Loads the icon file if it exists, otherwise draws one.

    Args:
        icon_path: Path to the icon file

    Returns:
        PIL Image object
    """
    from PIL import Image, ImageDraw

    # Load the icon file if it exists
    if icon_path and os.path.exists(icon_path):
        try:
            image = Image.open(icon_path)
            if image.mode != 'RGBA':
                image = image.convert('RGBA')
            return image.resize((64, 64), Image.Resampling.LANCZOS)
        except Exception:
            pass  # Fall back to drawing one

    # Draw an icon
    size = 64
    scale = 4
    real_size = size * scale

    image = Image.new('RGBA', (real_size, real_size), (0, 0, 0, 0))
    dc = ImageDraw.Draw(image)

    blue = (55, 118, 171)
    yellow = (255, 211, 67)
    white = (255, 255, 255)

    # Blue rounded background
    m = 2 * scale
    dc.rounded_rectangle(
        [m, m, real_size - m, real_size - m],
        radius=real_size // 4,
        fill=blue
    )

    # Yellow circle
    center = real_size // 2
    r = real_size // 3.5
    dc.ellipse([center - r, center - r, center + r, center + r], fill=yellow)

    # White dot
    r2 = r // 2
    dc.ellipse([center - r2, center - r2, center + r2, center + r2], fill=white)

    return image.resize((size, size), Image.Resampling.LANCZOS)


class _TraySystem:
    """Internal tray system class"""

    def __init__(self, name: Optional[str] = None, icon_path: Optional[str] = None, more_options: list = None):
        # Import pystray lazily
        import pystray
        from pystray import MenuItem as item

        self.hwnd = _get_console_hwnd()
        self.should_exit = False
        self.title = name if name else (os.path.basename(sys.argv[0]) or "Console App")

        # Disable the close button
        if self.hwnd:
            _disable_close_button(self.hwnd)

        # Build the menu
        menu_items = [
            item(f"{self.title}", lambda: None, enabled=False),
            item('👁️ Show/Hide', self.toggle_window, default=True),
        ]

        # Add extra items
        if more_options:
            for opt_name, opt_func in more_options:
                menu_items.append(item(opt_name, opt_func))

        menu_items.append(item('❌ Exit', self.on_exit))

        self.icon = pystray.Icon(
            "console_tray",
            _create_icon(icon_path),
            title=f"{self.title}",
            menu=tuple(menu_items)
        )

    def toggle_window(self) -> None:
        """Show or hide the window"""
        if not self.hwnd or user32 is None:
            return

        if _is_window_visible(self.hwnd):
            user32.ShowWindow(self.hwnd, SW_HIDE)
        else:
            user32.ShowWindow(self.hwnd, SW_RESTORE)
            user32.SetForegroundWindow(self.hwnd)

    def monitor_loop(self) -> None:
        """Monitor thread: watches for the window being minimized"""
        while not self.should_exit:
            if self.hwnd and user32:
                # Visible and minimized -> hide to the tray
                if _is_window_visible(self.hwnd) and _is_window_minimized(self.hwnd):
                    user32.ShowWindow(self.hwnd, SW_HIDE)
            time.sleep(0.2)

    def on_exit(self, icon, item) -> None:
        """Handle Exit from the tray menu"""
        exit_callback = _get_exit_callback()

        logger.info("Tray exit: the user chose Exit, cleaning up and exiting")

        # 1. Set the exit flag to stop the monitor loop
        self.should_exit = True
        logger.debug("Tray exit flag set")

        # 2. Restore the close button and show the window
        if self.hwnd and user32:
            _enable_close_button(self.hwnd)
            user32.ShowWindow(self.hwnd, SW_RESTORE)
            logger.debug("Window restored")

        # 3. Call the exit callback to ask the main program to exit
        if exit_callback:
            try:
                logger.debug("Calling the exit callback...")
                exit_callback()
                logger.info("Exit callback called")
            except Exception as e:
                logger.error(f"Error in the exit callback: {e}")



        # 5. Stop the tray icon
        try:
            logger.debug("Stopping the tray icon thread...")
            self.icon.stop()
            logger.debug("Tray icon thread stopped")
        except Exception as e:
            logger.warning(f"Error stopping the tray icon: {e}")

    def start(self) -> None:
        """Start the tray system"""
        # Tray icon thread
        t_tray = threading.Thread(target=self.icon.run, daemon=False)
        t_tray.start()

        # Window monitor thread
        t_monitor = threading.Thread(target=self.monitor_loop, daemon=True)
        t_monitor.start()

        # Hide the window at startup
        self.toggle_window()


def enable_min_to_tray(name: Optional[str] = None, icon_path: Optional[str] = None, exit_callback=None, more_options: list = None) -> None:
    """
    Enable minimize-to-tray

    Does nothing if there is no console window (for example when run as .pyw)
    or when running without a GUI, such as on Linux.

    Args:
        name: Name shown on the tray icon; defaults to the program name
        icon_path: Path to the icon file; an icon is drawn if omitted
        exit_callback: Called when the user chooses Exit from the tray menu
        more_options: Extra menu items as [(label, callback), ...]
    """
    global _tray_instance

    # Set the exit callback
    if exit_callback is not None:
        _set_exit_callback(exit_callback)

    # Check that the tray is available
    if not _check_tray_available():
        logger.info("Tray icon unavailable, skipping")
        return

    # DPI awareness
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        pass

    with _lock:
        if _tray_instance is not None:
            return  # Already started

        if not _get_console_hwnd():
            return  # No console window

        _tray_instance = _TraySystem(name, icon_path, more_options)
        _tray_instance.start()



def stop_tray() -> None:
    """Stop the tray icon"""
    global _tray_instance
    if _tray_instance and _tray_instance.icon:
        try:
            _tray_instance.icon.stop()
        except Exception:
            pass
    _tray_instance = None


if __name__ == "__main__":
    enable_min_to_tray()
    print("Running... double-click the tray icon to hide this window.")
    while True:
        time.sleep(1)
