# coding: utf-8
"""
Client state

Provides the ClientState class, which holds the client's global state.
A dataclass keeps the state definition typed and clear.
"""

from __future__ import annotations

import asyncio
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Dict, Any

if TYPE_CHECKING:
    import sounddevice as sd
    from websockets.legacy.client import WebSocketClientProtocol

from rich.console import Console
from rich.theme import Theme

from . import logger


# Rich console setup
_theme = Theme({
    'markdown.code': 'cyan',
    'markdown.item.number': 'yellow'
})
console = Console(highlight=False, soft_wrap=True, theme=_theme)


@dataclass
class ClientState:
    """
    Client runtime state

    Holds all state shared while the client runs, including the event loop,
    message queues, WebSocket connection, audio stream and recording state.

    Attributes:
        loop: asyncio event loop
        queue_in: Audio data input queue
        queue_out: Result output queue (reserved)
        websocket: WebSocket client connection
        stream: Audio input stream
        recording: Whether recording is in progress
        recording_start_time: Recording start timestamp
        audio_files: Map of task ID to audio file path
        last_recognition_text: Final text of the latest recognition (after hotword replacement), used by "Add correction"
    """

    loop: Optional[asyncio.AbstractEventLoop] = None
    queue_in: Optional[asyncio.Queue] = None
    queue_out: Optional[asyncio.Queue] = None
    websocket: Optional['WebSocketClientProtocol'] = None
    stream: Optional['sd.InputStream'] = None

    # Component references (for cleanup)
    shortcut_handler: Any = None
    stream_manager: Any = None
    processor: Any = None
    mouse_handler: Any = None
    udp_controller: Any = None

    recording: bool = False
    recording_start_time: float = 0.0
    audio_files: Dict[str, Path] = field(default_factory=dict)

    # Latest recognition result (for adding corrections by hand)
    last_recognition_text: Optional[str] = None

    # Latest output (the polished text if the LLM polished it, otherwise the raw recognition)
    last_output_text: Optional[str] = None
    last_output_time: Optional[float] = None

    def initialize(self) -> None:
        """
        Initialize the state

        Creates the event loop and message queues, ready to receive audio.
        """
        self.loop = asyncio.get_event_loop()
        self.queue_in = asyncio.Queue()
        self.queue_out = asyncio.Queue()
        logger.debug("Client state initialized")

    def reset(self) -> None:
        """
        Reset the state

        Clears all state and closes connections and streams. Used when
        reinitializing or exiting.
        """
        logger.debug("Resetting client state...")

        # Close the WebSocket connection
        if self.websocket is not None:
            try:
                if not self.websocket.closed:
                    logger.debug("WebSocket connection will be closed")
            except Exception:
                pass
            self.websocket = None

        # Close the audio stream
        if self.stream is not None:
            try:
                self.stream.close()
                logger.debug("Audio stream closed")
            except Exception:
                pass
            self.stream = None

        # Reset the rest
        self.recording = False
        self.recording_start_time = 0.0
        self.audio_files.clear()

        logger.debug("Client state reset")

    def start_recording(self, start_time: float) -> None:
        """
        Start recording

        Args:
            start_time: Recording start timestamp
        """
        self.recording = True
        self.recording_start_time = start_time
        logger.debug(f"Recording state updated: recording=True, start_time={start_time:.2f}")

    def stop_recording(self) -> float:
        """
        Stop recording

        Returns:
            Recording duration in seconds
        """
        duration = 0.0
        if self.recording_start_time > 0:
            duration = time.time() - self.recording_start_time

        self.recording = False
        self.recording_start_time = 0.0
        logger.debug(f"Recording state updated: recording=False, duration={duration:.2f}s")
        return duration

    @property
    def is_connected(self) -> bool:
        """Whether the WebSocket is connected"""
        if self.websocket is None:
            return False
        try:
            return not self.websocket.closed
        except AttributeError:
            return self.websocket is not None

    def register_audio_file(self, task_id: str, file_path: Path) -> None:
        """
        Register an audio file

        Args:
            task_id: Task ID
            file_path: Audio file path
        """
        self.audio_files[task_id] = file_path
        logger.debug(f"Registered audio file: task_id={task_id}, path={file_path}")

    def pop_audio_file(self, task_id: str) -> Optional[Path]:
        """
        Get and remove an audio file path

        Args:
            task_id: Task ID

        Returns:
            The audio file path, or None if there is none
        """
        file_path = self.audio_files.pop(task_id, None)
        if file_path:
            logger.debug(f"Got audio file: task_id={task_id}, path={file_path}")
        return file_path

    def set_output_text(self, text: str) -> None:
        """
        Store the latest output text and broadcast it over UDP (if enabled)

        Args:
            text: Output text
        """
        from config_client import ClientConfig as Config

        # Update the state
        self.last_output_text = text
        self.last_output_time = time.time()

        # Broadcast over UDP to the configured targets (if enabled)
        if Config.udp_broadcast and Config.udp_broadcast_targets:
            message = text.encode('utf-8')
            for addr, port in Config.udp_broadcast_targets:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                        sock.sendto(message, (addr, port))
                        logger.debug(f"Sent output text over UDP to {addr}:{port}, length: {len(text)}")
                except Exception as e:
                    logger.warning(f"Failed to send output text over UDP to {addr}:{port}: {e}")


# Global state instance
_global_state: Optional[ClientState] = None


def get_state() -> ClientState:
    """
    Get the global client state instance

    Creates it if it does not exist yet.

    Returns:
        The ClientState instance
    """
    global _global_state
    if _global_state is None:
        _global_state = ClientState()
        logger.debug("Created the global ClientState instance")
    return _global_state
