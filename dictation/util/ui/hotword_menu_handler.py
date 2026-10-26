# coding: utf-8
"""
Dictionary words menu handler module

Handles the tray menu's "Add dictionary words" item.
"""

import queue
import threading
import tkinter as tk
from pathlib import Path
from typing import Optional

from util.client.state import get_state, console
from . import logger



# Global dialog manager
_dialog_manager: Optional['_HotwordDialogManager'] = None
_manager_lock = threading.Lock()


def get_dialog_manager() -> Optional['_HotwordDialogManager']:
    """Get the dialog manager singleton"""
    global _dialog_manager
    with _manager_lock:
        if _dialog_manager is None:
            _dialog_manager = _HotwordDialogManager()
        return _dialog_manager


def on_add_hotword():
    """
    Handle a click on the "Add dictionary words" menu item
    """
    try:
        # Get the dialog manager and show the dialog
        manager = get_dialog_manager()
        result = manager.show_dialog()

        if not result:
            logger.info("User cancelled adding dictionary words")
            return

        hotword_text = result.get('hotword', '').strip()

        if not hotword_text:
            logger.warning("User submitted no dictionary words")
            return

        # Save to hot.txt
        _save_hotwords(hotword_text)

        # Show a success message
        console.print(f'[green]✓[/] Dictionary words added: {hotword_text}')

    except Exception as e:
        logger.error(f"Error handling 'Add dictionary words': {e}", exc_info=True)
        console.print(f'[red]Could not add dictionary words: {e}[/]')


def _save_hotwords(text: str) -> None:
    """
    Save dictionary words to hot.txt

    Args:
        text: The words (one per line)
    """
    hot_file = Path('hot.txt')

    # Make sure the file exists
    if not hot_file.exists():
        hot_file.touch()

    # Read the current content and check whether it ends with a newline
    content = hot_file.read_text(encoding='utf-8')
    needs_newline = content and not content.endswith('\n')

    # Append to the file
    with open(hot_file, 'a', encoding='utf-8') as f:
        if needs_newline:
            f.write('\n')

        # Write each line
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        for line in lines:
            f.write(f"{line}\n")

    logger.debug(f"Appended {len(lines)} dictionary words to {hot_file}")


class _HotwordDialogManager:
    """
    Dictionary words dialog manager
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
            name="HotwordDialogThread"
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
            raise RuntimeError("Timed out starting the dictionary words dialog Tkinter thread")

    def _run_tkinter(self):
        """Run the Tkinter main loop in its own thread"""
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
        """Process dialog requests in the queue"""
        if not self.is_running:
            return

        try:
            while not self.request_queue.empty():
                try:
                    self.request_queue.get_nowait()
                    self._show_dialog_impl()
                except queue.Empty:
                    break
        except Exception as e:
            logger.error(f"Error processing a dictionary words dialog request: {e}", exc_info=True)

        if self.root:
            self.root.after(100, self._process_requests)

    def _show_dialog_impl(self):
        """Actually show the dialog"""
        try:
            from util.ui.hotword_dialog import show_hotword_dialog

            result = show_hotword_dialog(
                parent=self.root,
                title="Add dictionary words"
            )
            self.result_queue.put(result)

        except Exception as e:
            logger.error(f"Error showing the dictionary words dialog: {e}", exc_info=True)
            self.result_queue.put(None)

    def show_dialog(self) -> Optional[tuple]:
        """Show the dialog"""
        self.request_queue.put(True)

        try:
            result = self.result_queue.get(timeout=300)
            return result
        except queue.Empty:
            logger.error("Dictionary words dialog timed out")
            return None
