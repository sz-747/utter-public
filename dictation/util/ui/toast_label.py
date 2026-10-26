"""
Toast Label window module

Floating message window built on a Label widget, for ordinary notifications.
"""
import logging
import tkinter as tk
from tkinter import font
from typing import Optional, Callable, Union

from .toast_base import (
    ToastWindowBase,
)
from .toast_constants import (
    DEFAULT_FONT_FAMILY,
    DEFAULT_PADDING_X,
    DEFAULT_PADDING_Y,
    MIN_WINDOW_HEIGHT,
    LABEL_HEIGHT_PADDING,
)
from .toast_logger import get_toast_logger

# Logging (uses the main program's logger if it has one)
logger = get_toast_logger(__name__)


class ToastWindowLabel(ToastWindowBase):
    """Floating message window built on a Label widget

    For ordinary notifications; supports simple text updates.

    Features:
        - Simple, efficient text display
        - Automatic wrapping (using wraplength)
        - Markdown rendering
    """

    def __init__(
        self,
        parent_root: tk.Tk,
        text: str,
        font_size: int = 14,
        font_family: str = '',
        bg: str = '#075077',
        fg: str = 'white',
        duration: int = 3000,
        initial_width: Union[float, int] = 400,
        initial_height: int = 0,
        streaming: bool = False,
        stop_callback: Optional[Callable[[], None]] = None,
        markdown: bool = False,
        editable: bool = False
    ) -> None:
        """Create a floating message window built on a Label widget

        Args:
            parent_root: Parent window (the Tk root)
            text: Initial text
            font_size: Font size (pixels)
            font_family: Font name; an empty string uses the default font
            bg: Background color
            fg: Foreground (text) color
            duration: Time before it closes automatically (milliseconds)
            initial_width: Initial width; 0-1 is a fraction of the screen, >1 is pixels
            initial_height: Initial height; 0 means calculate it automatically
            streaming: Whether the text streams in
            stop_callback: Called when the window closes
            markdown: Whether to render Markdown
            editable: Whether the text can be edited after Markdown rendering
        """
        # Initialize the base class
        super().__init__(
            parent_root, text, font_size, font_family, bg, fg,
            duration, initial_width, initial_height, streaming,
            stop_callback, markdown, editable
        )

        # Calculate the actual width
        actual_width = self._calculate_actual_width()

        # Used for incremental updates
        self.last_char_count = 0

        # Use the default font if none was given
        font_name = font_family if font_family else DEFAULT_FONT_FAMILY

        # Create the text label
        self.label = tk.Label(
            self.window,
            text=text,
            font=(font_name, font_size),
            fg=fg,
            bg=bg,
            justify=tk.LEFT,
            wraplength=actual_width - (DEFAULT_PADDING_X * 2),
            anchor='nw'
        )

        # Fill the window with fill=BOTH and expand=True
        self.label.pack(
            side=tk.TOP,
            fill=tk.BOTH,
            expand=True,
            padx=DEFAULT_PADDING_X,
            pady=DEFAULT_PADDING_Y
        )

        # Initialize the character count
        if text:
            self.last_char_count = len(text)

        # Force a layout update
        self.window.update_idletasks()

        # Set the initial window position
        self._set_window_position(initial=True)

        # If not streaming and Markdown is on, render it now
        if not streaming and markdown:
            self.window.update()
            self._switch_to_markdown()

    def _set_window_position(self, initial: bool = False) -> None:
        """Set the window position

        Args:
            initial: Whether this is the initial position (screen center, one line high)
        """
        try:
            screen_width = self.window.winfo_screenwidth()
            screen_height = self.window.winfo_screenheight()

            # Calculate the initial width
            calculated_width = self._calculate_actual_width()

            # The Label's preferred height
            needed_h = self.label.winfo_reqheight() + LABEL_HEIGHT_PADDING

            # If an initial height was set, use the larger value
            if self.initial_height > 0:
                window_height = max(self.initial_height, needed_h)
            else:
                window_height = needed_h

            # Enforce the minimum height
            window_height = max(window_height, MIN_WINDOW_HEIGHT)
            window_width = calculated_width

            if initial:
                # Initial position: centered horizontally, top at the middle of the screen
                x = (screen_width - window_width) // 2
                y = screen_height // 2
            else:
                # Keep the current position, only change the size
                x = self.window.winfo_x()
                y = self.window.winfo_y()

            self.window.geometry(f'{window_width}x{window_height}+{x}+{y}')
        except tk.TclError as e:
            logger.warning(f"Could not set the window position: {e}")

    def update_text(self, new_text: str) -> None:
        """Update the text

        Label cannot insert text incrementally, so every update replaces all of it.

        Args:
            new_text: The new full text
        """
        if not self.streaming:
            return

        # Work out the new characters
        current_char_count = len(new_text)
        if current_char_count > self.last_char_count:
            # Save the full text
            self.full_text = new_text

            try:
                # Label cannot insert incrementally, so replace all the text
                self.label.config(text=new_text)

                # Force the layout to be calculated now
                self.window.update_idletasks()

                # Calculate the height the window needs
                needed_h = self.label.winfo_reqheight() + LABEL_HEIGHT_PADDING
                current_h = self.window.winfo_height()
                current_w = self.window.winfo_width()

                # Grow the window if needed
                if needed_h > current_h:
                    curr_x = self.window.winfo_x()
                    curr_y = self.window.winfo_y()
                    self.window.geometry(f"{current_w}x{int(needed_h)}+{curr_x}+{curr_y}")

                self.last_char_count = current_char_count
            except tk.TclError:
                # The window has been destroyed
                self.streaming = False

    def _destroy_content_widget(self) -> None:
        """Destroy the Label widget"""
        if hasattr(self, 'label'):
            try:
                self.label.destroy()
            except tk.TclError:
                pass
