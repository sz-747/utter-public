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


async def paste_text(text: str, restore_clipboard: bool = True):
    """
    Paste text by simulating Ctrl+V.

    Args:
        text: The text to paste
        restore_clipboard: Whether to put the original clipboard contents back afterwards
    """
    # Save the clipboard
    original = ''
    if restore_clipboard:
        try:
            original = safe_paste()
        except:
            pass

    # Copy the text to paste
    pyclip.copy(text)
    logger.debug(f"Copied text to the clipboard, length: {len(text)}")

    # Paste it (pynput simulates Ctrl+V)
    controller = keyboard.Controller()
    with controller.pressed(keyboard.Key.ctrl):
        controller.tap('v')

    logger.debug("Sent the paste command (Ctrl+V)")

    keep_output = should_keep_output_clipboard()

    # Restore the clipboard, unless the output should stay on it as a fallback
    if restore_clipboard and original and not keep_output:
        await asyncio.sleep(0.1)
        pyclip.copy(original)
        logger.debug("Clipboard restored")
    elif keep_output:
        safe_copy(text)
