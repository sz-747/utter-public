"""
LLM typing output mode

Types the output directly, chosen by the paste argument or Config.paste:
- paste=True: wait for the stream to finish, then paste it all at once
- paste=False: stream with write, typing each character as it arrives
"""
import asyncio
import keyboard

from config_client import ClientConfig as Config
from util.tools.asyncio_to_thread import to_thread
from util.client.output.text_output import TextOutput
from util.client.clipboard import paste_text, keep_output_clipboard
from util.client.output.focus import before_typing
from util.llm.llm_stop_monitor import reset, should_stop
from util.llm.llm_cleanup_guard import (
    is_default_cleanup_role,
    validate_cleanup_output,
)
from . import logger


async def handle_typing_mode(text: str, paste: bool = None, matched_hotwords=None, role_config=None, content=None,
                             prefix: str = '') -> tuple:
    """Typing output mode; prefix is only used by the default cleanup (separator when continuing the previous dictation) and is not part of the result"""
    from util.llm.llm_handler import get_handler
    from util.llm.llm_error_handler import handle_llm_error

    handler = get_handler()
    # Not passed in: detect it here (compatibility)
    if not role_config or content is None:
        role_config, content = handler.detect_role(text)

    if not role_config:
        # Should not happen, but just in case
        result_text = TextOutput.strip_punc(text)
        await output_text(result_text, paste)
        return (result_text, 0, 0.0)

    reset()  # Reset the stop flag
    if not is_default_cleanup_role(role_config):
        prefix = ''

    try:
        # The default role is the automatic transcript cleanup: buffer and check the whole text first,
        # so a model that strays into answering never types text that cannot be taken back into the
        # current window. Named roles keep the original streaming behavior.
        if is_default_cleanup_role(role_config):
            return await _process_buffered_cleanup(
                handler, role_config, content, matched_hotwords, paste, prefix
            )
        if paste:
            return await _process_paste(handler, role_config, content, matched_hotwords)
        else:
            return await _process_streaming(handler, role_config, content, matched_hotwords)

    except Exception as e:
        result_text, _ = handle_llm_error(e, content, role_config.name if role_config else "LLM")
        result_text = TextOutput.strip_punc(result_text)
        await output_text(prefix + result_text, paste)
        return (result_text, 0, 0.0)


async def _process_buffered_cleanup(
    handler, role_config, content, matched_hotwords, paste, prefix=''
) -> tuple:
    """Generate and check the whole default cleanup; only output it once it passes."""
    polished_text, token_count, gen_time = await to_thread(
        handler.process, role_config, content, matched_hotwords, None, should_stop
    )
    if should_stop():
        return ("", 0, 0.0)

    validation = validate_cleanup_output(content, polished_text)
    if not validation.accepted:
        logger.warning(f"Default cleanup fell back to the original text: {validation.reason}")

    final_text = TextOutput.strip_punc(validation.text)
    await output_text(prefix + final_text, paste)
    return (final_text, token_count if validation.accepted else 0, gen_time)


async def _process_paste(handler, role_config, content, matched_hotwords) -> tuple:
    """Paste mode: get the full text, then paste it all at once"""
    polished_text, token_count, gen_time = await to_thread(
        handler.process, role_config, content, matched_hotwords, None, should_stop
    )
    if should_stop():
        return ("", 0, 0.0)

    final_text = TextOutput.strip_punc(polished_text or content)
    before_typing()
    await paste_text(final_text, restore_clipboard=Config.restore_clip)
    return (final_text, token_count, gen_time)


async def _process_streaming(handler, role_config, content, matched_hotwords) -> tuple:
    """Streaming typing mode: simulate key presses while the text is generated"""
    chunks = []
    pending_buffer = ""

    def stream_write_chunk(chunk: str):
        nonlocal pending_buffer
        if not chunk: return
        if not chunks:
            before_typing()
        chunks.append(chunk)

        full_current = pending_buffer + chunk
        content_to_write = full_current
        trailing = ""

        # Find the last character that is not trailing junk, scanning from the right
        for i in range(len(full_current) - 1, -1, -1):
            char = full_current[i]
            if char == '\n' or char in Config.trash_punc:
                continue
            else:
                content_to_write = full_current[:i+1]
                trailing = full_current[i+1:]
                break
        else:
            content_to_write = ""
            trailing = full_current

        if content_to_write:
            logger.debug(f"output_text: keyboard.write '{content_to_write}'")
            keyboard.write(content_to_write)
            pending_buffer = trailing
        else:
            pending_buffer = trailing

    # Run the streaming request
    polished_text, token_count, gen_time = await to_thread(
        handler.process, role_config, content, matched_hotwords, stream_write_chunk, should_stop
    )

    # Blocks until it finishes normally or the user presses Esc
    if should_stop():
        final_text = TextOutput.strip_punc(''.join(chunks) or content)
        return (final_text, 0, 0.0)

    # The model output nothing: type the original text
    if not chunks:
        final_text = TextOutput.strip_punc(content)
        logger.debug(f"output_text: keyboard.write '{final_text}' (fallback)")
        keyboard.write(final_text)
        return (final_text, 0, 0.0)

    # If the LLM output only a punctuation mark it was held back, so type it now
    full_output = ''.join(chunks).strip()
    if len(full_output) == 1 and full_output in Config.trash_punc:
        keyboard.write(full_output)

    final_text = TextOutput.strip_punc(polished_text)
    keep_output_clipboard(final_text)
    return (final_text, token_count, gen_time)


async def output_text(text: str, paste: bool = None):
    """Output text (paste or type, by paste or Config.paste)"""
    before_typing()
    if paste:
        await paste_text(text, restore_clipboard=Config.restore_clip)
    else:
        logger.debug(f"output_text: keyboard.write '{text}'")
        keep_output_clipboard(text)
        keyboard.write(text)
