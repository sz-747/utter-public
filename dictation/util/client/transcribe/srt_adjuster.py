# coding: utf-8
"""
SRT adjustment

SrtAdjuster re-times SRT subtitles.
"""

from __future__ import annotations

import uuid
from pathlib import Path

from util.client.state import console
from util.tools import srt_from_txt
from . import logger



class SrtAdjuster:
    """
    SRT subtitle adjuster

    Rebuilds the SRT timeline from a text file.
    """

    def adjust(self, file: Path) -> None:
        """
        Re-time the SRT subtitles.

        Args:
            file: Path to the text file
        """
        task_id = str(uuid.uuid1())
        console.print(f'\nTask ID: {task_id}')
        console.print(f'    File: {file}')

        logger.info(f"Adjusting SRT: {file}")

        try:
            srt_from_txt.one_task(file)
            console.print('    [green]SRT adjusted')
            logger.info(f"SRT adjusted: {file}")
        except Exception as e:
            console.print(f'    [red]SRT adjustment failed: {e}')
            logger.error(f"SRT adjustment failed: {e}", exc_info=True)
