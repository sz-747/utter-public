"""
LLM toast output mode

Streams into a floating window, which stays for 3 seconds when done
"""
import asyncio
import logging

from util.client.output.text_output import TextOutput
from util.tools.asyncio_to_thread import to_thread
from util.llm.llm_stop_monitor import reset, should_stop, create_stop_callback
from util.llm.llm_role_config import RoleConfig

logger = logging.getLogger(__name__)


async def handle_toast_mode(text: str, role_config=None, matched_hotwords=None, content=None) -> tuple:
    """Toast floating-window mode"""
    from util.llm.llm_handler import get_handler
    from util.ui.toast import ToastMessageManager, ToastMessage

    handler = get_handler()
    # Compatibility: detect the role here if it was not passed in
    if not role_config or content is None:
        role_config, content_detected = handler.detect_role(text)
        content = content_detected if content is None else content

    if not role_config:
        return ("", 0, 0.0)

    reset()  # Reset the stop flag
    task_stop_event = create_stop_callback()
    toast_manager = ToastMessageManager()
    msg_id = None

    try:
        # Create the initial toast
        msg = ToastMessage(
            text="",
            font_family=role_config.toast_font_family,
            font_size=role_config.toast_font_size,
            bg=role_config.toast_bg_color,
            fg=role_config.toast_font_color,
            duration=role_config.toast_duration,
            initial_width=role_config.toast_initial_width,
            initial_height=role_config.toast_initial_height,
            streaming=True,
            window_type='text',
            markdown=True,
            editable=role_config.toast_editable,
            stop_callback=lambda: task_stop_event.set()
        )

        msg_id = toast_manager.add_message(msg)
        toast_window = await toast_manager.wait_for_window(msg_id, timeout=1.0)

        if not toast_window:
            logger.error("Could not create the toast window")
            if msg_id: toast_manager.close_toast(msg_id)
            return ("", 0, 0.0)

        chunks = []
        def stream_toast_chunk(chunk: str):
            chunks.append(chunk)
            toast_manager.update_toast(msg_id, ''.join(chunks))

        # Call the LLM with streaming
        polished_text, token_count, gen_time = await to_thread(
            handler.process, role_config, content, matched_hotwords, stream_toast_chunk, should_stop
        )

        if should_stop():
            toast_manager.close_toast(msg_id)
            return (''.join(chunks) or content, token_count, gen_time)
        else:
            toast_manager.finish_toast(msg_id)
            return (polished_text or content, token_count, gen_time)

    except Exception as e:
        if msg_id: toast_manager.close_toast(msg_id)

        from util.llm.llm_error_handler import handle_llm_error
        role_name = role_config.name or RoleConfig.DEFAULT_ROLE_NAME

        # Output the original text; also show an error when the user needs to fix the settings
        result_text, _ = handle_llm_error(e, content, role_name)
        result_text = TextOutput.strip_punc(result_text)

        from util.llm.llm_output_typing import output_text
        from config_client import ClientConfig as Config
        await output_text(result_text, Config.paste)
        return (result_text, 0, 0.0)
