"""
Toast Text window module

Floating message window built on a Text widget, for streamed output (such as live LLM output).
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
    STREAMING_TEXT_HEIGHT,
    NON_STREAMING_TEXT_HEIGHT,
    HEIGHT_PADDING,
    TEXT_WRAP_MODE,
)
from .toast_logger import get_toast_logger

# Logging (uses the main program's logger if it has one)
logger = get_toast_logger(__name__)


class ToastWindowText(ToastWindowBase):
    """Floating message window built on a Text widget

    For streamed output: text is inserted incrementally and the window grows to fit.

    Features:
        - Streamed text output (shown as it arrives)
        - Window height adjusts to the content
        - Markdown rendering (applied when the stream finishes)
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
        """Create a floating message window built on a Text widget

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

        # Font object used to measure line height
        font_name = self.font_family if self.font_family else DEFAULT_FONT_FAMILY
        self.my_font = font.Font(family=font_name, size=self.font_size)
        self.line_height = self.my_font.metrics('linespace')
        self.last_char_count = 0

        # Create the Text widget
        text_height = STREAMING_TEXT_HEIGHT if streaming else NON_STREAMING_TEXT_HEIGHT

        self.text_area = tk.Text(
            self.window,
            font=self.my_font,
            fg=self.fg,
            bg=self.bg,
            padx=DEFAULT_PADDING_X,
            pady=DEFAULT_PADDING_Y,
            borderwidth=0,
            highlightthickness=0,
            wrap=TEXT_WRAP_MODE,
            insertofftime=0,
            state=tk.DISABLED,
            cursor="arrow",
            height=text_height
        )

        # Anchor at the top left and fill the window with fill=BOTH
        self.text_area.pack(side=tk.TOP, anchor='nw', fill=tk.BOTH, expand=True)

        # Turn off the Text widget's own wheel scrolling and pass the event to the window
        # Binding to a handler stops Text's built-in scrolling but still forwards the event
        def pass_to_window(event):
            # Let the window handle the event
            self.window.event_generate('<MouseWheel>', x=event.x, y=event.y, delta=event.delta)
            return "break"

        self.text_area.bind('<MouseWheel>', pass_to_window)
        self.text_area.bind('<Button-4>', pass_to_window)  # Linux
        self.text_area.bind('<Button-5>', pass_to_window)  # Linux

        # Insert the initial text
        if text:
            self.text_area.config(state=tk.NORMAL)
            self.text_area.insert(tk.END, text)
            self.text_area.config(state=tk.DISABLED)
            self.last_char_count = len(text)

        # Force a layout update
        self.window.update_idletasks()

        # When not streaming, set the window width first, then count the real lines
        if not streaming and text:
            # Set the window width first (with a temporary one-line height)
            calculated_width = self._calculate_actual_width()
            screen_width = self.window.winfo_screenwidth()
            screen_height = self.window.winfo_screenheight()
            temp_x = (screen_width - calculated_width) // 2
            temp_y = screen_height // 2
            self.window.geometry(f'{calculated_width}x100+{temp_x}+{temp_y}')

            # Update so the Text widget rewraps at the correct width
            self.window.update_idletasks()

            # Now count the real lines
            result = self.text_area.count('1.0', 'end', 'displaylines')
            actual_lines = result[0] if result else 1
            self.text_area.config(height=actual_lines)

        # Set the initial window position (the line count is now correct)
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

            # Update the window so the sizes are correct
            self.window.update_idletasks()

            # Use the base class width calculation
            calculated_width = self._calculate_actual_width()

            # Number of lines actually displayed
            result = self.text_area.count('1.0', 'end', 'displaylines')
            current_lines = result[0] if result else 1

            # Exact height: lines * line height + top and bottom padding
            needed_h = (current_lines * self.line_height) + HEIGHT_PADDING

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

            self.window.geometry(f'{window_width}x{int(window_height)}+{x}+{y}')
        except tk.TclError as e:
            logger.warning(f"Could not set the window position: {e}")

    def update_text(self, new_text: str) -> None:
        """Update the text (incremental insert)

        Only works while streaming. Appends the new characters to the Text widget
        and resizes the window to fit.

        Args:
            new_text: The new full text
        """
        if not self.streaming:
            return

        # Check the window still exists
        try:
            if not self.window.winfo_exists():
                self.streaming = False
                return
        except tk.TclError:
            self.streaming = False
            return

        # Work out the new characters
        current_char_count = len(new_text)
        if current_char_count > self.last_char_count:
            # Save the full text
            self.full_text = new_text

            # The new part
            new_chars = new_text[self.last_char_count:]

            try:
                # Update the Text widget
                self.text_area.config(state=tk.NORMAL)
                self.text_area.insert(tk.END, new_chars)
                self.text_area.config(state=tk.DISABLED)

                # Force the layout to be calculated now
                self.window.update_idletasks()

                # Calculate the height the window needs
                result = self.text_area.count('1.0', 'end', 'displaylines')
                current_lines = result[0] if result else 1
                needed_h = (current_lines * self.line_height) + HEIGHT_PADDING
                current_h = self.window.winfo_height()
                current_w = self.window.winfo_width()

                # Make the Text widget tall enough for every line
                self.text_area.config(height=current_lines)

                # Grow the window if needed
                if needed_h > current_h:
                    curr_x = self.window.winfo_x()
                    curr_y = self.window.winfo_y()
                    self.window.geometry(f"{current_w}x{int(needed_h)}+{curr_x}+{curr_y}")

                self.last_char_count = current_char_count
            except tk.TclError:
                # The window has been destroyed: stop streaming
                self.streaming = False

    def _destroy_content_widget(self) -> None:
        """Destroy the Text widget"""
        if hasattr(self, 'text_area'):
            try:
                self.text_area.destroy()
            except tk.TclError:
                pass
