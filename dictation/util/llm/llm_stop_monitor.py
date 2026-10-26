"""
LLM output interrupt monitor

Listens for the interrupt key (Esc by default) and stops LLM streaming output

Uses pynput GlobalHotKeys instead of the keyboard library
"""
import logging
import threading
from typing import Optional
from config_client import ClientConfig as Config
from . import logger


# Global event: tells the LLM to stop output (when Esc is pressed by hand)
_stop_event = threading.Event()

# Thread-local storage: a separate stop flag for each task
_thread_local = threading.local()

# Global hotkey manager reference
_hotkey_manager = None


def should_stop() -> bool:
    """
    Check whether output should stop

    Returns:
        True means stop
    """
    # Check the thread-local stop flag first
    local_stop = getattr(_thread_local, 'stop_event', None)
    if local_stop and local_stop.is_set():
        return True

    # Then the global stop flag (set by Esc)
    return _stop_event.is_set()


def reset():
    """Reset the stop flags (call before starting new output)"""
    _stop_event.clear()
    # Reset the thread-local stop flag
    local_stop = getattr(_thread_local, 'stop_event', None)
    if local_stop:
        local_stop.clear()


def create_stop_callback() -> 'threading.Event':
    """
    Create a separate stop event for a new LLM task

    Returns:
        The stop event
    """
    stop_event = threading.Event()
    _thread_local.stop_event = stop_event
    return stop_event


def on_stop_pressed():
    """Callback for when the user presses the interrupt key"""
    logger.debug("Esc pressed, stopping LLM output")
    _stop_event.set()


def start_monitor():
    """Start watching for the interrupt key (called automatically on import)"""
    global _hotkey_manager

    try:
        from util.client.global_hotkey import get_global_hotkey_manager

        _hotkey_manager = get_global_hotkey_manager()

        # Convert Config.llm_stop_key to pynput format
        # The default is 'esc'; in pynput format that is '<esc>'
        stop_key = Config.llm_stop_key.lower().strip()
        if not stop_key.startswith('<'):
            stop_key = f'<{stop_key}>'

        _hotkey_manager.register(stop_key, on_stop_pressed)
        _hotkey_manager.start()
        logger.debug(f"LLM interrupt key monitor started: {stop_key}")
    except Exception as e:
        logger.warning(f"Could not start the LLM interrupt key monitor: {e}")


def stop_monitor():
    """Stop watching for the interrupt key"""
    global _hotkey_manager
    if _hotkey_manager:
        try:
            _hotkey_manager.stop()
            logger.debug("LLM interrupt key monitor stopped")
        except Exception as e:
            logger.warning(f"Could not stop the LLM interrupt key monitor: {e}")


# Start the monitor automatically
start_monitor()
