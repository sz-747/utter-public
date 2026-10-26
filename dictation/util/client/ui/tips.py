# coding: utf-8
"""
Startup tips

TipsDisplay prints the tips shown when the client starts.
"""

from __future__ import annotations

import os

from rich.markdown import Markdown

from util.client.state import console
from config_client import ClientConfig as Config, __version__
from . import logger



def _format_shortcut_name(key: str) -> str:
    """
    Format a shortcut name for display.

    Args:
        key: Shortcut name (e.g. 'caps_lock', 'f12')

    Returns:
        str: Display name (e.g. 'Caps Lock', 'F12')
    """
    # Replace underscores with spaces, then title-case
    return key.replace('_', ' ').title()


def _get_shortcuts_display() -> str:
    """
    Get the display string for all enabled shortcuts.

    Returns:
        str: The shortcut names, comma-separated
    """
    enabled_shortcuts = [sc for sc in Config.shortcuts if sc.get('enabled', True)]
    if not enabled_shortcuts:
        return 'No shortcuts configured'

    # Format each shortcut name
    formatted = [_format_shortcut_name(sc['key']) for sc in enabled_shortcuts]
    return ', '.join(formatted)


class TipsDisplay:
    """
    Tips display

    Prints the tips shown when the client starts.
    """

    @staticmethod
    def show_mic_tips() -> None:
        """Show the startup tips for microphone mode."""
        shortcuts_display = _get_shortcuts_display()

        console.rule('[bold #1f5f57]Utter dictation client')
        console.print(f'\nVersion: [bold green]{__version__}')

        markdown = f'''

Based on: https://github.com/HaujetZhao/CapsWriter-Offline

How to use it:

1. The **speech server** recognises speech, on this PC or on another PC over Tailscale.
2. This **client** listens for the shortcut, records and types the text.
3. Press the shortcut (`{shortcuts_display}`), speak, and press it again to type.


Features:

1. **Dictionary**: `hot.txt` words are matched by sound to fix misheard names and terms.
2. **Replacement rules**: `hot-rule.txt` rewrites fixed phrases, spoken email addresses and filler words.
3. **Learning**: names you correct after dictating are added to the dictionary.
4. **AI polish**: an optional local model cleans up long dictations.
5. **Archive**: every dictation's text is kept in `transcripts/`, and recordings in the year folders.
6. **Tray**: right-click the tray icon to copy the last result, add dictionary words or corrections, or restart audio.


Notes:

1. Current shortcut: `{shortcuts_display}`. Change it in Utter's Settings (or `config_client.py`).
2. To type into programs running as administrator (such as Task Manager or games), **run the client as administrator**.
3. Trailing commas and full stops are removed from results by default.
4. Saved recordings: if `FFmpeg` is found they are saved as compressed `mp3`, otherwise as `wav`.
        '''

        console.print(Markdown(markdown), highlight=True)
        console.rule()
        console.print(f'\nWorking folder: [cyan underline]{os.getcwd()}')
        console.print(f'\nServer address: [cyan underline]{Config.addr}:{Config.port}')
        console.print(f'\nShortcuts in use: [green4]{shortcuts_display}')
        console.line()

        logger.debug("Showed the microphone mode startup tips")

    @staticmethod
    def show_file_tips() -> None:
        """Show the startup tips for file transcription mode."""
        console.print(f'\nVersion: [bold green]{__version__}')

        markdown = '\nBased on: https://github.com/HaujetZhao/CapsWriter-Offline'
        console.print(Markdown(markdown), highlight=True)
        console.print(f'Working folder: [cyan underline]{os.getcwd()}')
        console.print(f'Server address: [cyan underline]{Config.addr}:{Config.port}')

        logger.debug("Showed the file transcription mode startup tips")
