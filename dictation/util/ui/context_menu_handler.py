
# coding: utf-8
"""
Context menu handler module

Handles the tray menu's "Edit context" item.
"""

import queue
import threading
import tkinter as tk
from typing import Optional

from config_client import ClientConfig as Config
from util.client.state import console
from . import logger



# Global dialog manager
_dialog_manager: Optional['_ContextDialogManager'] = None
_manager_lock = threading.Lock()


def get_dialog_manager() -> Optional['_ContextDialogManager']:
    """Get the dialog manager singleton"""
    global _dialog_manager
    with _manager_lock:
        if _dialog_manager is None:
            _dialog_manager = _ContextDialogManager()
        return _dialog_manager


def on_edit_context():
    """
    Handle a click on the "Edit context" menu item
    """
    try:
        # Get the dialog manager and show the dialog
        manager = get_dialog_manager()

        # Pass the current context setting as the default
        result = manager.show_dialog(default_text=Config.context)

        if not result or not result.confirmed:
            logger.info("User cancelled editing the context")
            return

        context_text = result.data.get('context', '').strip()

        # Update the setting
        Config.context = context_text

        # Show a success message
        console.print(f'[green]✓[/] Context updated: {context_text}')
        if context_text:
             logger.info(f"User updated the context: {context_text}")
        else:
             logger.info("User cleared the context")

    except Exception as e:
        logger.error(f"Error handling 'Edit context': {e}", exc_info=True)
        console.print(f'[red]Could not edit the context: {e}[/]')


class _ContextDialogManager:
    """
    Context dialog manager
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
            name="ContextDialogThread"
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
            raise RuntimeError("Timed out starting the context dialog Tkinter thread")

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
                    req_data = self.request_queue.get_nowait()
                    self._show_dialog_impl(req_data)
                except queue.Empty:
                    break
        except Exception as e:
            logger.error(f"Error processing a context dialog request: {e}", exc_info=True)

        if self.root:
            self.root.after(100, self._process_requests)

    def _show_dialog_impl(self, default_text):
        """Actually show the dialog"""
        try:
            from util.ui.context_dialog import show_context_dialog

            result = show_context_dialog(
                default_text=default_text,
                parent=self.root,
                title="Edit context"
            )
            self.result_queue.put(result)

        except Exception as e:
            logger.error(f"Error showing the context dialog: {e}", exc_info=True)
            self.result_queue.put(None)

    def show_dialog(self, default_text: str = "") -> Optional[object]:
        """Show the dialog"""
        self.request_queue.put(default_text)

        try:
            result = self.result_queue.get(timeout=300)
            return result
        except queue.Empty:
            logger.error("Context dialog timed out")
            return None
