# coding: utf-8
"""
Audio recording

AudioRecorder manages one recording session: it starts the recording,
sends the audio to the speech server and finishes the recording.
"""

from __future__ import annotations

import base64
import json
import uuid
from typing import TYPE_CHECKING, Optional

import numpy as np
import websockets

from config_client import ClientConfig as Config
from util.client.state import console
from util.client.audio.file_manager import AudioFileManager
from . import logger

if TYPE_CHECKING:
    from util.client.state import ClientState


def asr_context(user_context: str) -> str:
    """The context sent with each recording: the person's own context text, then the language hint."""
    hint = 'The speaker speaks English.'
    return f'{user_context.strip()}\n{hint}' if user_context and user_context.strip() else hint


class AudioRecorder:
    """
    Audio recorder

    Manages one complete recording session:
    - receives data from the audio stream
    - optionally saves it to a local file
    - sends the audio to the speech server
    """

    def __init__(self, state: 'ClientState'):
        """
        Args:
            state: the client state
        """
        self.state = state
        self.task_id: Optional[str] = None
        self._file_manager: Optional[AudioFileManager] = None
        self._start_time: float = 0.0
        self._duration: float = 0.0
        self._cache: list = []

    async def _send_message(self, message: dict) -> None:
        """Send a message to the speech server."""
        websocket = self.state.websocket

        if websocket is None:
            if message['is_final']:
                self.state.pop_audio_file(message['task_id'])
                console.print('    Speech server not connected; nothing sent\n')
                logger.warning("Speech server not connected; audio not sent")
            return

        try:
            if hasattr(websocket, 'closed') and websocket.closed:
                if message['is_final']:
                    self.state.pop_audio_file(message['task_id'])
                    console.print('    Speech server connection closed\n')
                    logger.error("Speech server connection closed")
                return

            await websocket.send(json.dumps(message))

        except websockets.ConnectionClosedError:
            if message['is_final']:
                self.state.pop_audio_file(message['task_id'])
                console.print('[red]Connection lost')
                logger.error("WebSocket connection lost")
        except websockets.ConnectionClosedOK:
            if message['is_final']:
                self.state.pop_audio_file(message['task_id'])
                console.print('[yellow]Connection closed')
                logger.info("WebSocket connection closed normally")
        except Exception as e:
            logger.error(f"Error sending audio: {e}", exc_info=True)

    async def record_and_send(self) -> None:
        """
        Record and send

        Reads audio from the queue, saves it to a file (if enabled)
        and sends it to the speech server for recognition.
        """
        try:
            # Unique task ID
            self.task_id = str(uuid.uuid1())
            logger.debug(f"Recording task created, task ID: {self.task_id}")

            self._start_time = 0.0
            self._duration = 0.0
            self._cache = []
            sent_audio = False

            # Audio file
            file_path = None
            if Config.save_audio:
                self._file_manager = AudioFileManager()

            # Read from the queue
            while task := await self.state.queue_in.get():
                self.state.queue_in.task_done()

                if task['type'] == 'begin':
                    self._start_time = task['time']
                    logger.debug(f"Recording started, timestamp: {self._start_time}")

                elif task['type'] == 'data':
                    # Hold audio until the shortcut threshold has passed
                    if task['time'] - self._start_time < Config.threshold:
                        self._cache.append(task['data'])
                        continue

                    # Create the audio file
                    if Config.save_audio and self._file_manager and file_path is None:
                        file_path, _ = self._file_manager.create(
                            task['data'].shape[1],
                            self._start_time
                        )
                        self.state.register_audio_file(self.task_id, file_path)
                        logger.debug(f"Audio file created: {file_path}")

                    # Audio data
                    if self._cache:
                        data = np.concatenate(self._cache)
                        self._cache.clear()
                    else:
                        data = task['data']

                    # Save to the local file
                    self._duration += len(data) / 48000
                    if Config.save_audio and self._file_manager:
                        self._file_manager.write(data)

                    # Send for recognition
                    message = {
                        'task_id': self.task_id,
                        'seg_duration': Config.mic_seg_duration,
                        'seg_overlap': Config.mic_seg_overlap,
                        'is_final': False,
                        'time_start': self._start_time,
                        'time_frame': task['time'],
                        'source': 'mic',
                        'data': base64.b64encode(
                            np.mean(data[::3], axis=1).tobytes()
                        ).decode('utf-8'),
                        'context': asr_context(Config.context),
                    }
                    await self._send_message(message)
                    sent_audio = True

                elif task['type'] == 'finish':
                    # Send any audio still held back
                    if self._cache:
                        data = np.concatenate(self._cache)
                        self._cache.clear()

                        self._duration += len(data) / 48000
                        if Config.save_audio and self._file_manager:
                            self._file_manager.write(data)

                        message = {
                            'task_id': self.task_id,
                            'seg_duration': Config.mic_seg_duration,
                            'seg_overlap': Config.mic_seg_overlap,
                            'is_final': False,
                            'time_start': self._start_time,
                            'time_frame': task['time'],
                            'source': 'mic',
                            'data': base64.b64encode(
                                np.mean(data[::3], axis=1).tobytes()
                            ).decode('utf-8'),
                            'context': asr_context(Config.context),
                        }
                        await self._send_message(message)
                        sent_audio = True

                    # Finish the local file
                    if Config.save_audio and self._file_manager:
                        self._file_manager.finish()
                        logger.debug("Audio file written")

                    console.print(f'Task: {self.task_id}')
                    console.print(f'    Recording length: {self._duration:.2f}s')
                    logger.info(f"Recording task finished, task ID: {self.task_id}, length: {self._duration:.2f}s")
                    try:
                        from util.client.audio import capture_log
                        capture_log.recorder_finished(self._duration)   # compare with the separate capture to find where audio was lost
                    except Exception as e:
                        logger.debug(f"Capture comparison failed: {e}")

                    # Tell the server the recording is over
                    if not sent_audio:
                        logger.warning(f"Skipping empty recording task, task_id={self.task_id}")
                        # No result will come back, so hide the "processing" pill now
                        try:
                            from util.client.ui import hide_recording_status
                            hide_recording_status()
                        except Exception as e:
                            logger.debug(f"Hiding the status pill failed: {e}")
                        break

                    message = {
                        'task_id': self.task_id,
                        'seg_duration': 15,
                        'seg_overlap': 2,
                        'is_final': True,
                        'time_start': self._start_time,
                        'time_frame': task['time'],
                        'source': 'mic',
                        'data': '',
                        'context': asr_context(Config.context),
                    }
                    await self._send_message(message)
                    break

        except Exception as e:
            logger.error(f"Recording task error: {e}", exc_info=True)

    def get_file_manager(self) -> Optional[AudioFileManager]:
        """The current file manager."""
        return self._file_manager
