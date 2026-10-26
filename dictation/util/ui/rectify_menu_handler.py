# coding: utf-8
"""
Corrections menu handler module

Handles the tray menu's "Add a correction" item.
"""

import queue
import threading
import tkinter as tk
from pathlib import Path
from typing import Optional

from util.client.state import get_state
from util.client.state import console
from . import logger



# Global dialog manager
_dialog_manager: Optional['_RectifyDialogManager'] = None
_manager_lock = threading.Lock()


def get_dialog_manager() -> Optional['_RectifyDialogManager']:
    """Get the dialog manager singleton"""
    global _dialog_manager
    with _manager_lock:
        if _dialog_manager is None:
            _dialog_manager = _RectifyDialogManager()
        return _dialog_manager


def on_add_rectify_record():
    """
    Handle a click on the "Add a correction" menu item

    The dialog runs in its own Tkinter thread to avoid threading problems.

    Steps:
    1. Get the last recognition result from ClientState
    2. Queue a request with the dialog manager
    3. Wait for the user to finish
    4. Save to hot-rectify.txt, which triggers a reload
    """
    try:
        # 1. Get the last recognition result from the global state
        state = get_state()
        recognition_text = state.last_recognition_text or ""  # Use an empty string if None

        logger.info(f"User clicked 'Add a correction', recognition result: '{recognition_text[:30]}...'")

        # 2. Get the dialog manager and show the dialog
        manager = get_dialog_manager()
        result = manager.show_dialog(recognition_text)

        if not result:
            logger.info("User cancelled adding a correction")
            return

        original, corrected = result

        if not original or not corrected:
            logger.warning("User submitted an empty correction")
            return

        logger.info(f"User submitted a correction: original='{original}', corrected='{corrected}'")

        # 3. Save to hot-rectify.txt
        _save_rectify_record(original, corrected)

        # 4. Show a short success message (the file watcher shows the details)
        console.print('[green]✓[/] Correction added')

    except Exception as e:
        logger.error(f"Error handling 'Add a correction': {e}", exc_info=True)
        console.print(f'[red]Could not add the correction: {e}[/]')


def _save_rectify_record(original: str, corrected: str) -> None:
    """
    Save a correction to hot-rectify.txt

    Args:
        original: Original text (the wrong text that was recognized)
        corrected: Corrected text (the right text)
    """
    rectify_file = Path('hot-rectify.txt')

    # Append to the file
    with open(rectify_file, 'a', encoding='utf-8') as f:
        f.write(f"\n{original}\n{corrected}\n---\n")

    logger.debug(f"Appended a correction to {rectify_file}")


class _RectifyDialogManager:
    """
    Corrections dialog manager

    Runs the Tkinter main loop in its own thread and handles dialog requests through a queue.
    """

    def __init__(self):
        self.request_queue: queue.Queue = queue.Queue()
        self.result_queue: queue.Queue = queue.Queue()
        self.root: Optional[tk.Tk] = None
        self.is_running = False

        # Start Tkinter in its own thread
        self.tk_thread = threading.Thread(
            target=self._run_tkinter,
            daemon=True,
            name="RectifyDialogThread"
        )
        self.tk_thread.start()

        # Wait for Tkinter to finish starting
        self._wait_for_ready()

    def _wait_for_ready(self, timeout=5.0):
        """Wait for the Tkinter thread to be ready"""
        import time
        start = time.time()
        while not self.is_running and (time.time() - start) < timeout:
            time.sleep(0.05)

        if not self.is_running:
            raise RuntimeError("Timed out starting the Tkinter thread")

    def _run_tkinter(self):
        """Run the Tkinter main loop in its own thread"""
        # Create a hidden root window
        self.root = tk.Tk()
        self.root.withdraw()

        # What happens when the window closes
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Mark as running
        self.is_running = True

        # Start processing the request queue
        self._process_requests()

        # Start the Tkinter main loop
        self.root.mainloop()

    def _on_close(self):
        """Close the window and quit"""
        self.is_running = False
        if self.root:
            self.root.quit()

    def _process_requests(self):
        """Process dialog requests in the queue (polled with after)"""
        if not self.is_running:
            return

        try:
            # Check the queue without blocking
            while not self.request_queue.empty():
                try:
                    recognition_text = self.request_queue.get_nowait()
                    self._show_dialog_impl(recognition_text)
                except queue.Empty:
                    break
        except Exception as e:
            logger.error(f"Error processing a dialog request: {e}", exc_info=True)

        # Keep polling (100 ms)
        if self.root:
            self.root.after(100, self._process_requests)

    def _show_dialog_impl(self, recognition_text: str):
        """Actually show the dialog (called in the Tkinter thread)"""
        try:
            from util.ui.rectify_dialog import show_rectify_dialog

            result = show_rectify_dialog(
                recognition_text=recognition_text,
                parent=self.root,
                title="Add a correction"
            )

            # Put the result in the result queue
            if result and result.confirmed:
                original = result.get('original', '').strip()
                corrected = result.get('corrected', '').strip()
                self.result_queue.put((original, corrected))
            else:
                self.result_queue.put(None)

        except Exception as e:
            logger.error(f"Error showing the dialog: {e}", exc_info=True)
            self.result_queue.put(None)

    def show_dialog(self, recognition_text: str) -> Optional[tuple]:
        """
        Show the dialog (can be called from any thread)

        Args:
            recognition_text: Recognized text

        Returns:
            An (original, corrected) tuple, or None if the user cancelled
        """
        # Queue the request
        self.request_queue.put(recognition_text)

        # Wait for the result
        try:
            result = self.result_queue.get(timeout=300)  # 5 minute timeout
            return result
        except queue.Empty:
            logger.error("Dialog timed out")
            return None


if __name__ == "__main__":
    # Test code
    from util.client.state import get_state

    # Simulate a recognition result
    state = get_state()
    state.last_recognition_text = "Meet me at the tree o'clock"

    # Test the menu handler
    print("Testing the menu handler...")
    on_add_rectify_record()
