# coding: utf-8
"""
Text output module

Provides the TextOutput class, which sends recognition results to the current window.
"""

from __future__ import annotations

import asyncio
from typing import Optional
import re

import keyboard
import pyclip
from pynput import keyboard as pynput_keyboard

from config_client import ClientConfig as Config
from util.client.clipboard import keep_output_clipboard, should_keep_output_clipboard
from . import logger



class TextOutput:
    """
    Text output

    Outputs text either by simulated typing or by pasting.
    """

    @staticmethod
    def strip_punc(text: str) -> str:
        """
        Remove the final punctuation mark

        Args:
            text: Original text

        Returns:
            The text without its trailing punctuation mark
        """
        if not text or not Config.trash_punc:
            return text
        clean_text = re.sub(f"(?<=.)[{Config.trash_punc}]$", "", text)
        return clean_text

    async def output(self, text: str, paste: Optional[bool] = None) -> None:
        """
        Output a recognition result

        Types or pastes the text, depending on the configuration.

        Args:
            text: Text to output
            paste: Whether to paste (None means use the configured value)
        """
        if not text:
            return

        # Choose the output method
        if paste is None:
            paste = Config.paste

        if paste:
            await self._paste_text(text)
        else:
            self._type_text(text)

    async def _paste_text(self, text: str) -> None:
        """
        Output text by pasting

        Args:
            text: Text to paste
        """
        logger.debug(f"Pasting text, length: {len(text)}")

        # Save the clipboard
        try:
            temp = pyclip.paste().decode('utf-8')
        except Exception:
            temp = ''

        # Copy the result
        pyclip.copy(text)

        # Paste the result (simulate Ctrl+V with pynput)
        controller = pynput_keyboard.Controller()
        with controller.pressed(pynput_keyboard.Key.ctrl):
            controller.tap('v')

        logger.debug("Sent paste command (Ctrl+V)")

        keep_output = should_keep_output_clipboard()

        # Restore the clipboard; if the output fallback is on, leave the output text there instead
        if Config.restore_clip and not keep_output:
            await asyncio.sleep(0.1)
            pyclip.copy(temp)
            logger.debug("Clipboard restored")
        elif keep_output:
            keep_output_clipboard(text)

    def _type_text(self, text: str) -> None:
        """
        Output text by simulated typing

        Uses keyboard.write rather than pynput.keyboard.Controller.type(),
        which conflicts with some input methods.

        Args:
            text: Text to output
        """
        logger.debug(f"Typing text, length: {len(text)}")
        keep_output_clipboard(text)
        keyboard.write(text)
