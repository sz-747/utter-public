# coding: utf-8
import asyncio
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

from util.client.state import console
from . import logger

class MediaTool:
    """Media helpers: everything that touches FFmpeg."""

    @staticmethod
    def check_environment() -> bool:
        """Check that FFmpeg and ffprobe are available."""
        ffmpeg_path = shutil.which('ffmpeg')
        ffprobe_path = shutil.which('ffprobe')

        if ffmpeg_path is None:
            console.print('\n[bold red]Error: FFmpeg not found[/bold red]')
            console.print('    File transcription needs FFmpeg to extract the audio from audio and video files.')
            console.print('    [cyan]To fix this:[/cyan]')
            console.print('    1. Install FFmpeg and add its [bold]bin[/bold] folder to the [bold]Path[/bold] environment variable.')
            console.print('    2. Or put [bold]ffmpeg.exe[/bold] in the program folder.')
            console.print('    3. Downloads: [u]https://ffmpeg.org/download.html[/u]\n')
            logger.error("FFmpeg not found, cannot transcribe files")
            return False

        if ffprobe_path is None:
            console.print('\n[bold yellow]Note: ffprobe not found[/bold yellow]')
            console.print('    The file length cannot be read in advance, so progress shows only how much has been sent.')
            console.print('    [cyan]Tip:[/cyan] for full progress, make sure the FFmpeg bin folder includes ffprobe.exe.\n')
            logger.warning("ffprobe not found, progress display will be limited")

        return True

    @staticmethod
    async def get_audio_duration(file: Path) -> float:
        """Get the duration of an audio or video file."""
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", str(file)
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            stdout, stderr = await process.communicate()
            if process.returncode == 0:
                return float(stdout.decode().strip())
        except Exception as e:
            logger.warning(f"Could not get the duration with ffprobe: {e}")
        return 0.0

    @staticmethod
    def build_ffmpeg_cmd(file: Path) -> List[str]:
        """Build the FFmpeg command that extracts the audio."""
        return [
            "ffmpeg", "-i", str(file),
            "-f", "f32le", "-ac", "1", "-ar", "16000", "-"
        ]
