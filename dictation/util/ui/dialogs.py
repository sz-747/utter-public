# coding: utf-8
"""
Dialog base module

Shared helpers and base classes for dialogs.
"""

import ctypes
import tkinter as tk
from tkinter import ttk
from typing import Optional, Callable

from .toast_constants import DEFAULT_FONT_FAMILY
from . import logger

# DPI awareness (matches toast_base.py)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except (OSError, AttributeError):
    pass


# ============================================================
# Helpers
# ============================================================

def create_modal_dialog(
    title: str,
    width: int = 600,
    height: int = 400,
    resizable: bool = False,
    withdraw: bool = True
) -> tk.Toplevel:
    """
    Create a modal dialog window

    Args:
        title: Window title
        width: Window width (pixels)
        height: Window height (pixels)
        resizable: Whether the window can be resized
        withdraw: Whether to hide the window at first (avoids flicker); default True

    Returns:
        tkinter Toplevel window
    """
    # Create the Toplevel window
    dialog = tk.Toplevel()
    dialog.title(title)

    # Hide it first to avoid flicker
    if withdraw:
        dialog.withdraw()

    # Set the window size
    dialog.geometry(f"{width}x{height}")
    dialog.resizable(resizable, resizable)

    # Make it modal
    dialog.transient()  # Belongs to the main window
    dialog.grab_set()   # Take focus so the user can't use other windows

    # Center it
    _center_window(dialog, width, height)

    logger.debug(f"Created modal dialog: {title} ({width}x{height})")

    return dialog


def _center_window(window: tk.Toplevel, width: int, height: int) -> None:
    """
    Center a window on the screen

    Args:
        window: Window object
        width: Window width
        height: Window height
    """
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()

    x = (screen_width - width) // 2
    y = (screen_height - height) // 2

    window.geometry(f"+{x}+{y}")


def create_label_button_frame(
    parent: tk.Widget,
    label_text: str,
    on_confirm: Callable[[], None],
    on_cancel: Callable[[], None],
    confirm_text: str = "OK",
    cancel_text: str = "Cancel"
) -> ttk.Frame:
    """
    Create the standard button row

    Args:
        parent: Parent container
        label_text: Description text
        on_confirm: OK button callback
        on_cancel: Cancel button callback
        confirm_text: OK button text
        cancel_text: Cancel button text

    Returns:
        The button Frame
    """
    frame = ttk.Frame(parent)
    frame.pack(pady=10)

    ttk.Button(frame, text=confirm_text, command=on_confirm, width=10).pack(side="left", padx=5)
    ttk.Button(frame, text=cancel_text, command=on_cancel, width=10).pack(side="left", padx=5)

    return frame


def create_scrolled_text(
    parent: tk.Widget,
    height: int = 5,
    font: tuple = (DEFAULT_FONT_FAMILY, 10)
) -> tk.Text:
    """
    Create a text box with a scrollbar

    Args:
        parent: Parent container
        height: Text box height (lines)
        font: Font settings

    Returns:
        The Text widget
    """
    # Create the Text widget
    text_widget = tk.Text(parent, height=height, font=font, wrap="word")

    # Add a scrollbar
    scrollbar = ttk.Scrollbar(parent, command=text_widget.yview)
    text_widget.configure(yscrollcommand=scrollbar.set)

    return text_widget


def pack_scrolled_text(
    text_widget: tk.Text,
    scrollbar: ttk.Scrollbar,
    label_text: Optional[str] = None,
    parent: tk.Widget = None,
    padx: int = 10,
    pady_top: int = 10,
    pady_bottom: int = 5
) -> None:
    """
    Lay out a text box with a scrollbar

    Args:
        text_widget: Text widget
        scrollbar: Scrollbar
        label_text: Optional label text
        parent: Parent container (for the label)
        padx: Horizontal margin
        pady_top: Top margin
        pady_bottom: Bottom margin
    """
    # Add the label (if given)
    if label_text and parent:
        ttk.Label(parent, text=label_text).pack(anchor="w", padx=padx, pady=(pady_top, 0))

    # Lay out the text box and scrollbar
    text_widget.pack(fill="both", expand=True, padx=padx, pady=(0 if label_text else pady_top, pady_bottom))
    scrollbar.pack(side="right", fill="y")


class DialogResult:
    """Dialog result wrapper"""

    def __init__(self, confirmed: bool, **data):
        self.confirmed = confirmed  # Whether the user clicked OK
        self.data = data             # Data returned by the dialog

    def __bool__(self) -> bool:
        """Whether it was confirmed"""
        return self.confirmed

    def get(self, key: str, default=None):
        """Get a data value"""
        return self.data.get(key, default)


def wait_window(dialog: tk.Toplevel) -> None:
    """
    Wait for a window to close (standard modal dialog usage)

    Args:
        dialog: Dialog window
    """
    dialog.wait_window()
