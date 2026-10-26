"""
Toast message manager module

Provides the ToastMessageManager singleton, which manages the lifetime of every toast window.
"""
import logging
import threading
import tkinter as tk
from queue import Queue
from dataclasses import dataclass
from typing import Literal, Optional, Callable, Union, List, TYPE_CHECKING
import sys
import os

# When run directly, add the project root to sys.path
if __name__ == "__main__":
    file_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(os.path.dirname(file_dir))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
    from util.ui.toast_text import ToastWindowText
    from util.ui.toast_label import ToastWindowLabel
    from util.ui.toast_constants import (
        QUEUE_POLL_INTERVAL_MS,
        DEFAULT_DURATION_MS,
        DEFAULT_INITIAL_WIDTH,
        TK_SCALING_FACTOR,
    )
    from util.ui.toast_logger import get_toast_logger
else:
    from .toast_text import ToastWindowText
    from .toast_label import ToastWindowLabel
    from .toast_constants import (
        QUEUE_POLL_INTERVAL_MS,
        DEFAULT_DURATION_MS,
        DEFAULT_INITIAL_WIDTH,
        TK_SCALING_FACTOR,
    )
    from .toast_logger import get_toast_logger

# Forward reference for type hints
if TYPE_CHECKING:
    from .toast_base import ToastWindowBase


# Logging (uses the main program's logger if it has one)
logger = get_toast_logger(__name__)


# ============================================================
# Data classes
# ============================================================

@dataclass
class ToastMessage:
    """Toast message settings

    Attributes:
        text: Message text
        font_size: Font size (pixels)
        font_family: Font name; an empty string uses the default
        bg: Background color (hex or color name)
        fg: Foreground (text) color
        duration: How long to show it (milliseconds)
        initial_width: Initial width; 0-1 is a fraction of the screen, >1 is pixels
        initial_height: Initial height; 0 means calculate it automatically
        streaming: Whether the text streams in
        window_type: Window type ('text' or 'label')
        stop_callback: Called when the window closes
        markdown: Whether to render Markdown
    """
    text: str
    font_size: int = 14
    font_family: str = ''
    bg: str = '#075077'
    fg: str = 'white'
    duration: int = DEFAULT_DURATION_MS
    initial_width: Union[float, int] = DEFAULT_INITIAL_WIDTH
    initial_height: int = 0
    streaming: bool = False
    window_type: Literal['text', 'label'] = 'text'
    stop_callback: Optional[Callable[[], None]] = None
    markdown: bool = False
    editable: bool = False  # Whether the text can be edited after Markdown rendering


# ============================================================
# Toast message manager
# ============================================================

class ToastMessageManager:
    """Toast message manager (singleton)

    Runs the Tkinter main loop in its own thread and manages the lifetime of every toast window.

    Features:
        - Singleton, so there is only one Tkinter main loop
        - Message queue, so messages can be added from any thread
        - Tracks active windows so streamed output can update them
        - UUID message IDs for exact matching
    """

    _instance: Optional['ToastMessageManager'] = None
    _lock = threading.Lock()

    def __new__(cls) -> 'ToastMessageManager':
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self._initialized = True
        self.message_queue: 'Queue[ToastMessage]' = Queue()
        self.is_running = False
        self.active_windows: List = []  # Typed at runtime to avoid a circular import
        self.root: Optional[tk.Tk] = None

        # Start Tkinter in a worker thread
        self.manager_thread = threading.Thread(
            target=self._run_manager,
            daemon=True,
            name="ToastManagerThread"
        )
        self.manager_thread.start()

    def _run_manager(self) -> None:
        """Run the Tkinter main loop in the worker thread"""
        # Create a hidden root window
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.tk.call('tk', 'scaling', TK_SCALING_FACTOR)

        # What happens when the window closes
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Start processing the queue
        self.is_running = True
        self._process_queue()

        # Start the Tkinter main loop
        self.root.mainloop()

    def _on_close(self) -> None:
        """Close every window and quit"""
        self.is_running = False

        for window in self.active_windows[:]:
            try:
                window.window.destroy()
            except tk.TclError:
                pass

        self.active_windows.clear()

        if self.root:
            self.root.quit()

    def _process_queue(self) -> None:
        """Process messages in the queue"""
        try:
            if not self.message_queue.empty():
                msg = self.message_queue.get_nowait()
                msg_id = getattr(msg, '_id', 'unknown')

                # Pick the window class from window_type
                WindowClass = ToastWindowLabel if msg.window_type == 'label' else ToastWindowText

                toast_window = WindowClass(
                    self.root,
                    msg.text,
                    msg.font_size,
                    msg.font_family,
                    msg.bg,
                    msg.fg,
                    msg.duration,
                    msg.initial_width,
                    msg.initial_height,
                    streaming=msg.streaming,
                    stop_callback=msg.stop_callback,
                    markdown=msg.markdown,
                    editable=msg.editable
                )

                # Store the message ID on the window object
                toast_window._msg_id = msg_id
                self.active_windows.append(toast_window)

                # Callback for when the window is destroyed
                toast_window.window.bind(
                    '<Destroy>',
                    lambda _, w=toast_window: self._remove_window(w)
                )

            # Drop windows that have been destroyed
            self.active_windows = [
                w for w in self.active_windows
                if self._window_exists(w)
            ]

        except Exception as e:
            logger.warning(f"Error processing a queued message: {e}")

        # Keep processing the queue
        if self.is_running and self.root:
            self.root.after(QUEUE_POLL_INTERVAL_MS, self._process_queue)

    def _window_exists(self, window) -> bool:
        """Check whether a window still exists"""
        try:
            return window.window.winfo_exists()
        except tk.TclError:
            return False

    def _remove_window(self, window) -> None:
        """Remove a window from the active list"""
        if window in self.active_windows:
            self.active_windows.remove(window)

    def add_message(self, msg: ToastMessage) -> Optional[str]:
        """Add a ToastMessage to the queue

        Args:
            msg: Toast message settings

        Returns:
            Unique message ID (used later to update, finish or close it)
        """
        import uuid
        msg_id = str(uuid.uuid4())
        msg._id = msg_id  # Attach the unique ID
        self.message_queue.put(msg)
        return msg_id

    def update_toast(self, msg_id: str, new_text: str) -> None:
        """Update the text of the toast with this ID

        Args:
            msg_id: Unique message ID
            new_text: The new full text
        """
        for window in self.active_windows:
            if getattr(window, '_msg_id', None) == msg_id:
                window.update_text(new_text)
                return
        logger.warning(f"Message ID not found: {msg_id[:8]}")

    def finish_toast(self, msg_id: str) -> None:
        """Finish streamed output for the toast with this ID

        Args:
            msg_id: Unique message ID
        """
        for window in self.active_windows:
            if getattr(window, '_msg_id', None) == msg_id:
                if window.streaming:
                    window.finish()
                return
        logger.warning(f"Message ID not found: {msg_id[:8]}")

    def close_toast(self, msg_id: str) -> None:
        """Close the toast with this ID

        Args:
            msg_id: Unique message ID
        """
        for window in self.active_windows[:]:
            if getattr(window, '_msg_id', None) == msg_id:
                try:
                    window.window.destroy()
                    self.active_windows.remove(window)
                except (tk.TclError, ValueError):
                    pass
                return
        logger.warning(f"Message ID not found: {msg_id[:8]}")

    async def wait_for_window(self, msg_id: str, timeout: float = 1.0) -> Optional['ToastWindowBase']:
        """Wait asynchronously until the window with this ID has been created

        Args:
            msg_id: Unique message ID
            timeout: Timeout (seconds)

        Returns:
            The window object, or None on timeout
        """
        import asyncio
        start = asyncio.get_event_loop().time()
        while asyncio.get_event_loop().time() - start < timeout:
            for window in self.active_windows:
                if getattr(window, '_msg_id', None) == msg_id:
                    return window
            await asyncio.sleep(0.01)  # Poll every 10 ms
        logger.warning(f"Timed out waiting for window: {msg_id[:8]}")
        return None
