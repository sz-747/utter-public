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
import re
import threading
import time
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


# How long the target app gets to read the clipboard after Ctrl+V before the old content goes back,
# when its input field cannot be read. 0.1 s was too short for a busy app, which then pasted the old clipboard.
RESTORE_DELAY = 0.6
# Where the field can be read, the old content goes back once the dictation shows up in it. A busy app
# can take seconds to paste; restoring on a timer there would have pasted the old clipboard.
LANDING_TIMEOUT = 10.0
_LANDING_POLL = 0.1

_restore_lock = threading.Lock()
_restore = {'generation': 0, 'original': ''}     # the clipboard to give back, while a restore is waiting


def _field_reader():
    """A function returning the focused field's text (None when unreadable), or None without UI Automation."""
    try:
        import comtypes
        comtypes.CoInitialize()
        from util.client.learn.uia_text import UiaReader
        reader = UiaReader()
    except Exception:
        return None

    def read():
        element = reader.focused()
        if element is None or reader.is_password(element):
            return None
        return reader.text(element)
    return read


def _landed(before, now, text: str) -> bool:
    """Whether `text` was added to the field: its end appears more often now than before the paste.
    Spaces and line breaks are ignored, since apps report them differently."""
    if now is None:
        return False
    key = re.sub(r'\s+', '', text)[-30:]
    if not key:
        return True
    return re.sub(r'\s+', '', now).count(key) > re.sub(r'\s+', '', before or '').count(key)


def _restore_after_landing(generation: int, text: str, ready: threading.Event, sent: threading.Event) -> None:
    """Background: read the field, let Ctrl+V go, wait for the text to show up, then give the old clipboard back."""
    read = None
    before = None
    try:
        read = _field_reader()
        before = read() if read else None
    except Exception:
        read = None
    finally:
        ready.set()
    sent.wait(2)
    if read is None or before is None:
        time.sleep(RESTORE_DELAY)                 # a terminal or an unreadable field: the old fixed wait
    else:
        deadline = time.monotonic() + LANDING_TIMEOUT
        while True:
            try:
                if _landed(before, read(), text):
                    break
            except Exception:
                pass
            if time.monotonic() > deadline:
                # Still not in the field: it may paste later, so leave the dictation on the clipboard.
                logger.info(f"Dictation not seen in the field {LANDING_TIMEOUT:.0f} s after Ctrl+V; "
                            f"left it on the clipboard instead of restoring the old content")
                _finish_restore(generation, text, give_back=False)
                return
            time.sleep(_LANDING_POLL)
            with _restore_lock:
                if _restore['generation'] != generation:
                    return                        # a newer dictation took over the restore
    _finish_restore(generation, text)


def _finish_restore(generation: int, text: str, give_back: bool = True) -> None:
    with _restore_lock:
        if _restore['generation'] != generation:
            return
        original, _restore['original'] = (_restore['original'] if give_back else ''), ''
        # Copied something new meanwhile: keep it.
        if original and safe_paste() == text:
            for attempt in range(8):
                try:
                    pyclip.copy(original)
                    logger.debug("Clipboard restored")
                    return
                except Exception as e:
                    if attempt == 7:
                        logger.warning(f"Could not restore the clipboard: {e}")
                    time.sleep(0.03)


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
    restore = restore_clipboard and not should_keep_output_clipboard()

    # Save the clipboard; while the last dictation's restore still waits, the clipboard holds that
    # dictation and what the person had copied is in the waiting restore
    original, pending, generation = '', '', 0
    if restore:
        with _restore_lock:
            pending = _restore['original']
            _restore['generation'] += 1           # this dictation takes over any waiting restore
            generation = _restore['generation']
        try:
            original = pending or safe_paste()
        except Exception:
            pass

    # Copy the text to paste
    if not await _copy_with_retry(text):
        with _restore_lock:
            _restore['original'] = pending if _restore['generation'] == generation else _restore['original']
        return
    logger.debug(f"Copied text to the clipboard, length: {len(text)}")

    sent = threading.Event()
    if restore and original:
        with _restore_lock:
            _restore['original'] = original
        ready = threading.Event()
        threading.Thread(target=_restore_after_landing, args=(generation, text, ready, sent),
                         name='clipboard-restore', daemon=True).start()
        ready.wait(0.3)                           # the field as it was before Ctrl+V

    # Paste it (pynput simulates Ctrl+V)
    controller = keyboard.Controller()
    with controller.pressed(keyboard.Key.ctrl):
        controller.tap('v')

    logger.debug("Sent the paste command (Ctrl+V)")

    # The target app reads the clipboard after Ctrl+V. Writing to it right away (as this did to keep
    # the output there) collided with that read, and the paste came out empty while the text stayed
    # on the clipboard. When the output is kept it is already there, so nothing more is written;
    # otherwise the restore thread gives the old content back once the paste has landed.
    sent.set()
