# coding: utf-8
"""
Event handler.

Logic for keyboard and mouse events.
"""

import time
from . import logger



class ShortcutEventHandler:
    """
    Shortcut event handler.

    Handles key presses and releases: starting, cancelling and finishing recordings.
    """

    def __init__(self, tasks, pool, emulator):
        """
        Set up the event handler.

        Args:
            tasks: dict of shortcut tasks
            pool: thread pool
            emulator: shortcut emulator
        """
        self.tasks = tasks
        self.pool = pool
        self.emulator = emulator

    def handle_keydown(self, key_name, task) -> None:
        """Handle a key press."""
        # Hold mode
        if task.shortcut.hold_mode:
            if not task.is_recording:
                task.launch()
            return

        # Click mode
        if task.released:
            from threading import Event
            task.pressed = True
            task.released = False
            task.event = Event()  # new event object
            self.pool.submit(self._count_down, task)
            self.pool.submit(self._manage_task, task)

    def handle_keyup(self, key_name, task) -> None:
        """Handle a key release."""
        # Click mode
        if not task.shortcut.hold_mode:
            if task.pressed:
                task.pressed = False
                task.released = True
                task.event.set()
            return

        # Hold mode
        if not task.is_recording:
            return

        duration = time.time() - task.recording_start_time
        logger.debug(f"[{key_name}] Released after {duration:.2f}s")

        if duration < task.threshold:
            self._handle_short_press(key_name, task)
        else:
            task.finish()

    def _handle_short_press(self, key_name, task) -> None:
        """Handle a short press."""
        cancel_start = time.perf_counter()
        task.cancel()
        cancel_time = (time.perf_counter() - cancel_start) * 1000
        logger.debug(f"[{key_name}] task.cancel() took {cancel_time:.2f}ms")

        if task.shortcut.suppress:
            logger.debug(f"[{key_name}] Scheduling a replay of the key")
            self.pool.submit(self.emulator.emulate_key, key_name)

    def _count_down(self, task) -> None:
        """Countdown (click mode)."""
        time.sleep(task.threshold)
        task.event.set()

    def _manage_task(self, task) -> None:
        """Manage the recording task (click mode)."""
        was_recording = task.is_recording

        if not was_recording:
            task.launch()

        if task.event.wait(timeout=task.threshold * 0.8):
            if task.is_recording and was_recording:
                task.finish()
        else:
            if not was_recording:
                task.cancel()
