# coding: utf-8
"""
Audio file management

Provides the AudioFileManager class, which creates, writes, finishes and
renames audio files. Supports MP3 (needs FFmpeg) and WAV.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
import time
import wave
from os import makedirs
from pathlib import Path
from subprocess import DEVNULL, PIPE, Popen
from typing import Optional, Tuple, Union

import numpy as np

from config_client import ClientConfig as Config
from . import logger


# Audio file handle type
AudioWriter = Union[Popen, wave.Wave_write]
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


class AudioFileManager:
    """
    Audio file manager

    Handles an audio file's whole life:
    - create: MP3 or WAV, depending on whether FFmpeg is installed
    - write: write audio data to the file
    - finish: close the file handle
    - rename: rename the file after the recognized text
    """

    SAMPLE_RATE = 48000

    def __init__(self):
        """Initialize the audio file manager"""
        self.file_path: Optional[Path] = None
        self.file_handle: Optional[AudioWriter] = None
        self.channels: int = 1
        self._has_ffmpeg = shutil.which('ffmpeg') is not None

        if self._has_ffmpeg:
            logger.debug("FFmpeg found; recordings will be saved as MP3")
        else:
            logger.debug("FFmpeg not found; recordings will be saved as WAV")

    def create(self, channels: int, time_start: float) -> Tuple[Path, AudioWriter]:
        """
        Create an audio file

        Args:
            channels: Number of audio channels
            time_start: Recording start timestamp

        Returns:
            (file path, file writer handle) tuple
        """
        self.channels = channels

        # Build the folder and file name
        local_time = time.localtime(time_start)
        time_year = time.strftime('%Y', local_time)
        time_month = time.strftime('%m', local_time)
        time_ymdhms = time.strftime("%Y%m%d-%H%M%S", local_time)

        folder_path = Path() / time_year / time_month / 'assets'
        makedirs(folder_path, exist_ok=True)

        # Temporary file name
        file_path = tempfile.mktemp(prefix=f'({time_ymdhms})', dir=folder_path)
        file_path = Path(file_path)

        if self._has_ffmpeg:
            # Write MP3 through FFmpeg
            file_path = file_path.with_suffix('.mp3')
            ffmpeg_command = [
                'ffmpeg', '-y',
                '-f', 'f32le',
                '-ar', str(self.SAMPLE_RATE),
                '-ac', str(channels),
                '-i', '-',
                '-b:a', '192k',
                str(file_path),
            ]
            file_handle = Popen(
                ffmpeg_command,
                stdin=PIPE,
                stdout=DEVNULL,
                stderr=DEVNULL,
                creationflags=_NO_WINDOW,
            )
            logger.debug(f"Created MP3 file: {file_path}")
        else:
            # Write WAV with the wave module
            file_path = file_path.with_suffix('.wav')
            file_handle = wave.open(str(file_path), 'w')
            file_handle.setnchannels(channels)
            file_handle.setsampwidth(2)  # 16-bit
            file_handle.setframerate(self.SAMPLE_RATE)
            logger.debug(f"Created WAV file: {file_path}")

        self.file_path = file_path
        self.file_handle = file_handle

        return file_path, file_handle

    def write(self, data: np.ndarray) -> None:
        """
        Write audio data

        Args:
            data: Audio data array (float32)
        """
        if self.file_handle is None:
            logger.warning("Tried to write data but no file is open")
            return

        if isinstance(self.file_handle, Popen):
            # FFmpeg process
            self.file_handle.stdin.write(data.tobytes())
            self.file_handle.stdin.flush()
        elif isinstance(self.file_handle, wave.Wave_write):
            # WAV file: convert float32 -> int16
            int_data = (data * (2**15 - 1)).astype(np.int16).tobytes()
            self.file_handle.writeframes(int_data)

    def finish(self) -> Optional[Path]:
        """
        Finish writing the audio file

        Returns:
            The audio file path
        """
        if self.file_handle is None:
            return self.file_path

        try:
            if isinstance(self.file_handle, Popen):
                self.file_handle.stdin.close()
                logger.debug("FFmpeg process closed")
            elif isinstance(self.file_handle, wave.Wave_write):
                self.file_handle.close()
                logger.debug("WAV file closed")
        except Exception as e:
            logger.error(f"Error closing the audio file: {e}")
        finally:
            self.file_handle = None

        return self.file_path

    def rename(self, text: str, time_start: float) -> Optional[Path]:
        """
        Rename the audio file after the recognized text

        Args:
            text: Recognized text
            time_start: Recording start timestamp

        Returns:
            The renamed file path, or None on failure
        """
        if self.file_path is None or not self.file_path.exists():
            logger.warning(f"File does not exist, cannot rename: {self.file_path}")
            return None

        # Build the new file name
        time_ymdhms = time.strftime("%Y%m%d-%H%M%S", time.localtime(time_start))

        # Truncate the text and replace characters not allowed in file names
        text_clean = text[:Config.audio_name_len]
        text_clean = re.sub(r'[\\/:\"*?<>|]', ' ', text_clean)

        file_stem = f'({time_ymdhms}){text_clean}'
        new_path = self.file_path.with_name(file_stem + self.file_path.suffix)

        try:
            self.file_path.rename(new_path)
            logger.debug(f"Renamed audio file: {self.file_path.name} -> {new_path.name}")
            self.file_path = new_path
            return new_path
        except Exception as e:
            logger.error(f"Failed to rename the audio file: {e}")
            return self.file_path
