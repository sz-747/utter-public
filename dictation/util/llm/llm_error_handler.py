"""
LLM error handling and user messages

Handles LLM exceptions in one place and shows friendly error messages
"""
from typing import Optional, Tuple
from util.llm.llm_exceptions import (
    OpenAIErrorWrapper,
    AuthenticationErrorWrapper,
    RateLimitErrorWrapper,
    TimeoutErrorWrapper,
    ConnectionErrorWrapper,
    APIResponseErrorWrapper,
)
from . import logger


# A stopped model server fails every dictation the same way: show it once, until a request succeeds
_connection_error_shown = False


def note_llm_success():
    """Called after a request succeeds, so the next connection failure is shown again."""
    global _connection_error_shown
    _connection_error_shown = False


def get_user_friendly_message(error: Exception) -> str:
    """
    Return a friendly error message

    Args:
        error: the exception

    Returns:
        A friendly error message
    """
    # Wrapped OpenAI exception
    if isinstance(error, OpenAIErrorWrapper):
        if getattr(error, 'starting', False):
            return error.starting_message
        return error.user_message

    # Any other exception
    return f"the request failed ({type(error).__name__})."


def should_fallback_to_original(error: Exception) -> bool:
    """
    Decide whether to fall back to the original text silently

    Every error outputs the original text, so no dictation is lost.
    Authentication, connection and response errors need the user to fix their settings, so an
    error message is shown as well; temporary problems such as timeouts and rate limits fall back silently.

    Args:
        error: the exception

    Returns:
        True to fall back silently, False to fall back and show an error message
    """
    # Authentication failed: the user must set up the API key
    if isinstance(error, AuthenticationErrorWrapper):
        return False

    # Connection failed: the user should check the network and the API URL
    if isinstance(error, ConnectionErrorWrapper):
        return False

    # API response error: the user should check the settings
    if isinstance(error, APIResponseErrorWrapper):
        return False

    # Timeouts and rate limits: fall back to the original text
    if isinstance(error, (TimeoutErrorWrapper, RateLimitErrorWrapper)):
        return True

    # Anything else: play safe and fall back
    return True


def show_error_notification(error: Exception, role_name: str = "LLM"):
    """
    Show an error notification (toast or console)

    Args:
        error: the exception
        role_name: role name
    """
    user_msg = get_user_friendly_message(error)

    # Log it
    logger.warning(f"[{role_name}] {user_msg} - {error}")

    # Try to show a toast
    try:
        from util.ui.toast import ToastMessageManager, ToastMessage

        toast_manager = ToastMessageManager()

        # The dictation was typed, only not polished: the same small notice as "Not typed ... Saved in Utter",
        # not a red error box
        msg = ToastMessage(
            text=f"Typed without AI polish: {user_msg}",
            font_size=12,
            bg='#1f5f57',
            fg='white',
            duration=4500,
            streaming=False,
            window_type='text'
        )
        toast_manager.add_message(msg)   # Non-streaming windows close themselves after duration

    except Exception as e:
        # The toast failed; fall back to the console
        logger.error(f"Could not show the toast: {e}")


def handle_llm_error(error: Exception, original_text: str, role_name: str = "LLM",
                     fallback_text: Optional[str] = None) -> Tuple[str, bool]:
    """
    Single entry point for LLM error handling

    Args:
        error: the exception
        original_text: the original input text
        role_name: role name
        fallback_text: text to use when falling back (None means original_text)

    Returns:
        (output text, success); the output is always the original text or fallback_text, so no dictation is lost
    """
    global _connection_error_shown
    result = fallback_text if fallback_text is not None else original_text
    if should_fallback_to_original(error):
        logger.info(f"[{role_name}] Processing failed, falling back to the original text: {error}")
    elif isinstance(error, ConnectionErrorWrapper) and _connection_error_shown:
        logger.info(f"[{role_name}] Model server still unreachable, typed the original text")
    else:
        # Settings or connection problem: tell the user, and output the original text as usual
        show_error_notification(error, role_name)
        if isinstance(error, ConnectionErrorWrapper):
            _connection_error_shown = True
        logger.info(f"[{role_name}] Processing failed, showed the error and typed the original text")
    return (result, False)
