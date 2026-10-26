"""Independent capture of everything between pressing the shortcut and pressing it again.

Diagnoses lost audio (e.g. a shortcut held for 21 s of which only 6 s was recognised).
The audio callback copies every block here, separately from the path to the speech
engine, so after each recording we can tell where audio went missing:

  - the microphone delivered nothing for a while (Bluetooth/device), or
  - blocks arrived but did not reach recognition (a client bug).

Each recording leaves appdata/captures/<time>.wav (16 kHz mono) and <time>.json:
held time, audio the mic delivered, audio recognition received, delay before the
first block, gaps, overflow flags, and a verdict. The newest _KEEP are kept.
"""
from __future__ import annotations

import json
import threading
import time
import wave
from datetime import datetime
from pathlib import Path

import numpy as np

from util.app_settings import APPDATA
from . import logger

CAPTURE_DIR = APPDATA / 'captures'
_KEEP = 40
_MAX_SECONDS = 600
_GAP = 0.25             # a pause between blocks longer than this counts as a gap (blocks are 50 ms)
_LOSS = 1.0             # seconds of difference that count as lost audio

_lock = threading.Lock()
_current: dict | None = None


def begin(start_time: float, device=None) -> None:
    """The shortcut was pressed: start collecting a fresh capture."""
    global _current
    with _lock:
        _current = {'start': start_time, 'device': device, 'blocks': [], 'times': [], 'overflows': 0,
                    'ended': None, 'recorder_seconds': None, 'rate': None}


def add(block, sample_rate: int, status=None) -> None:
    """From the audio callback: cheap, never raises."""
    with _lock:
        cap = _current
        if cap is None or cap['ended'] is not None:
            return
        if len(cap['times']) * 0.05 > _MAX_SECONDS:
            return
        cap['rate'] = sample_rate
        cap['times'].append(time.time())
        cap['blocks'].append(block.mean(axis=1) if block.ndim > 1 else block.copy())
        if status and getattr(status, 'input_overflow', False):
            cap['overflows'] += 1


def end(cancelled: bool = False) -> None:
    """The shortcut was pressed again (or the press was only a tap)."""
    global _current
    with _lock:
        if _current is None:
            return
        if cancelled:
            _current = None
            return
        _current['ended'] = time.time()
        cap = _current
    # The recorder reports what reached recognition a moment later; write then, or after 3 s anyway.
    threading.Timer(3.0, _write, args=(cap,)).start()


def recorder_finished(seconds: float) -> None:
    """The recorder's count of audio sent to the speech engine for this recording."""
    with _lock:
        cap = _current
        if cap is not None and cap['ended'] is not None and cap['recorder_seconds'] is None:
            cap['recorder_seconds'] = seconds
    if cap is not None:
        _write(cap)


def analyse(cap: dict) -> dict:
    times = cap['times']
    rate = cap['rate'] or 48000
    held = (cap['ended'] or time.time()) - cap['start']
    delivered = sum(len(b) for b in cap['blocks']) / rate
    first = (times[0] - cap['start']) if times else None
    gaps = []
    previous = cap['start']
    for t in times + [cap['ended'] or previous]:
        if t - previous > _GAP:
            gaps.append([round(previous - cap['start'], 2), round(t - previous, 2)])
        previous = t
    recorder = cap['recorder_seconds']
    if held - delivered > _LOSS:
        verdict = 'microphone delivered no audio for part of the recording (device/Bluetooth)'
    elif recorder is not None and delivered - recorder > _LOSS:
        verdict = 'audio arrived but did not reach recognition (client bug); the full audio is in this capture'
    else:
        verdict = 'ok'
    return {'held': round(held, 2), 'delivered': round(delivered, 2),
            'recognised': None if recorder is None else round(recorder, 2),
            'first_audio_after': None if first is None else round(first, 2), 'gaps': gaps,
            'overflows': cap['overflows'], 'device': cap['device'], 'verdict': verdict}


def _write(cap: dict) -> None:
    with _lock:
        if cap.get('written'):
            return
        cap['written'] = True
    try:
        report = analyse(cap)
        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        stem = datetime.fromtimestamp(cap['start']).strftime('%Y%m%d-%H%M%S')
        if cap['blocks']:
            audio = np.concatenate(cap['blocks'])
            step = max(1, int((cap['rate'] or 48000) // 16000))
            pcm = (np.clip(audio[::step], -1, 1) * 32767).astype('<i2')
            with wave.open(str(CAPTURE_DIR / f'{stem}.wav'), 'wb') as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate((cap['rate'] or 48000) // step)
                out.writeframes(pcm.tobytes())
        (CAPTURE_DIR / f'{stem}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        if report['verdict'] != 'ok':
            logger.warning(f"Audio lost: held {report['held']}s, mic delivered {report['delivered']}s, "
                           f"recognizer received {report['recognised']}s, first audio after {report['first_audio_after']}s: {report['verdict']}")
            _notify(report)
        _prune()
    except Exception as e:
        logger.warning(f'Capture report failed: {e}')


def _notify(report: dict) -> None:
    try:
        from util.client.ui import toast
        lost = round(report['held'] - (report['recognised'] or report['delivered']), 1)
        toast(f'About {lost}s of what you said was not captured.\nDetails saved in appdata/captures for analysis.',
              font_size=12, bg='#8a4b14', duration=5000)
    except Exception:
        pass


def _prune() -> None:
    stems = sorted({p.stem for p in CAPTURE_DIR.glob('*.json')})
    for stem in stems[:-_KEEP]:
        for path in CAPTURE_DIR.glob(f'{stem}.*'):
            try:
                path.unlink()
            except OSError:
                pass
