# coding: utf-8
"""
Recognition results

ResultProcessor handles the results the speech server sends back.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import TYPE_CHECKING, Optional

from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from config_client import ClientConfig as Config
from util.client.state import console
from util.client.websocket_manager import WebSocketManager
from util.hotword import get_hotword_manager
from util.client.output.text_output import TextOutput
from util.client.output import joiner
from util.tools.window_detector import get_active_window_info
from . import logger
from util.common.lifecycle import lifecycle
from util.client.state import get_state
from util.client.diary.archive import save_recognition, save_output, save_details

if TYPE_CHECKING:
    from util.client.state import ClientState



def _estimate_tokens(text: str) -> int:
    """Rough token count of a text."""
    return int(len(text) / 4) if text else 0


class ResultProcessor:
    """
    Result processor

    Handles the results the speech server sends back:
    - receives WebSocket messages
    - applies dictionary replacements
    - optionally polishes the text with AI
    - types the final text
    - saves the recording and the diary
    """

    def __init__(self, state: 'ClientState'):
        """
        Args:
            state: the client state
        """
        self.state = state
        self._ws_manager = WebSocketManager(state)
        self._hotword_manager = get_hotword_manager()
        self._delivered = False      # whether the dictation being processed has reached the user
        self._text_output = TextOutput()
        self._exit_event = asyncio.Event()
        self._loop = asyncio.get_running_loop()  # keep the event loop for thread-safe calls

    def request_exit(self):
        """Ask the processing loop to stop (thread-safe)."""
        logger.info("Exit requested; setting the exit event")

        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._exit_event.set)
            logger.debug("Exit event set via call_soon_threadsafe")
        else:
            self._exit_event.set()
            logger.debug("Exit event set directly")

    def _format_llm_result(self, llm_result) -> str:
        """Format the AI polish result for the console."""
        polished_text = llm_result.result
        role_name = llm_result.role_name
        processed = llm_result.processed
        token_count = llm_result.token_count
        generation_time = llm_result.generation_time  # measured from the first token

        polished_text = polished_text.replace('\n', ' ').replace('\r', ' ')
        max_display_length = 50
        if len(polished_text) > max_display_length:
            polished_text = polished_text[:max_display_length] + '...'

        role_label = f'[{role_name}]' if role_name else ''
        result_text = f'[green]{polished_text}[/green]' if processed else polished_text

        if token_count == 0 and polished_text:
            token_count = _estimate_tokens(polished_text)

        # Speed from the generation time (more accurate)
        if processed and generation_time > 0:
            speed = token_count / generation_time if token_count > 0 else 0
            speed_label = f'    {speed:.1f} tokens/s' if speed > 0 else ''
        else:
            speed_label = ''

        return f'    Model result{role_label}: {result_text}{speed_label}'

    def _log_modifier_key_state(self) -> None:
        """
        Log every key currently held down

        Helps debug stuck keys.
        """
        try:
            import keyboard

            pressed_keys = keyboard._pressed_events
            key_names = list(pressed_keys.keys())
            logger.debug(f"Keys held down: {key_names}")

        except Exception as e:
            logger.debug(f"Checking key state failed: {e}")

    async def process_loop(self) -> None:
        """Main processing loop."""
        if not await self._ws_manager.connect():
            logger.warning("WebSocket connection check failed")
            return

        console.print('[green]Connected\n')
        logger.info("WebSocket connected")

        try:
            while True:
                if self._exit_event.is_set():
                    logger.info("Exit event seen; stopping the processing loop")
                    break

                # One task receives a message, the other waits for the exit event
                recv_task = asyncio.create_task(self.state.websocket.recv())
                logger.debug("Receive task created")

                exit_wait_task = asyncio.create_task(self._exit_event.wait())
                logger.debug("Exit wait task created")

                done, pending = await asyncio.wait(
                    [recv_task, exit_wait_task],
                    return_when=asyncio.FIRST_COMPLETED
                )
                logger.debug(f"Tasks finished: done={len(done)}, pending={len(pending)}")

                for task in pending:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass

                if exit_wait_task in done:
                    logger.info("Exit requested; stopping the processing loop")
                    if recv_task not in done and not recv_task.done():
                        recv_task.cancel()
                        try:
                            await recv_task
                        except asyncio.CancelledError:
                            pass
                    break

                if recv_task in done:
                    try:
                        message = recv_task.result()
                    except ConnectionClosedError:
                        logger.warning("WebSocket connection closed")
                        break
                    if lifecycle.is_shutting_down:
                        logger.info("Exit requested before the message was handled")
                        break
                    try:
                        logger.debug("Handling message")
                        await self._handle_message(message)
                        logger.debug("Message handled")
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        # One dictation failing must not drop the connection: this used to raise,
                        # and the next recording was lost too ("server not connected")
                        logger.error(f"Error handling message: {e}", exc_info=True)

        except ConnectionClosedError:
            console.print('[red]Disconnected\n')
            logger.error("WebSocket disconnected")
        except ConnectionClosedOK:
            console.print('[yellow]Connection closed\n')
            logger.info("WebSocket connection closed normally")
        except asyncio.CancelledError:
            logger.info("Processing loop cancelled")
            raise
        except Exception as e:
            logger.error(f"Error receiving results: {e}", exc_info=True)
            print(e)
        finally:
            self._cleanup()

    async def _handle_message(self, message: str) -> None:
        """Handle one message from the server."""
        import json

        if lifecycle.is_shutting_down:
            return

        message = json.loads(message)
        self._archive(save_recognition, message)

        # The text field: the joined result used for dictation
        text = message['text']
        original_text = text
        delay = message['time_complete'] - message['time_submit']

        if message['is_final']:
            logger.info(f"Final result: {text}, delay: {delay:.2f}s")
        else:
            logger.debug(
                f"Partial result: {text[:50]}{'...' if len(text) > 50 else ''}, "
                f"delay: {delay:.2f}s"
            )

        if not message['is_final']:
            return

        self._delivered = False
        try:
            await self._process_final(message, text, original_text, delay)
        except Exception as e:
            logger.error(f"Error handling the final result: {e}", exc_info=True)
            if not self._delivered and (text or '').strip():
                # Not typed yet: clipboard and notice, as when there is nowhere to type; the archive has the text
                self._keep_unsent(TextOutput.strip_punc(text), 'something went wrong before it was typed')
        finally:
            # Whatever happened (typed, empty result, error), hide the "processing" pill
            self._hide_status()
            try:
                from util.client.learn.reviewer import get_reviewer
                get_reviewer().nudge()      # the AI reviewer looks at new dictations once idle
            except Exception as e:
                logger.debug(f"Notifying the AI reviewer failed: {e}")

    @staticmethod
    def _hide_status() -> None:
        """Hide the status pill, unless the next recording has already started."""
        try:
            if not get_state().recording:
                from util.client.ui import hide_recording_status
                hide_recording_status()
        except Exception as e:
            logger.debug(f"Hiding the status pill failed: {e}")

    async def _process_final(self, message, text, original_text, delay) -> None:
        """Handle a final result: correct it, type it, save it."""
        # 1. Phoneme search and dictionary replacement
        fixes = []
        correction_result = self._hotword_manager.get_phoneme_corrector().correct(text, k=10)
        if Config.hot:
            text = correction_result.text
            fixes += [{'kind': 'dictionary', 'from': origin, 'to': hw}
                      for origin, hw, score in correction_result.matchs]

        # 2. Strip trailing punctuation
        text = TextOutput.strip_punc(text)

        # 3. Regular-expression rules
        if getattr(Config, 'hot_rule', True):
            text, rule_log = self._hotword_manager.get_rule_corrector().substitute_with_log(text)
            fixes += [{'kind': 'rule', 'from': old, 'to': new} for old, new in rule_log]

        self.state.last_recognition_text = text
        self._archive(save_output, message, text)

        console.print(f'    Recognition delay: {delay:.2f}s')

        # The raw recognition result first
        original_text_stripped = TextOutput.strip_punc(original_text)
        console.print(f'    Recognised: [green]{original_text_stripped}')

        # Then the text after dictionary replacement, if it changed
        if original_text_stripped != text:
            console.print(f'    Dictionary: [cyan]{text}')
            logger.debug(f"After dictionary replacement: {text[:50]}{'...' if len(text) > 50 else ''}")

        matched_hotwords = correction_result.matchs
        potential_hotwords = correction_result.similars

        # 1. Dictionary words that matched and were replaced
        if matched_hotwords and Config.hot:
            # (heard, dictionary word, score)
            replaced_info = [f"{origin}->[green4]{hw}[/]" for origin, hw, score in matched_hotwords]
            console.print(f'    Matched: {", ".join(replaced_info)}')

        # 2. Possible dictionary words (excluding those already replaced)
        if potential_hotwords and Config.hot:
            replaced_set = {hw for origin, hw, score in matched_hotwords}
            potential_matches = [(origin, hw, score) for origin, hw, score in potential_hotwords if hw not in replaced_set]

            if potential_matches:
                potential_str = ", ".join([f"{origin}->{hw}({score:.2f})" for origin, hw, score in potential_matches[:5]])
                if len(potential_matches) > 5:
                    potential_str += f" ... ({len(potential_matches)} in all)"
                console.print(f'    Possible: [yellow]{potential_str}')

        paste = Config.paste
        window_info = get_active_window_info()
        from util.client.output import focus
        focus.remember(window_info)

        # Nowhere to type (a menu, button or the desktop has focus): save it in Utter instead
        delivery = 'typed'
        typeable, reason = (True, '')
        if text:
            from util.client.output.target import check as check_target
            typeable, reason = check_target()

        # The cursor is still right after the last dictation: add a full stop and capitalise
        window = joiner.window_key(window_info)
        sep = ''
        if typeable and text:
            sep, text = joiner.prepare(window, text)
            if sep:
                logger.debug(f"Continuing the last dictation, separator: {sep!r}")

        # AI polish and output (short text skips AI polish)
        llm_result = None
        if not typeable:
            delivery = 'saved'
            self._keep_unsent(text, reason)
        elif Config.llm_enabled and len(text) >= Config.llm_min_chars:
            from util.llm.llm_process_text import llm_process_text
            logger.info(f"Text length {len(text)} >= {Config.llm_min_chars}; running AI polish")
            thinking_started_at = time.monotonic()
            try:
                from util.client.ui import show_thinking_status
                show_thinking_status()
            except Exception as e:
                logger.debug(f"Showing the thinking pill failed: {e}")
            try:
                llm_result = await llm_process_text(
                    text,
                    paste=paste,
                    matched_hotwords=potential_hotwords,  # possible dictionary words as context
                    prefix=sep,
                )
            finally:
                try:
                    min_seconds = getattr(Config, 'thinking_status_min_seconds', 0.8)
                    elapsed = time.monotonic() - thinking_started_at
                    if min_seconds > elapsed:
                        await asyncio.sleep(min_seconds - elapsed)
                    self._hide_status()
                except Exception as e:
                    logger.debug(f"Hiding the thinking pill failed: {e}")
        else:
            if Config.llm_enabled:
                logger.debug(f"Text length {len(text)} < {Config.llm_min_chars}; skipping AI polish")
            await self._text_output.output(sep + text, paste=paste)
            get_state().set_output_text(text)
        self._delivered = True       # typed, polished and typed, or kept on the clipboard; later steps only record

        if llm_result and llm_result.processed:
            from util.text_metrics import changed_words
            edited = changed_words(text, llm_result.result)
            if edited:
                fixes.append({'kind': 'ai', 'words': edited})
        self._save_details(message, window_info, fixes, delivery)

        # Learning: watch what the person changes in this text next
        if typeable:
            typed = llm_result.result if llm_result and llm_result.processed else text
            joiner.remember(window, typed)
            try:
                from util.client.learn.edit_watcher import get_edit_watcher
                get_edit_watcher().observe(typed, (window_info or {}).get('process_name', ''))
            except Exception as e:
                logger.debug(f"Starting the edit watcher failed: {e}")

        # Save the recording and the diary
        file_audio = None
        if Config.save_audio:
            from util.client.diary.diary_writer import DiaryWriter

            # Rename the audio file after its text
            file_path = self.state.pop_audio_file(message['task_id'])
            if file_path:
                from util.client.audio.file_manager import AudioFileManager
                file_manager = AudioFileManager()
                file_manager.file_path = file_path
                file_audio = file_manager.rename(text, message['time_start'])
                logger.debug(f"Recording saved: {file_audio}")

            diary_writer = DiaryWriter()
            diary_writer.write(text, message['time_start'], file_audio)
            self._archive(save_output, message, llm_result.result if llm_result and llm_result.processed else text, file_audio)
            logger.debug("Diary written")

        # Show and save the AI polish result
        if Config.llm_enabled and llm_result and llm_result.processed:
            console.print(self._format_llm_result(llm_result))
            from util.llm.llm_write_md import write_llm_md
            write_llm_md(
                llm_result.input_text,
                llm_result.result,
                llm_result.role_name,
                message['time_start'],
                file_audio
            )
            logger.debug("AI polish diary written")

        # Key state (for debugging)
        self._log_modifier_key_state()

        console.line()

    @staticmethod
    def _archive(save, message, *args) -> None:
        """Write to the dictation archive; a failure (another program holding the database: "database
        is locked") is logged and the text is typed anyway. Once, an archive error kept a whole
        dictation from being typed and dropped the server connection."""
        try:
            save(message, *args)
        except Exception as e:
            logger.warning(f"Archive write failed; typing anyway ({message.get('task_id')}): {e} - {message.get('text', '')[:200]}")

    @staticmethod
    def _save_details(message, window_info, fixes, delivery='typed') -> None:
        """Record the target app, the fixes and whether it was typed (for Insights); never blocks output."""
        try:
            save_details(message, window_info, fixes, delivery)
        except Exception as e:
            logger.warning(f"Saving dictation details failed: {e}")

    @staticmethod
    def _keep_unsent(text: str, reason: str) -> None:
        """Nowhere to type: put it on the clipboard and say it was saved in Utter."""
        get_state().set_output_text(text)
        try:
            # Always, even with "keep the result on the clipboard" off: nothing was typed, so this is the copy
            from util.client.clipboard import safe_copy
            safe_copy(text)
        except Exception as e:
            logger.debug(f"Copying to the clipboard failed: {e}")
        console.print(f'    Not typed: [yellow]{reason}[/], saved in Utter')
        logger.info(f"No place to type ({reason}); saved without typing")
        try:
            from util.client.ui import toast
            toast(f'Not typed: {reason}.\nSaved in Utter and copied to your clipboard.',
                  font_size=12, bg='#1f5f57', duration=4500)
        except Exception as e:
            logger.debug(f"Showing the not-typed toast failed: {e}")

    def _cleanup(self) -> None:
        """Release resources."""
        if self.state.websocket is not None:
            try:
                if self.state.websocket.closed:
                    self.state.websocket = None
                    logger.debug("WebSocket connection cleared")
            except Exception:
                self.state.websocket = None
