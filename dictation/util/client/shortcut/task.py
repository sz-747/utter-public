# coding: utf-8
"""
Shortcut task.

Tracks the recording state of a single shortcut.
"""

import asyncio
import time
from threading import Event
from typing import TYPE_CHECKING, Optional

from . import logger
from util.tools.my_status import Status

if TYPE_CHECKING:
    from util.client.shortcut.shortcut_config import Shortcut
    from util.client.state import ClientState
    from util.client.audio.recorder import AudioRecorder



class ShortcutTask:
    """
    Recording task for one shortcut.

    Each shortcut tracks its own recording state so they do not interfere.
    """

    def __init__(self, shortcut: 'Shortcut', state: 'ClientState', recorder_class=None):
        """
        Set up the shortcut task.

        Args:
            shortcut: shortcut configuration
            state: client state instance
            recorder_class: AudioRecorder class (optional, for lazy import)
        """
        self.shortcut = shortcut
        self.state = state
        self._recorder_class = recorder_class

        # Task state
        self.task: Optional[asyncio.Future] = None
        self.recording_start_time: float = 0.0
        self.is_recording: bool = False

        # hold_mode state
        self.pressed: bool = False
        self.released: bool = True
        self.event: Event = Event()

        # Thread pool (for the countdown)
        self.pool = None

        # Console recording animation
        self._status = Status('Recording', spinner='point')

    def _get_recorder(self) -> 'AudioRecorder':
        """Create an AudioRecorder."""
        if self._recorder_class is None:
            from util.client.audio.recorder import AudioRecorder
            self._recorder_class = AudioRecorder
        return self._recorder_class(self.state)

    def launch(self) -> None:
        """Start recording."""
        logger.info(f"[{self.shortcut.key}] Pressed: recording started")

        # Record the start time
        self.recording_start_time = time.time()
        self.is_recording = True

        # Keep a separate copy of all mic audio during this press (to diagnose lost audio)
        try:
            from util.client.audio import capture_log
            manager = getattr(self.state, 'stream_manager', None)
            device = getattr(manager, 'selected_device', None) if manager else None
            capture_log.begin(self.recording_start_time, device)
        except Exception as e:
            logger.debug(f"Could not start the capture log: {e}")

        # Queue the begin marker
        asyncio.run_coroutine_threadsafe(
            self.state.queue_in.put({'type': 'begin', 'time': self.recording_start_time, 'data': None}),
            self.state.loop
        )

        # Update the recording state
        self.state.start_recording(self.recording_start_time)
        try:
            from util.client.ui import show_recording_status
            show_recording_status(self.recording_start_time)
        except Exception as e:
            logger.debug(f"Could not show the recording status bar: {e}")
        # The sound cue and muting only apply once the press passes the threshold (not a normal key press)
        self._notify('started', getattr(self, 'threshold', 0.3))

        # Console animation: recording
        self._status.start()

        # Start the recognition task
        recorder = self._get_recorder()
        self.task = asyncio.run_coroutine_threadsafe(
            recorder.record_and_send(),
            self.state.loop,
        )

    def cancel(self) -> None:
        """Cancel recording (press was too short)."""
        logger.debug(f"[{self.shortcut.key}] Recording cancelled (press too short)")

        self.is_recording = False
        self.state.stop_recording()
        try:
            from util.client.ui import hide_recording_status
            hide_recording_status()
        except Exception as e:
            logger.debug(f"Could not hide the recording status bar: {e}")
        self._status.stop()
        self._notify('cancelled')
        try:
            from util.client.audio import capture_log
            capture_log.end(cancelled=True)
        except Exception as e:
            logger.debug(f"Could not cancel the capture log: {e}")

        self.task.cancel()
        self.task = None

    def finish(self) -> None:
        """Finish recording."""
        logger.info(f"[{self.shortcut.key}] Released: recording finished")

        self.is_recording = False
        self.state.stop_recording()
        try:
            # Don't hide: switch straight to "processing" until text is typed, so there is no gap that looks like a failure
            from util.client.ui import show_thinking_status
            show_thinking_status()
        except Exception as e:
            logger.debug(f"Could not switch the status bar to processing: {e}")
        self._status.stop()
        self._notify('stopped')
        try:
            from util.client.audio import capture_log
            capture_log.end()
        except Exception as e:
            logger.debug(f"Could not finish the capture log: {e}")

        asyncio.run_coroutine_threadsafe(
            self.state.queue_in.put({
                'type': 'finish',
                'time': time.time(),
                'data': None
            }),
            self.state.loop
        )

        # Restore the key (toggle key in non-suppress mode).
        # In suppress mode the key never reaches the system, so its state did not change.
        if self.shortcut.is_toggle_key() and not self.shortcut.suppress:
            self._restore_key()

    def _notify(self, event: str, threshold: float = 0.0) -> None:
        """Notify the sound cue/mute thread and the desktop app status (both non-blocking)."""
        try:
            from util.client.audio.feedback import get_feedback
            feedback = get_feedback()
            if event == 'started':
                feedback.started(self.recording_start_time, threshold)
            elif event == 'stopped':
                feedback.stopped()
            else:
                feedback.cancelled()
            from util.client.runtime_status import get_runtime_status
            get_runtime_status().touch()
        except Exception as e:
            logger.debug(f"Recording feedback notification failed: {e}")

    def _restore_key(self) -> None:
        """Restore the key state (ShortcutManager handles self-capture)."""
        # Ask the manager to restore the key.
        # To avoid capturing it ourselves, the manager sets a flag before sending the key.
        manager = self._manager_ref()
        if manager:
            logger.debug(f"[{self.shortcut.key}] Restoring key state (suppress={self.shortcut.suppress})")
            manager.schedule_restore(self.shortcut.key)
        else:
            logger.warning(f"[{self.shortcut.key}] Lost the manager reference, cannot restore the key")
