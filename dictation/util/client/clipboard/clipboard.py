# coding: utf-8
"""
Clipboard helpers

One place for clipboard operations:
1. Read the clipboard safely (tries several encodings)
2. Write to the clipboard safely
3. A context manager that saves and restores the clipboard
4. Paste text (simulates Ctrl+V)
"""
import asyncio
from contextlib import contextmanager
import pyclip
from pynput import keyboard
from . import logger


# Encodings tried, in order, when decoding clipboard bytes
CLIPBOARD_ENCODINGS = ['utf-8', 'utf-16', 'latin1']


def safe_paste() -> str:
    """
    Read and decode text from the clipboard.

    Tries several encodings so the text decodes correctly.

    Returns:
        The decoded text, or an empty string on failure
    """
    try:
        clipboard_data = pyclip.paste()

        # Try each encoding in turn
        for encoding in CLIPBOARD_ENCODINGS:
            try:
                return clipboard_data.decode(encoding)
            except (UnicodeDecodeError, AttributeError):
                continue

        # Every encoding failed
        logger.debug(f"Could not decode the clipboard, tried: {CLIPBOARD_ENCODINGS}")
        return ""

    except Exception as e:
        logger.warning(f"Could not read the clipboard: {e}")
        return ""


def safe_copy(content: str) -> bool:
    """
    Copy content to the clipboard.

    Args:
        content: What to copy

    Returns:
        Whether it worked
    """
    if not content:
        return False

    try:
        pyclip.copy(content)
        logger.debug(f"Wrote to the clipboard, length: {len(content)}")
        return True
    except Exception as e:
        logger.warning(f"Could not write to the clipboard: {e}")
        return False


def copy_to_clipboard(content: str):
    """
    Copy content to the clipboard (old API, kept for compatibility).

    Args:
        content: What to copy
    """
    safe_copy(content)


def should_keep_output_clipboard() -> bool:
    """Whether the final output text should stay on the clipboard."""
    try:
        from config_client import ClientConfig as Config
        return bool(getattr(Config, 'copy_output_to_clipboard', False))
    except Exception:
        return False


def keep_output_clipboard(content: str) -> bool:
    """
    Leave the final output text on the clipboard so it can be pasted by hand
    if focus was lost.
    """
    if not should_keep_output_clipboard():
        return False
    return safe_copy(content)


@contextmanager
def save_and_restore_clipboard():
    """
    Save the clipboard and restore it afterwards.

    Usage:
        with save_and_restore_clipboard():
            # use the clipboard here
            pyclip.copy("temporary content")
        # the original contents are back after the block
    """
    original = safe_paste()
    try:
        yield
    finally:
        if original:
            pyclip.copy(original)
            logger.debug("Clipboard restored")


# How long the target app gets to read the clipboard after Ctrl+V before the old content goes back.
# 0.1 s was too short for a busy app, which then pasted the old clipboard.
RESTORE_DELAY = 0.6


async def _copy_with_retry(text: str, attempts: int = 8) -> bool:
    """Put text on the clipboard, waiting while another app briefly holds it open."""
    for attempt in range(attempts):
        try:
            pyclip.copy(text)
            return True
        except Exception as e:
            if attempt == attempts - 1:
                logger.warning(f"Could not write the clipboard ({attempts} tries): {e}")
                return False
            await asyncio.sleep(0.03)
    return False


async def paste_text(text: str, restore_clipboard: bool = True):
    """
    Paste text by simulating Ctrl+V.

    Args:
        text: The text to paste
        restore_clipboard: Whether to put the original clipboard contents back afterwards
    """
    keep_output = should_keep_output_clipboard()

    # Save the clipboard
    original = ''
    if restore_clipboard and not keep_output:
        try:
            original = safe_paste()
        except:
            pass

    # Copy the text to paste
    if not await _copy_with_retry(text):
        return
    logger.debug(f"Copied text to the clipboard, length: {len(text)}")

    # Paste it (pynput simulates Ctrl+V)
    controller = keyboard.Controller()
    with controller.pressed(keyboard.Key.ctrl):
        controller.tap('v')

    logger.debug("Sent the paste command (Ctrl+V)")

    # The target app reads the clipboard after Ctrl+V. Writing to it right away (as this did to keep
    # the output there) collided with that read, and the paste came out empty while the text stayed
    # on the clipboard. When the output is kept it is already there, so nothing more is written.
    if restore_clipboard and original and not keep_output:
        await asyncio.sleep(RESTORE_DELAY)
        if await _copy_with_retry(original):
            logger.debug("Clipboard restored")
