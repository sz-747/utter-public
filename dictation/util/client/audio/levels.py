"""Live microphone levels for the status pill: how loud, and where in pitch.

The audio callback calls update() with each 50 ms block while recording.
The pill reads get(): one value per frequency band (low to high), 0..1.
Loudness sets the height, so silence shows flat bars. The spectrum only
decides which bars rise: bands are scaled together against the block's
strongest band (not each to itself, which would flatten every band to full
height and lose the pitch), so a low voice lifts the low bands and a higher
pitch shifts the energy outward.

Loudness is judged against the speaker's own recent level, not a fixed
"loud" value: a headset mic often puts normal speech around -38 dBFS, so a
fixed scale left the bars small unless the speaker shouted. Speaking a bit
louder, or a bit higher than usual, now visibly lifts the bars.
"""
import threading
import time

import numpy as np

BANDS = 5
_EDGES = np.geomspace(90, 4000, BANDS + 1)      # voice range, low to high
_SILENT_DB = -55.0                             # dBFS treated as silence (bars flat)
_REF_START_DB = -32.0                          # first guess of the speaker's loud level
_REF_MIN_DB = -42.0                            # never treat quieter than this as "loud"
_REF_DECAY_DB = 2.0                            # per second: the loud level eases down after a raised word
_CONTRAST = 2.6                                # >1 widens the gap between normal and raised speech
_PITCH_RANGE = (70.0, 400.0)                   # Hz searched for the voice's pitch
_PITCH_OCTAVES = 0.6                           # this far above the usual pitch = full lift
_PITCH_LIFT = 0.45                             # how much a raised pitch adds to the height

_STALL_SECONDS = 0.3                           # blocks arrive every 50 ms; this long without one = mic stalled

_lock = threading.Lock()
_levels = np.zeros(BANDS)
_last_block = None                         # time of the last block from the microphone
_since = time.monotonic()                      # when this recording started
# The speaker's voice is kept across recordings so the first words already scale well.
_ref_db = _REF_START_DB                        # recent loud level
_usual_pitch = None                            # log2 Hz, slowly averaged over voiced blocks


def reset(voice: bool = False):
    """Start a new recording; voice=True also forgets the speaker's usual loudness and pitch."""
    global _levels, _last_block, _since, _ref_db, _usual_pitch
    with _lock:
        if voice:
            _ref_db, _usual_pitch = _REF_START_DB, None
        _levels = np.zeros(BANDS)
        _last_block = None
        _since = time.monotonic()


def stalled(threshold: float = _STALL_SECONDS) -> bool:
    """True when the microphone has sent nothing for a while (e.g. a Bluetooth dropout),
    including a slow start right after the shortcut is pressed."""
    with _lock:
        reference = _last_block if _last_block is not None else _since
    return time.monotonic() - reference > threshold


def _pitch(windowed, sample_rate):
    """The voice's pitch in Hz, or None when the block is not voiced (autocorrelation peak)."""
    power = np.abs(np.fft.rfft(windowed, 2 * len(windowed))) ** 2
    corr = np.fft.irfft(power)[:len(windowed)]
    lo, hi = int(sample_rate / _PITCH_RANGE[1]), int(sample_rate / _PITCH_RANGE[0])
    if hi >= len(corr) or corr[0] <= 0:
        return None
    lag = lo + int(np.argmax(corr[lo:hi]))
    return sample_rate / lag if corr[lag] > 0.3 * corr[0] else None


def update(block, sample_rate):
    global _levels, _last_block, _ref_db, _usual_pitch
    with _lock:
        _last_block = time.monotonic()
    mono = block.mean(axis=1) if block.ndim > 1 else block
    if not len(mono):
        return
    seconds = len(mono) / sample_rate
    db = 20 * np.log10(float(np.sqrt(np.mean(mono ** 2))) + 1e-12)
    windowed = mono * np.hanning(len(mono))
    pitch = _pitch(windowed, sample_rate) if db > _SILENT_DB + 10 else None

    spectrum = np.abs(np.fft.rfft(windowed))
    freqs = np.fft.rfftfreq(len(mono), 1 / sample_rate)
    # Strongest frequency in each band: a band's mean would dilute the wide high bands,
    # so a higher pitch would barely register.
    energy = np.array([spectrum[(freqs >= lo) & (freqs < hi)].max() if np.any((freqs >= lo) & (freqs < hi)) else 0.0
                       for lo, hi in zip(_EDGES[:-1], _EDGES[1:])])
    with _lock:
        # Loud level jumps up to a raised word, then eases back down to the speaker's normal.
        _ref_db = max(db, _ref_db - _REF_DECAY_DB * seconds, _REF_MIN_DB)
        loudness = np.clip((db - _SILENT_DB) / (_ref_db - _SILENT_DB), 0, 1) ** _CONTRAST

        lift = 0.0
        if pitch is not None:
            octave = float(np.log2(pitch))
            if _usual_pitch is None:
                _usual_pitch = octave
            lift = float(np.clip((octave - _usual_pitch) / _PITCH_OCTAVES, 0, 1))
            _usual_pitch += (octave - _usual_pitch) * min(1.0, seconds / 4)   # ~4 s memory
        loudness = min(1.0, loudness + _PITCH_LIFT * lift * (loudness > 0.05))

        shape = (energy / max(float(energy.max()), 1e-12)) ** 0.6
        _levels = np.clip(shape * loudness, 0, 1)


def get():
    with _lock:
        return _levels.copy()
