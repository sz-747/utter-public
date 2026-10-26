"""Live client status for the desktop app (appdata/status.json) and live settings.

The client writes a snapshot every few seconds and right after each state
change; the app treats a stale snapshot as "not running". Settings written by
the app are applied to ClientConfig as soon as the file changes.
"""
from __future__ import annotations

import os
import threading
import time

from config_client import ClientConfig as Config, __version__
from util import app_settings
from . import logger

_HEARTBEAT = 3.0


class RuntimeStatus:
    def __init__(self):
        self._started_at = time.time()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = None
        self._settings_mtime = None
        self._settings = {}

    # -- settings -------------------------------------------------------

    def apply_settings_at_startup(self) -> None:
        self._settings = app_settings.load()
        changed = app_settings.apply_to_config(Config, self._settings)
        self._settings_mtime = self._mtime()
        if changed:
            logger.info(f'Applied desktop app settings: {", ".join(changed)}')

    def _mtime(self):
        try:
            return app_settings.SETTINGS_PATH.stat().st_mtime
        except OSError:
            return None

    def _check_settings(self) -> bool:
        mtime = self._mtime()
        if mtime == self._settings_mtime:
            return False
        self._settings_mtime = mtime
        new = app_settings.load()
        # Only keys the app changed are applied, so a runtime toggle such as the
        # double-tap LLM switch is not overwritten by an unrelated settings save.
        diff = {k: v for k, v in new.items() if self._settings.get(k) != v}
        self._settings = new
        changed = app_settings.apply_to_config(Config, diff)
        if changed:
            logger.info(f'Desktop app changed settings: {", ".join(changed)}')
            if 'shortcuts' in changed:
                logger.info('Shortcut changes take effect after the client restarts.')
        return bool(changed)

    # -- status ---------------------------------------------------------

    def snapshot(self, stopped: bool = False) -> dict:
        from util.client.state import get_state
        state = get_state()
        manager = getattr(state, 'stream_manager', None)
        device = getattr(manager, 'selected_device', None) if manager else None
        dictionary_words = rules = None
        try:
            from util.hotword import get_hotword_manager
            hotwords = get_hotword_manager()
            dictionary_words = len(hotwords.phoneme_corrector.hotwords)
            rules = len(hotwords.rule_corrector.patterns)
        except Exception:
            pass
        return {
            'pid': os.getpid(),
            'version': __version__,
            'started_at': self._started_at,
            'updated_at': time.time(),
            'stopped': stopped,
            'connected': bool(state.is_connected),
            'recording': bool(state.recording),
            'microphone': {'name': device[0], 'api': device[1]} if device else None,
            'microphones': getattr(manager, 'available_devices', []) if manager else [],
            'audio_input_device': getattr(Config, 'audio_input_device', None),
            'server': f'{Config.addr}:{Config.port}',
            'llm_enabled': bool(Config.llm_enabled),
            'llm_min_chars': Config.llm_min_chars,
            'hot': bool(Config.hot),
            'hot_rule': bool(getattr(Config, 'hot_rule', True)),
            'auto_learn': bool(getattr(Config, 'auto_learn', False)),
            'dictation_sounds': bool(getattr(Config, 'dictation_sounds', False)),
            'mute_while_dictating': bool(getattr(Config, 'mute_while_dictating', False)),
            'quiet_mode': getattr(Config, 'quiet_mode', 'mute'),
            'quiet_media_only': bool(getattr(Config, 'quiet_media_only', False)),
            'paste': bool(Config.paste),
            'save_audio': bool(Config.save_audio),
            'shortcuts': [s for s in Config.shortcuts if s.get('enabled', True)],
            'dictionary_words': dictionary_words,
            'replacement_rules': rules,
            'last_output_at': getattr(state, 'last_output_time', None),
            'auto_review': bool(getattr(Config, 'auto_review', False)),
            'review': self._review_status(),
        }

    @staticmethod
    def _review_status() -> dict:
        try:
            from util.client.learn.reviewer import status
            return dict(status)
        except Exception:
            return {}

    def _write(self, stopped: bool = False) -> None:
        try:
            app_settings.write_json(app_settings.STATUS_PATH, self.snapshot(stopped))
        except Exception as e:
            # The app may be reading the file at this moment; the next tick retries.
            logger.debug(f'Status write skipped: {e}')

    def touch(self) -> None:
        self._wake.set()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, name='runtime-status', daemon=True)
        self._thread.start()

    def _run(self) -> None:
        last_write = 0.0
        while not self._stop.is_set():
            # Settings are polled every second; status is written on change or heartbeat.
            woken = self._wake.wait(1.0)
            self._wake.clear()
            try:
                woken = self._check_settings() or woken
            except Exception as e:
                logger.warning(f'Settings check failed: {e}')
            if woken or time.time() - last_write >= _HEARTBEAT:
                self._write()
                last_write = time.time()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=2)
        self._write(stopped=True)


_status = None


def get_runtime_status() -> RuntimeStatus:
    global _status
    if _status is None:
        _status = RuntimeStatus()
    return _status
