"""
Client resource cleanup

Releases the client's resources when it exits.
"""

import asyncio
from . import logger
from util.common.lifecycle import lifecycle
from util.client.state import get_state, console


def request_exit_from_tray(icon=None, item=None):
    """
    Exit callback used by the tray icon
    """
    logger.info("Tray exit: the user chose Exit, cleaning up and exiting")
    lifecycle.request_shutdown(reason="Tray Icon")

def cleanup_client_resources():
    """
    Clean up client resources
    """
    state = get_state()

    # Stop the shortcut listener
    if state.shortcut_handler:
        try:
            state.shortcut_handler.stop()
            logger.debug("Shortcut listener stopped")
        except Exception as e:
            logger.warning(f"Error stopping the shortcut listener: {e}")

    # Stop the mouse listener
    if state.mouse_handler:
        try:
            state.mouse_handler.stop()
            logger.debug("Mouse listener stopped")
        except Exception as e:
            logger.warning(f"Error stopping the mouse listener: {e}")

    # Stop the audio stream
    if state.stream_manager:
        try:
            if hasattr(state.stream_manager, 'close'):
                 state.stream_manager.close()
            # state.stream will be set to None in state.reset() later
        except Exception as e:
            logger.warning(f"Error stopping the audio stream: {e}")

    # Stop the result processor
    if state.processor:
        # The processor may have no explicit stop; it relies on its loop exiting
        pass

    # Close the WebSocket connection
    if state.websocket is not None:
        try:
            logger.debug("Trying to close the WebSocket connection...")
            if state.loop and state.loop.is_running():
                # run_coroutine_threadsafe schedules safely from signal handlers and other threads
                asyncio.run_coroutine_threadsafe(state.websocket.close(), state.loop)
            # With no running loop, the websocket is cleared when the state resets
        except AttributeError:
             pass # already closed, or no closed attribute
        except Exception as e:
            logger.warning(f"Error closing the WebSocket connection: {e}")

    # Unmute muted apps and tell the desktop app the client has stopped
    try:
        from util.client.audio.feedback import get_feedback
        get_feedback().shutdown()
    except Exception as e:
        logger.warning(f"Error unmuting apps: {e}")
    try:
        from util.client.learn.reviewer import get_reviewer
        get_reviewer().shutdown()
    except Exception as e:
        logger.warning(f"Error stopping the AI review: {e}")
    try:
        from util.client.learn.edit_watcher import get_edit_watcher
        get_edit_watcher().shutdown()
    except Exception as e:
        logger.warning(f"Error stopping auto-learning: {e}")
    try:
        from util.client.runtime_status import get_runtime_status
        get_runtime_status().stop()
    except Exception as e:
        logger.warning(f"Error writing the stopped status: {e}")

    # Fully reset the state
    try:
        state.reset()
    except Exception as e:
        logger.warning(f"Error resetting the state: {e}")

    # Stop the tray icon
    try:
        from util.client.ui import stop_tray
        stop_tray()
    except Exception as e:
        logger.warning(f"Error stopping the tray icon: {e}")

    logger.info("Client resources cleaned up")
    console.print('[green4]Goodbye!')
