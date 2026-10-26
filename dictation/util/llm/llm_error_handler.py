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
        return error.user_message

    # Any other exception
    return f"Processing failed: {type(error).__name__}"


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

        # Errors use a red background and a larger size
        msg = ToastMessage(
            text=f"❌ {role_name}: {user_msg}",
            font_size=16,           # Larger font
            bg='#8B0000',           # Dark red
            fg='white',
            duration=5000,          # Show for 5 seconds
            initial_width=0.6,      # 60% of the screen width
            initial_height=80,      # Fixed minimum height of 80 px
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
    result = fallback_text if fallback_text is not None else original_text
    if should_fallback_to_original(error):
        logger.info(f"[{role_name}] Processing failed, falling back to the original text: {error}")
    else:
        # Settings or connection problem: tell the user, and output the original text as usual
        show_error_notification(error, role_name)
        logger.info(f"[{role_name}] Processing failed, showed the error and typed the original text")
    return (result, False)
