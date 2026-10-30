"""Start/stop sounds and muting other apps while dictating.

Runs on one worker thread so the keyboard hook never waits on COM or audio.
"""
from __future__ import annotations

import io
import json
import os
import queue
import threading
import time
import wave

import numpy as np

from config_client import ClientConfig as Config
from util.app_settings import APPDATA
from . import logger

MUTED_PATH = APPDATA / 'muted.json'
_SAMPLE_RATE = 44100


def _tone(freqs, step=0.07, volume=0.22):
    """Short tone sequence as in-memory WAV bytes, with fades to avoid clicks."""
    parts = []
    for freq in freqs:
        t = np.arange(int(_SAMPLE_RATE * step)) / _SAMPLE_RATE
        wave_data = np.sin(2 * np.pi * freq * t)
        fade = np.minimum(1, np.minimum(t, step - t) / 0.012)
        parts.append(wave_data * fade)
    samples = (np.concatenate(parts) * volume * 32767).astype('<i2')
    buffer = io.BytesIO()
    with wave.open(buffer, 'wb') as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(_SAMPLE_RATE)
        out.writeframes(samples.tobytes())
    return buffer.getvalue()


START_SOUND = _tone([660, 880])
STOP_SOUND = _tone([880, 660])


def _play(sound):
    try:
        import winsound
        winsound.PlaySound(sound, winsound.SND_MEMORY)
    except Exception as e:
        logger.debug(f'Dictation sound failed: {e}')


# Apps that play music or video ("Only music and video apps"): players, streaming apps, browsers.
MEDIA_PROCESSES = {
    'spotify.exe', 'applemusic.exe', 'itunes.exe', 'tidal.exe', 'deezer.exe', 'amazon music.exe',
    'vlc.exe', 'wmplayer.exe', 'microsoft.media.player.exe', 'video.ui.exe', 'music.ui.exe',
    'foobar2000.exe', 'aimp.exe', 'musicbee.exe', 'potplayermini64.exe', 'mpc-hc64.exe', 'mpv.exe',
    'chrome.exe', 'msedge.exe', 'firefox.exe', 'brave.exe', 'opera.exe', 'vivaldi.exe', 'arc.exe',
}
LOWERED_LEVEL = 0.2   # "Lower volume" keeps music at 20% of its own level


def _session_name(session):
    try:
        return (session.Process.name() if session.Process else '').lower()
    except Exception:
        return ''


class _Muter:
    """Quiets other apps' audio (mute, or lower to 20%) and restores only what it changed."""

    def __init__(self):
        self._changed = []   # (pid, volume control, 'mute' or previous level)
        self._no_output_noted = False

    def mute(self, mode='mute', media_only=False):
        from pycaw.pycaw import AudioUtilities
        own = os.getpid()
        try:
            sessions = AudioUtilities.GetAllSessions()
        except Exception as e:
            # "Element not found" (0x80070490): Windows has no default speakers right now (headset
            # just disconnected, or only a microphone is plugged in), so there is nothing to quiet.
            if not self._no_output_noted:
                logger.info(f'Nothing to quiet while dictating: no speakers are active ({e})')
                self._no_output_noted = True
            return
        self._no_output_noted = False
        for session in sessions:
            try:
                if session.ProcessId in (0, own):
                    continue
                if media_only and _session_name(session) not in MEDIA_PROCESSES:
                    continue
                volume = session.SimpleAudioVolume
                if volume.GetMute():
                    continue
                if mode == 'lower':
                    level = volume.GetMasterVolume()
                    volume.SetMasterVolume(level * LOWERED_LEVEL, None)
                    self._changed.append((session.ProcessId, volume, level))
                else:
                    volume.SetMute(1, None)
                    self._changed.append((session.ProcessId, volume, 'mute'))
            except Exception as e:
                logger.debug(f'Quiet session failed: {e}')
        self._remember()

    def restore(self):
        for _, volume, before in self._changed:
            try:
                if before == 'mute':
                    volume.SetMute(0, None)
                else:
                    volume.SetMasterVolume(before, None)
            except Exception as e:
                logger.debug(f'Restore session failed: {e}')
        self._changed = []
        self._remember()

    def _remember(self):
        # Lets the next client start restore apps if this process dies while they are quiet.
        try:
            if self._changed:
                MUTED_PATH.parent.mkdir(parents=True, exist_ok=True)
                MUTED_PATH.write_text(json.dumps({str(pid): before for pid, _, before in self._changed}),
                                      encoding='utf-8')
            elif MUTED_PATH.exists():
                MUTED_PATH.unlink()
        except OSError:
            pass

    @staticmethod
    def restore_after_crash():
        try:
            saved = json.loads(MUTED_PATH.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return
        if isinstance(saved, list):                  # older format: a list of muted pids
            saved = {str(pid): 'mute' for pid in saved}
        from pycaw.pycaw import AudioUtilities
        for session in AudioUtilities.GetAllSessions():
            before = saved.get(str(session.ProcessId))
            if before is None:
                continue
            try:
                if before == 'mute':
                    session.SimpleAudioVolume.SetMute(0, None)
                else:
                    session.SimpleAudioVolume.SetMasterVolume(float(before), None)
            except Exception:
                pass
        try:
            MUTED_PATH.unlink()
        except OSError:
            pass


class DictationFeedback:
    def __init__(self):
        self._queue: 'queue.Queue[tuple]' = queue.Queue()
        self._thread = threading.Thread(target=self._run, name='dictation-feedback', daemon=True)
        self._thread.start()

    def started(self, start_time: float, confirm_after: float) -> None:
        self._queue.put(('start', start_time, confirm_after))

    def stopped(self) -> None:
        self._queue.put(('stop',))

    def cancelled(self) -> None:
        self._queue.put(('cancel',))

    def shutdown(self) -> None:
        self._queue.put(('shutdown',))
        self._thread.join(timeout=2)

    def _run(self):
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception as e:
            logger.debug(f'COM init for feedback failed: {e}')
        muter = _Muter()
        try:
            muter.restore_after_crash()
        except Exception as e:
            logger.debug(f'Restore muted apps failed: {e}')

        confirmed = False
        while True:
            event = self._queue.get()
            kind = event[0]
            try:
                if kind == 'start':
                    _, start_time, confirm_after = event
                    # A tap shorter than the threshold is a normal key press, not dictation.
                    delay = start_time + confirm_after + 0.05 - time.time()
                    if delay > 0:
                        time.sleep(delay)
                    from util.client.state import get_state
                    state = get_state()
                    confirmed = state.recording and state.recording_start_time == start_time
                    if confirmed:
                        if getattr(Config, 'dictation_sounds', False):
                            _play(START_SOUND)
                        if getattr(Config, 'mute_while_dictating', False):
                            muter.mute(getattr(Config, 'quiet_mode', 'mute'),
                                       getattr(Config, 'quiet_media_only', False))
                elif kind in ('stop', 'cancel', 'shutdown'):
                    muter.restore()
                    if kind == 'stop' and confirmed and getattr(Config, 'dictation_sounds', False):
                        _play(STOP_SOUND)
                    confirmed = False
                    if kind == 'shutdown':
                        return
            except Exception as e:
                logger.warning(f'Dictation feedback error: {e}')


_feedback = None


def get_feedback() -> DictationFeedback:
    global _feedback
    if _feedback is None:
        _feedback = DictationFeedback()
    return _feedback
