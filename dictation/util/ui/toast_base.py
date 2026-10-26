"""
Toast window base module

Provides the abstract base class for toast windows.
"""
import logging
import tkinter as tk
from tkinter import font
from typing import Optional, Callable, Union
from abc import ABC, abstractmethod
import ctypes

import markdown
from tkhtmlview import HTMLLabel

from .toast_constants import (
    DEFAULT_FONT_FAMILY,
    DEFAULT_PADDING_X,
    DEFAULT_PADDING_Y,
    MIN_WINDOW_HEIGHT,
    MARKDOWN_MIN_HEIGHT,
    SCROLL_STEP,
    DESTROY_DELAY_MS,
)
from . import logger

# DPI awareness (called once only)
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except (OSError, AttributeError):
    # Windows 7, or a system without DPI awareness support
    pass


# ============================================================
# Toast window abstract base class
# ============================================================

class ToastWindowBase(ABC):
    """Toast window abstract base class

    Handles window creation, dragging, mouse events and timed closing.
    Subclasses must implement update_text and _destroy_content_widget.

    Attributes:
        window: tkinter Toplevel window
        streaming: Whether the text streams in
        markdown: Whether Markdown rendering is on
        full_text: The full text content
    """

    def __init__(
        self,
        parent_root: tk.Tk,
        text: str,
        font_size: int,
        font_family: str,
        bg: str,
        fg: str,
        duration: int,
        initial_width: Union[float, int],
        initial_height: int,
        streaming: bool,
        stop_callback: Optional[Callable[[], None]],
        markdown_enabled: bool,
        editable: bool = False
    ) -> None:
        """Initialize the toast window base class

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
            markdown_enabled: Whether to render Markdown
            editable: Whether the text can be edited after Markdown rendering
        """
        # Basic attributes
        self.parent_root = parent_root
        self.stop_callback = stop_callback
        self.streaming = streaming
        self.markdown = markdown_enabled
        self.editable = editable
        self.duration = duration
        self.initial_width = initial_width
        self.initial_height = initial_height

        # State flags
        self.pause = False
        self.mouse_inside = False
        self.timer_id: Optional[str] = None

        # Drag position
        self.x = 0
        self.y = 0

        # Full text and style settings (used for Markdown rendering)
        self.full_text = text
        self.font_size = font_size
        self.font_family = font_family if font_family else DEFAULT_FONT_FAMILY
        self.bg = bg
        self.fg = fg

        # Create the window
        self.window = tk.Toplevel(parent_root)
        self.window.hang_on = False

        # Window attributes
        self.window.overrideredirect(True)  # No border
        self.window.attributes('-topmost', True)  # Stay on top
        self.window.configure(bg=bg)
        self.window.resizable(True, True)
        self.window.pack_propagate(False)

        # Bind common events
        self._bind_common_events()

        # Show the window
        self.window.deiconify()

        # If not streaming, start the close timer
        if not self.streaming:
            self._start_destroy_timer()

    def _bind_common_events(self) -> None:
        """Bind common events (drag, mouse enter/leave, wheel, Esc, copy)"""
        self.window.bind('<ButtonPress-1>', self._on_drag_start)
        self.window.bind('<ButtonRelease-1>', self._on_drag_stop)
        self.window.bind('<B1-Motion>', self._on_drag_motion)
        self.window.bind('<Escape>', self._destroy_window)
        self.window.bind('<Enter>', self._on_mouse_enter)
        self.window.bind('<Leave>', self._on_mouse_leave)
        self.window.bind('<MouseWheel>', self._on_mouse_wheel)
        self.window.bind('<Button-4>', self._on_mouse_wheel)  # Linux scroll up
        self.window.bind('<Button-5>', self._on_mouse_wheel)  # Linux scroll down
        self.window.bind('<Control-c>', self._on_copy)        # Ctrl+C copies

    def _calculate_actual_width(self) -> int:
        """Calculate the actual window width

        Returns:
            Window width (pixels)
        """
        screen_width = self.window.winfo_screenwidth()
        if 0 < self.initial_width < 1:
            # A fraction between 0 and 1: share of the screen width
            return int(screen_width * self.initial_width)
        else:
            # Absolute value (pixels)
            return int(self.initial_width)

    @staticmethod
    def _invert_color(hex_color: str) -> str:
        """Invert a hex color

        Args:
            hex_color: Hex color (e.g. '#075077')

        Returns:
            The inverted hex color
        """
        # Strip the # prefix
        hex_color = hex_color.lstrip('#')
        # Parse the RGB values
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        # Invert
        inv_r = 255 - r
        inv_g = 255 - g
        inv_b = 255 - b
        return f"#{inv_r:02x}{inv_g:02x}{inv_b:02x}"

    # --------------------------------------------------------
    # Mouse events
    # --------------------------------------------------------

    def _on_mouse_enter(self, event: tk.Event) -> None:
        """Mouse entered the window: pause the close timer"""
        self.mouse_inside = True
        if self.timer_id:
            self.window.after_cancel(self.timer_id)
            self.timer_id = None

    def _on_mouse_leave(self, event: tk.Event) -> None:
        """Mouse left the window: restart the close timer"""
        self.mouse_inside = False
        if not self.streaming:
            self._start_destroy_timer()

    def _on_drag_start(self, event: tk.Event) -> None:
        """Drag started"""
        self.pause = True
        self.x = event.x
        self.y = event.y

    def _on_drag_stop(self, event: tk.Event) -> None:
        """Drag ended"""
        self.pause = False

    def _on_drag_motion(self, event: tk.Event) -> None:
        """Dragging: move the window"""
        deltax = event.x - self.x
        deltay = event.y - self.y
        x = self.window.winfo_x() + deltax
        y = self.window.winfo_y() + deltay
        self.window.geometry(f"+{x}+{y}")

    def _on_mouse_wheel(self, event: tk.Event) -> str:
        """Move the window up or down with the mouse wheel

        The window can scroll between the middle and the bottom of the screen:
        - If the bottom of the window is off screen, it can scroll up (smaller y)
        - If the top of the window is above the middle of the screen, it can scroll down (larger y)

        Returns:
            "break" to stop the event propagating
        """
        try:
            self.window.update_idletasks()
            current_y = self.window.winfo_y()
            window_height = self.window.winfo_height()
            screen_height = self.window.winfo_screenheight()
            screen_middle = screen_height // 2

            # Work out the scroll direction
            delta = getattr(event, 'delta', 0)
            num = getattr(event, 'num', 0)

            if delta:
                is_scroll_up = (delta < 0)
            elif num:
                is_scroll_up = (num != 4)
            else:
                return "break"

            # Limits
            # top_limit: y when the window is lowest (bottom at the screen's bottom edge)
            # bottom_limit: y when the window is highest (top at the middle of the screen)
            top_limit = screen_height - window_height
            bottom_limit = screen_middle

            # Check whether scrolling is allowed
            window_bottom = current_y + window_height
            can_scroll_up = window_bottom > screen_height  # Bottom is off screen, can scroll up
            can_scroll_down = current_y < screen_middle    # Top is above the middle, can scroll down

            # Scroll based on direction and position
            if is_scroll_up and can_scroll_up:
                # Scroll up (smaller y)
                target_y = max(current_y - SCROLL_STEP, top_limit)
                if target_y != current_y:
                    self.window.geometry(f"+{self.window.winfo_x()}+{int(target_y)}")
            elif not is_scroll_up and can_scroll_down:
                # Scroll down (larger y)
                target_y = min(current_y + SCROLL_STEP, bottom_limit)
                if target_y != current_y:
                    self.window.geometry(f"+{self.window.winfo_x()}+{int(target_y)}")

            return "break"
        except tk.TclError as e:
            logger.warning(f"Could not handle the scroll event: {e}")
            return "break"

    def _on_copy(self, _event: tk.Event) -> str:
        """Copy text to the clipboard

        Copies the selected text if there is any, otherwise the whole content.

        Args:
            _event: Event object (unused)

        Returns:
            "break" to stop the event propagating
        """
        try:
            text_to_copy = None

            # If there is an md_label, check for selected text
            if hasattr(self, 'md_label') and self.md_label:
                try:
                    # Text widgets report the selection with tag_ranges("sel")
                    sel_ranges = self.md_label.tag_ranges("sel")
                    if sel_ranges:
                        # Text is selected: copy it
                        text_to_copy = self.md_label.get(sel_ranges[0], sel_ranges[1])
                        logger.info("Copied the selected text to the clipboard")
                except tk.TclError:
                    pass  # No selection, or another error

            # Nothing selected: copy everything
            if text_to_copy is None:
                text_to_copy = self.full_text
                logger.info("Copied the whole toast to the clipboard")

            self.window.clipboard_clear()
            self.window.clipboard_append(text_to_copy)
        except Exception as e:
            logger.error(f"Could not copy to the clipboard: {e}")
        return "break"

    # --------------------------------------------------------
    # Closing the window
    # --------------------------------------------------------

    def _start_destroy_timer(self) -> None:
        """Start the auto-close timer"""
        if self.timer_id:
            self.window.after_cancel(self.timer_id)
        self.timer_id = self.window.after(self.duration, self._destroy_window)

    def _destroy_window(self, event: Optional[tk.Event] = None) -> None:
        """Close the window

        Args:
            event: Event object (passed when Esc triggers it)
        """
        try:
            # Call the stop callback (used to stop LLM output)
            if self.stop_callback:
                try:
                    self.stop_callback()
                except Exception as e:
                    logger.warning(f"Stop callback failed: {e}")

            if self.pause:
                # The window is paused (being dragged): close it a little later
                if self.timer_id:
                    self.window.after_cancel(self.timer_id)
                self.timer_id = self.window.after(DESTROY_DELAY_MS, self._destroy_window)
            else:
                if self.timer_id:
                    self.window.after_cancel(self.timer_id)
                    self.timer_id = None
                self.window.destroy()
        except tk.TclError:
            # The window may already be gone
            pass

    # --------------------------------------------------------
    # Markdown rendering
    # --------------------------------------------------------

    def _calculate_height_coefficient(self, content_height: int) -> float:
        """Calculate the margin coefficient from the content height

        Uses an exponential decay curve: f(x) = 0.5 * e^(-0.003x) + 1.1
        Short content needs a larger margin coefficient to be shown in full.
        For tall content the coefficient approaches its limit of 1.1.

        Args:
            content_height: Content height (pixels)

        Returns:
            Margin coefficient in the range (1.1, 1.6]
            - x=50: f(50) ≈ 1.6
            - x=300: f(300) ≈ 1.3
            - x=1500: f(1500) ≈ 1.15
            - x→∞: f(x) → 1.1
        """
        import math

        if content_height <= 50:
            return 1.6

        # Exponential decay curve: f(x) = 0.5 * e^(-0.003x) + 1.1
        coefficient = 0.5 * math.exp(-0.003 * content_height) + 1.1

        # Keep the coefficient in a sensible range
        return max(coefficient, 1.1)

    def _switch_to_markdown(self) -> None:
        """Switch the content widget to rendered Markdown"""
        try:
            # Remember the current position
            cx, cy = self.window.winfo_x(), self.window.winfo_y()

            # Convert Markdown to HTML
            raw_html = markdown.markdown(
                self.full_text,
                extensions=['extra', 'nl2br']
            )

            # Wrap it in full HTML (no padding; the HTMLLabel widget handles that)
            full_html = f"""
            <div style="background-color:{self.bg}; color:{self.fg};
                        font-family:{self.font_family}; font-size:{self.font_size}px;">
                {raw_html}
            </div>
            """

            # Create the HTMLLabel first, on top of the existing widget
            self.md_label = HTMLLabel(
                self.window,
                html=full_html,
                wrap="word",
                background=self.bg,
                padx=DEFAULT_PADDING_X,
                pady=DEFAULT_PADDING_Y
            )
            self.md_label.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

            # Make it editable or not, based on the editable setting
            # In the DISABLED state text can still be selected but not edited
            # In the NORMAL state text can be selected and edited
            if self.editable:
                self.md_label.config(state=tk.NORMAL)

                # Make the cursor the inverse of the background color
                cursor_color = self._invert_color(self.bg)
                self.md_label.config(insertbackground=cursor_color, insertwidth=2)
            # Otherwise keep HTMLLabel's default DISABLED state

            # Selection highlight (the default one is invisible in the DISABLED state)
            select_bg = "#3399ff"
            select_fg = "white"
            self.md_label.config(selectbackground=select_bg, selectforeground=select_fg)

            # HTMLLabel styles text with tags, so set the selection style on every tag too
            for tag in self.md_label.tag_names():
                self.md_label.tag_config(tag, selectbackground=select_bg, selectforeground=select_fg)

            # The Markdown widget is showing now, so remove the old widget
            self._destroy_content_widget()

            # Update several times so the layout is fully calculated
            self.window.update()
            self.window.update_idletasks()

            # fit_height() gives the real content height
            # by resizing the label to fit all its content
            self.md_label.fit_height()
            self.window.update()
            self.window.update_idletasks()

            # Measure the height after fit_height()
            height_after = self.md_label.winfo_height()
            reqheight_after = self.md_label.winfo_reqheight()

            # Use the larger height (reqheight may be more accurate)
            content_height = max(height_after, reqheight_after)

            # Calculate the new window height and width
            # A dynamic coefficient makes sure all the content shows
            margin_coefficient = self._calculate_height_coefficient(content_height)
            final_h = max(int(content_height * margin_coefficient), MARKDOWN_MIN_HEIGHT)
            final_w = self._calculate_actual_width()

            self.window.geometry(f"{final_w}x{int(final_h)}+{cx}+{cy}")

            # Update the layout and measure again
            self.window.update()
            self.window.update_idletasks()

            logger.info(f"Markdown window: {final_w}x{final_h} (content: {content_height}px, coefficient: {margin_coefficient:.2f})")

        except Exception as e:
            logger.error(f"Markdown rendering failed: {e}")
            self._destroy_window()

    # --------------------------------------------------------
    # Abstract methods (subclasses must implement them)
    # --------------------------------------------------------

    @abstractmethod
    def update_text(self, new_text: str) -> None:
        """Update the text (implemented by subclasses)

        Args:
            new_text: The new full text
        """
        pass

    @abstractmethod
    def _destroy_content_widget(self) -> None:
        """Destroy the content widget (implemented by subclasses)"""
        pass

    # --------------------------------------------------------
    # Finishing streamed output
    # --------------------------------------------------------

    def finish(self) -> None:
        """Finish streamed output

        Marks the stream as done, renders Markdown if it is on,
        then starts the auto-close timer.
        """
        if self.streaming:
            self.streaming = False

            # Render Markdown if it is on
            if self.markdown:
                self._switch_to_markdown()

            # Only start the timer if the mouse is not over the window
            if not self.mouse_inside:
                self._start_destroy_timer()
