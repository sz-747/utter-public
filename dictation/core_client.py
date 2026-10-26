# coding: utf-8
"""
Dictation client entry point

Main entry point of the dictation client. It has two modes:
1. Microphone mode: live dictation
2. File mode: transcribe audio or video files into subtitles

Usage:
    python core_client.py              # microphone mode
    python core_client.py file1.mp4    # file mode
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from platform import system
from typing import List

import colorama
import typer

from config_client import ClientConfig as Config, __version__
from util.logger import setup_logger
from util.common.lifecycle import lifecycle

# Run from this folder so the dictionary files and data folders resolve by relative path
BASE_DIR = os.path.dirname(__file__)
os.chdir(BASE_DIR)

# Make sure the terminal handles ANSI control codes
colorama.init()

_main_task = None  # main task reference
_client_mutex_handle = None


def _acquire_single_client_lock() -> bool:
    """Prevent more than one microphone client from running at once."""
    global _client_mutex_handle

    if _client_mutex_handle:
        return True

    if system() != 'Windows':
        return True

    import ctypes

    error_already_exists = 183
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    handle = kernel32.CreateMutexW(None, False, 'Local\\UtterDictationClient')
    if not handle:
        return True

    if ctypes.get_last_error() == error_already_exists:
        kernel32.CloseHandle(handle)
        return False

    _client_mutex_handle = handle
    return True


def _release_single_client_lock() -> None:
    """Release the single-instance lock."""
    global _client_mutex_handle

    if system() != 'Windows' or not _client_mutex_handle:
        return

    import ctypes

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.CloseHandle(_client_mutex_handle)
    _client_mutex_handle = None


if not sys.argv[1:] and not _acquire_single_client_lock():
    print("A dictation client is already running, so this one has exited.")
    sys.exit(0)


# Set up logging
logger = setup_logger('client', level=Config.log_level)


async def main_mic() -> None:
    """
    Microphone mode

    Starts live speech recognition and listens for the shortcut that starts and stops recording.
    """
    global _main_task

    # Set up the lifecycle
    lifecycle.initialize(logger=logger, exit_on_signal=True)

    # Keep a reference to the current task
    _main_task = asyncio.current_task()

    from util.client.state import console
    from util.client.output import ResultProcessor
    from util.client.startup import setup_client_components

    logger.info("=" * 50)
    logger.info("Dictation client starting (microphone mode)")
    logger.info(f"Version: {__version__}")
    logger.info(f"Log level: {Config.log_level}")

    # Set up all components
    _state = setup_client_components(BASE_DIR)

    # Receive results
    try:
        processor = ResultProcessor(_state)
        _state.processor = processor # store on the state so cleanup can find it

        # Main loop: run until a shutdown signal arrives
        while not lifecycle.is_shutting_down:
            # Start the processing task
            process_task = asyncio.create_task(processor.process_loop())
            # Start the shutdown wait task
            wait_shutdown = asyncio.create_task(lifecycle.wait_for_shutdown())

            done, pending = await asyncio.wait(
                [process_task, wait_shutdown],
                return_when=asyncio.FIRST_COMPLETED
            )

            # Shutdown signal received
            if wait_shutdown in done:
                logger.info("Main loop saw the shutdown signal")
                process_task.cancel() # cancel any processing in progress
                break

            # If the processing task ended (normally or not), go round again.
            # ResultProcessor should loop forever unless something goes wrong.
            if process_task in done:
                # Check for a shutdown request (the processor may have raised one)
                if lifecycle.is_shutting_down:
                    break
                # No shutdown requested but the task ended, so it probably failed
                try:
                    await process_task
                except Exception as e:
                    logger.error(f"Processing loop error: {e}")
                    # Avoid flooding the log in a tight loop
                    await asyncio.sleep(1)

    except asyncio.CancelledError:
        logger.info("Main task cancelled, exiting...")
        raise
    except Exception as e:
        logger.error(f"Error while receiving results: {e}", exc_info=True)
        raise
    finally:
        # This finally is for resources local to the coroutine;
        # global cleanup is left to lifecycle
        pass


async def main_file(files: List[Path]) -> None:
    """
    File mode

    Args:
        files: Files to transcribe
    """
    # Set up the lifecycle
    lifecycle.initialize(logger=logger, exit_on_signal=True)

    from util.client.state import get_state, console
    from util.client.transcribe import FileTranscriber, SrtAdjuster
    from util.client.ui import TipsDisplay

    logger.info("=" * 50)
    logger.info("Dictation client starting (file mode)")
    logger.info(f"Version: {__version__}")
    logger.info(f"Log level: {Config.log_level}")
    logger.info(f"Files to process: {[str(f) for f in files]}")

    state = get_state()
    TipsDisplay.show_file_tips()

    srt_adjuster = SrtAdjuster()

    for file in files:
        if lifecycle.is_shutting_down:
            break

        logger.info(f"Processing file: {file}")

        if file.suffix in ['.txt', '.json', '.srt']:
            srt_adjuster.adjust(file)
        else:
            transcriber = FileTranscriber(state, file)
            if await transcriber.check():
                await transcriber.send()
                await transcriber.receive()

        logger.info(f"Finished file: {file}")

    # Close the connection
    if state.websocket:
        await state.websocket.close()

    logger.info("All files processed")
    input('\nPress Enter to exit\n')


def init_mic() -> None:
    """Set up and run microphone mode"""
    from util.client.state import console

    if not _acquire_single_client_lock():
        logger.warning("A dictation client is already running; this instance is exiting")
        print("A dictation client is already running, so this one has exited.")
        return

    from util.client.cleanup import cleanup_client_resources

    # Register cleanup functions
    lifecycle.register_on_shutdown(cleanup_client_resources)
    lifecycle.register_on_shutdown(_release_single_client_lock)

    try:
        asyncio.run(main_mic())
        lifecycle.cleanup() # cleanup on normal exit
    except KeyboardInterrupt:
        # With lifecycle in place this is rarely reached, unless the signal
        # handler did not take effect or the interrupt came outside async code
        logger.info("Stop signal received...")
        lifecycle.cleanup()
    except asyncio.CancelledError:
        logger.info("Task cancelled...")
        lifecycle.cleanup()
    except Exception as e:
        logger.error(f"Runtime error: {e}", exc_info=True)
        lifecycle.cleanup()
        raise


def init_file(files: List[Path]) -> None:
    """
    Set up and run file mode
    """
    from util.client.state import console
    from util.client.cleanup import cleanup_client_resources

    lifecycle.register_on_shutdown(cleanup_client_resources)

    try:
        asyncio.run(main_file(files))
        lifecycle.cleanup()
    except KeyboardInterrupt:
        logger.info("Stop signal received...")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Error while transcribing files: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    # Transcribe any files passed as arguments;
    # with no arguments, dictate from the microphone
    if sys.argv[1:]:
        typer.run(init_file)
    else:
        init_mic()
