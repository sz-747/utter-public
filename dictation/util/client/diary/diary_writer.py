# coding: utf-8
"""
Diary writer

Provides the DiaryWriter class, which writes recognition results to Markdown diary files.
"""

from __future__ import annotations

import time
from os import makedirs
from pathlib import Path
from typing import Optional, List

from util.client.state import console
from . import logger


# Header template for new Markdown files
HEADER_MD = r'''```txt
Regex tip

Match audio file links: \[(.+)\]\((.{10,})\)[\s]*
Replace with an HTML player: <audio controls><source src="$2" type="audio/mpeg">$1</audio>\n\n

Match HTML players: <audio controls><source src="(.+)" type="audio/mpeg">(.+)</audio>\n\n
Replace with file links: [$2]($1)
```


'''


class DiaryWriter:
    """
    Diary writer

    Writes recognition results to Markdown diary files:
    - creates a folder structure by date
    - links the audio files
    """

    def __init__(self, base_path: Optional[Path] = None):
        """
        Initialize the diary writer

        Args:
            base_path: Base folder, the current folder by default
        """
        self.base_path = base_path or Path()

    def write(
        self,
        text: str,
        time_start: float,
        file_audio: Optional[Path] = None
    ) -> List[Path]:
        """
        Write a diary entry

        Args:
            text: Recognized text
            time_start: Recording start timestamp
            file_audio: Audio file path (optional)

        Returns:
            List of diary files written
        """
        local_time = time.localtime(time_start)
        time_year = time.strftime('%Y', local_time)
        time_month = time.strftime('%m', local_time)
        time_day = time.strftime('%d', local_time)
        time_hms = time.strftime('%H:%M:%S', local_time)

        folder_path = self.base_path / time_year / time_month
        makedirs(folder_path, exist_ok=True)

        # One file per day
        file_md = folder_path / f'{time_day}.md'

        # Make sure the Markdown file exists
        if not file_md.exists():
            self._create_md(file_md)

        # Build the diary entry
        if file_audio:
            try:
                path_rel = file_audio.relative_to(file_md.parent).as_posix()
                path_rel = path_rel.replace(" ", "%20")
            except ValueError:
                path_rel = file_audio.as_posix().replace(" ", "%20")
        else:
            path_rel = ""

        # Write the Markdown
        with open(file_md, 'a', encoding='utf-8') as f:
            if path_rel:
                f.write(f'[{time_hms}]({path_rel}) {text}\n\n')
            else:
                f.write(f'{time_hms} {text}\n\n')

        logger.debug(f"Wrote diary entry: {file_md.name}")
        return [file_md]

    def _create_md(self, file_md: Path) -> None:
        """Create a new Markdown file"""
        with open(file_md, 'w', encoding='utf-8') as f:
            f.write(HEADER_MD)
        logger.debug(f"Created diary file: {file_md}")
