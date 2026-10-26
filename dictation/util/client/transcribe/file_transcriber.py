# coding: utf-8
"""
File transcription

FileTranscriber turns an audio or video file into subtitles.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
import websockets
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from config_client import ClientConfig as Config
from util.client.state import console
from util.client.websocket_manager import WebSocketManager
from util.client.audio.recorder import asr_context
from .media_tool import MediaTool
from .result_handler import ResultHandler
from . import logger

if TYPE_CHECKING:
    from util.client.state import ClientState


class FileTranscriber:
    """
    File transcriber

    Runs the transcription flow:
    1. Check the environment and the file
    2. Extract the audio with MediaTool
    3. Send the data over the WebSocket
    4. Hand the result to ResultHandler
    """

    def __init__(self, state: 'ClientState', file: Path):
        self.state = state
        self.file = file
        self._ws_manager = WebSocketManager(state)
        self.task_id: Optional[str] = None
        self._audio_duration: float = 0.0

    async def check(self) -> bool:
        """Check that transcription can run."""
        # 1. Check the media tool (FFmpeg)
        if not MediaTool.check_environment():
            return False

        # 2. Check the server connection
        if not await self._ws_manager.connect():
            console.print('Could not connect to the server')
            logger.error("Could not connect to the server")
            return False

        # 3. Check the file exists
        if not self.file.exists():
            console.print(f'File not found: {self.file}')
            logger.error(f"File not found: {self.file}")
            return False

        return True

    async def send(self) -> None:
        """Stream the audio data to the server."""
        websocket = self.state.websocket

        self.task_id = str(uuid.uuid1())
        console.print(f'\nTask ID: {self.task_id}')
        console.print(f'    File: {self.file}')

        # 1. Get the duration first
        self._audio_duration = await MediaTool.get_audio_duration(self.file)
        if self._audio_duration > 0:
            console.print(f'    Audio length: {self._audio_duration:.2f}s')

        logger.info(f"Transcribing file: {self.file}, task ID: {self.task_id}")

        # 2. Start FFmpeg
        ffmpeg_cmd = MediaTool.build_ffmpeg_cmd(self.file)

        try:
            process = await asyncio.create_subprocess_exec(
                *ffmpeg_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL
            )

            # Chunk size: one minute of audio (16000 * 4 * 60 bytes)
            chunk_size = 16000 * 4 * 60
            bytes_sent = 0

            while True:
                data = await process.stdout.read(chunk_size)
                if not data:
                    break

                bytes_sent += len(data)
                progress = bytes_sent / 4 / 16000
                if self._audio_duration > 0:
                    prog_str = f'    Sent: {progress:.2f}s / {self._audio_duration:.2f}s'
                else:
                    prog_str = f'    Sent: {progress:.2f}s'
                console.print(prog_str, end='\r')

                message = {
                    'task_id': self.task_id,
                    'seg_duration': Config.file_seg_duration,
                    'seg_overlap': Config.file_seg_overlap,
                    'is_final': False,
                    'time_start': time.time(),
                    'time_frame': time.time(),
                    'source': 'file',
                    'data': base64.b64encode(data).decode('utf-8'),
                    'context': asr_context(Config.context),
                }
                await websocket.send(json.dumps(message))

            # Send the end marker
            final_message = {
                'task_id': self.task_id,
                'seg_duration': Config.file_seg_duration,
                'seg_overlap': Config.file_seg_overlap,
                'is_final': True,
                'time_start': time.time(),
                'time_frame': time.time(),
                'source': 'file',
                'data': '',
                'context': asr_context(Config.context),
            }
            await websocket.send(json.dumps(final_message))
            await process.wait()

            if self._audio_duration == 0:
                self._audio_duration = progress
                console.print(f'    Audio length: {self._audio_duration:.2f}s')

            logger.debug("Finished sending audio data")

        except websockets.exceptions.ConnectionClosed:
            console.print('\n[bold red]Error: the connection to the server closed. Check that the server is running.[/bold red]')
            logger.error(f"Connection closed while sending data: {self.file}")
            if 'process' in locals() and process.returncode is None:
                process.terminate()
            raise
        except Exception as e:
            console.print(f'\n[red]Error during transcription: {e}')
            logger.error(f"Error sending transcription data: {e}", exc_info=True)
            if 'process' in locals() and process.returncode is None:
                process.terminate()
            return

    async def receive(self) -> None:
        """Receive the transcription result."""
        websocket = self.state.websocket

        try:
            async for message in websocket:
                message = json.loads(message)
                console.print(f'    Transcribed: {message["duration"]:.2f}s', end='\r')
                if message['is_final']:
                    break
        except websockets.exceptions.ConnectionClosed:
            console.print('\n[bold red]Error: the connection to the server closed while waiting for the result.[/bold red]')
            logger.error(f"Connection closed while receiving results: {self.file}")
            return
        except Exception as e:
            logger.error(f"Error receiving message: {e}")
            return

        # Save and format the result
        text_display = ResultHandler.save_results(self.file, message)

        process_duration = message['time_complete'] - message['time_start']
        console.print(f'\033[K    Processing time: {process_duration:.2f}s')
        console.print(f'    Result:\n[green]{text_display}')

        logger.info(
            f"Transcription finished: {self.file}, processing time: {process_duration:.2f}s, "
            f"text length: {len(text_display)}"
        )
