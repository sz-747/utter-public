"""Start a local Ollama when AI polish finds it off.

Ollama can stop after the client started (closed, crashed, the PC woke without it). Without this
every long dictation is typed unpolished until someone runs it by hand. Utter's meeting notes do
the same (utter/summary.py _start_local_ai).
"""
import shutil
import subprocess
import time

from . import logger

_RETRY_SECONDS = 300          # a start that failed is not retried on every dictation
_last_start = 0.0


def start_ollama() -> bool:
    """Launch `ollama serve` hidden, at most once per _RETRY_SECONDS. True if it was launched now
    or recently (it needs a few seconds before it answers); False if Ollama is not installed."""
    global _last_start
    if time.monotonic() - _last_start < _RETRY_SECONDS and _last_start:
        return True
    exe = shutil.which('ollama')
    if not exe:
        return False
    try:
        subprocess.Popen([exe, 'serve'], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)
                         | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
    except OSError as e:
        logger.warning(f'Could not start Ollama: {e}')
        return False
    _last_start = time.monotonic()
    logger.info('AI polish: Ollama was not running, started it')
    return True
