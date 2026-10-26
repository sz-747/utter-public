"""Live meeting transcription: record the microphone and what the PC plays, cut at pauses, transcribe.

Two sources, each its own speaker label:
- 'me': the microphone (the one dictation uses, when it can be found).
- 'others': WASAPI loopback of the default speakers or headphones, so
  everyone on the call is heard without a bot joining it.

Each source is cut into utterances at pauses (Segmenter) and each utterance is
sent to the speech server as one finished task, the same websocket
protocol its dictation client uses. Audio is never written to disk.
"""
from __future__ import annotations

import base64
import json
import queue
import threading
import time
import uuid

import numpy as np

RATE = 16000                 # what the speech server expects: float32, 16 kHz, mono
FRAME = 480                  # 30 ms analysis frames
QUIET_LEVEL = 0.006          # RMS below this is a pause
SPEECH_LEVEL = 0.015         # an utterance needs some frames this loud, or it is noise
MIN_SPEECH_SECONDS = 0.3
PAUSE_SECONDS = 0.7          # cut after this much quiet ...
MIN_SECONDS = 2.5            # ... once the utterance is at least this long
MAX_SECONDS = 20.0           # and always cut here, to keep the transcript live
_LEVEL_DECAY = 0.85


def to_mono_16k(samples: np.ndarray, channels: int, rate: int) -> np.ndarray:
    """Interleaved float32 at any rate and channel count to mono 16 kHz."""
    samples = np.asarray(samples, dtype=np.float32)
    if channels > 1:
        samples = samples[: len(samples) // channels * channels].reshape(-1, channels).mean(axis=1)
    if rate == RATE or not len(samples):
        return samples
    if rate % RATE == 0:      # 48 kHz: average each group of 3 (a cheap low-pass) and keep one
        step = rate // RATE
        return samples[: len(samples) // step * step].reshape(-1, step).mean(axis=1)
    count = int(len(samples) * RATE / rate)
    return np.interp(np.linspace(0, len(samples) - 1, count), np.arange(len(samples)), samples).astype(np.float32)


class Segmenter:
    """Collects one source's audio and hands back utterances, cut at natural pauses.

    feed() returns the finished utterances as (seconds from start, samples).
    Utterances without speech-level audio are dropped: silence makes speech
    models invent words.
    """

    def __init__(self):
        self._frames: list[np.ndarray] = []
        self._pending = np.zeros(0, dtype=np.float32)
        self._start = 0.0             # stream time of the first buffered frame
        self._clock = 0.0             # stream time of the next sample
        self._quiet = 0               # trailing quiet frames
        self._loud = 0                # speech-level frames in the buffer
        self.level = 0.0              # for the page's meter, 0..1

    def feed(self, samples: np.ndarray, at: float | None = None) -> list[tuple[float, np.ndarray]]:
        """`at` is when these samples began, in seconds from the start. Speaker loopback sends
        nothing while the PC is silent, so counting samples alone would lose time."""
        out = []
        if at is not None and not self._frames:
            self._clock = at - len(self._pending) / RATE
        samples = np.concatenate([self._pending, samples]) if len(self._pending) else samples
        usable = len(samples) // FRAME * FRAME
        self._pending = samples[usable:]
        for frame in samples[:usable].reshape(-1, FRAME):
            rms = float(np.sqrt(np.mean(frame * frame)))
            self.level = max(rms * 8, self.level * _LEVEL_DECAY)
            if not self._frames:
                self._start = self._clock
            self._clock += FRAME / RATE
            if rms < QUIET_LEVEL and not self._frames:
                continue                      # skip leading silence entirely
            self._frames.append(frame)
            self._quiet = self._quiet + 1 if rms < QUIET_LEVEL else 0
            self._loud += rms >= SPEECH_LEVEL
            seconds = len(self._frames) * FRAME / RATE
            if seconds >= MAX_SECONDS or (seconds >= MIN_SECONDS and self._quiet * FRAME / RATE >= PAUSE_SECONDS):
                out.extend(self._cut())
        return out

    def flush(self) -> list[tuple[float, np.ndarray]]:
        return self._cut()

    def _cut(self):
        frames, start, loud = self._frames, self._start, self._loud
        self._frames, self._quiet, self._loud = [], 0, 0
        if not frames or loud * FRAME / RATE < MIN_SPEECH_SECONDS:
            return []
        return [(start, np.concatenate(frames))]


class Transcriber:
    """Sends utterances to the speech server one at a time; reports text through on_text."""

    def __init__(self, address: str, on_text, context: str = ''):
        self.url = f'ws://{address}'
        self.on_text = on_text
        self.context = context
        self.error = None
        self._queue: queue.Queue = queue.Queue()
        self._busy = False
        self._thread = threading.Thread(target=self._run, daemon=True, name='notetaker-transcriber')
        self._thread.start()

    def submit(self, speaker: str, at: float, samples: np.ndarray):
        self._queue.put((speaker, at, samples))

    @property
    def pending(self) -> int:
        return self._queue.qsize() + self._busy

    def close(self, timeout: float = 90) -> bool:
        """Finish the queued utterances, then stop. False if it ran out of time."""
        self._queue.put(None)
        self._thread.join(timeout)
        return not self._thread.is_alive()

    def _run(self):
        from websockets.sync.client import connect
        ws = None
        while True:
            item = self._queue.get()
            if item is None:
                break
            self._busy = True
            speaker, at, samples = item
            for attempt in range(2):          # one reconnect, e.g. after the engine restarted
                try:
                    # legacy=True: one connection stays open across utterances (websockets >= 17.1)
                    ws = ws or connect(self.url, subprotocols=['binary'], max_size=None, open_timeout=5, legacy=True)
                    text = self._recognize(ws, samples)
                    self.error = None
                    if text:
                        self.on_text(speaker, at, text)
                    break
                except Exception as e:  # shown on the page; the meeting keeps recording
                    self.error = f'Speech engine: {type(e).__name__}: {e}'
                    try:
                        ws and ws.close()
                    except Exception:
                        pass
                    ws = None
                    time.sleep(1 + attempt)
            self._busy = False
        if ws:
            ws.close()

    def _recognize(self, ws, samples: np.ndarray) -> str:
        task_id = str(uuid.uuid4())
        ws.send(json.dumps({
            'task_id': task_id, 'source': 'mic', 'is_final': True,
            'data': base64.b64encode(samples.astype(np.float32).tobytes()).decode('ascii'),
            'time_start': time.time(), 'seg_duration': 15.0, 'seg_overlap': 2.0, 'context': self.context,
        }))
        while True:
            message = json.loads(ws.recv(timeout=120))
            if message.get('task_id') == task_id and message.get('is_final'):
                return (message.get('text') or '').strip()


# -- audio devices ----------------------------------------------------------------

def _same_device(a: str, b: str) -> bool:
    """Windows shortens some device names, so a prefix of either name is the same device."""
    x, y = a.lower().strip(), b.lower().strip()
    return bool(x and y) and (x.startswith(y) or y.startswith(x))


def find_devices(pa, preferred_mic: str | None = None) -> dict:
    """WASAPI devices to record: {'me': info or None, 'others': info or None}."""
    import pyaudiowpatch
    try:
        wasapi = pa.get_host_api_info_by_type(pyaudiowpatch.paWASAPI)
    except OSError:
        return {'me': None, 'others': None}
    inputs = [d for d in pa.get_device_info_generator_by_host_api(host_api_index=wasapi['index'])
              if d['maxInputChannels'] > 0 and not d.get('isLoopbackDevice')]
    mic = next((d for d in inputs if preferred_mic and _same_device(d['name'], preferred_mic)), None)
    if mic is None and wasapi['defaultInputDevice'] >= 0:
        mic = next((d for d in inputs if d['index'] == wasapi['defaultInputDevice']), None)
    try:
        loopback = pa.get_default_wasapi_loopback()
    except (OSError, LookupError):
        loopback = None
    return {'me': mic, 'others': loopback}


class Recorder:
    """Records both sources and feeds them through Segmenters into a Transcriber."""

    def __init__(self, transcriber: Transcriber, preferred_mic: str | None = None, started_at: float | None = None):
        import pyaudiowpatch
        self._pyaudio = pyaudiowpatch
        self.transcriber = transcriber
        self.preferred_mic = preferred_mic
        self.started_at = started_at or time.time()
        self.segmenters = {'me': Segmenter(), 'others': Segmenter()}
        self._locks = {speaker: threading.Lock() for speaker in self.segmenters}
        self._last_audio = {speaker: 0.0 for speaker in self.segmenters}
        self.devices: dict = {}
        self.errors: dict = {}
        self._streams = []
        self._pa = None
        self._stop = threading.Event()

    def start(self):
        self._pa = self._pyaudio.PyAudio()
        found = find_devices(self._pa, self.preferred_mic)
        for speaker, info in found.items():
            if not info:
                continue
            try:
                self._streams.append(self._open(speaker, info))
                self.devices[speaker] = info['name'].replace(' [Loopback]', '')
            except Exception as e:  # the other source can still record
                self.errors[speaker] = f'{info["name"]}: {e}'
        if not self._streams:
            self.stop()
            raise RuntimeError('No microphone or speakers could be recorded on this PC.')
        threading.Thread(target=self._cut_when_silent, daemon=True, name='notetaker-idle').start()

    def _feed(self, speaker: str, samples: np.ndarray):
        now = time.time()
        with self._locks[speaker]:
            self._last_audio[speaker] = now
            cut = self.segmenters[speaker].feed(samples, now - self.started_at - len(samples) / RATE)
        for at, utterance in cut:
            self.transcriber.submit(speaker, at, utterance)

    def _cut_when_silent(self):
        """Loopback stops sending audio when the PC goes silent; end the utterance in progress then."""
        while not self._stop.wait(0.25):
            for speaker, segmenter in self.segmenters.items():
                with self._locks[speaker]:
                    if time.time() - self._last_audio[speaker] < PAUSE_SECONDS:
                        continue
                    cut = segmenter.flush()
                for at, utterance in cut:
                    self.transcriber.submit(speaker, at, utterance)

    def _open(self, speaker: str, info: dict):
        channels = max(1, int(info['maxInputChannels']))
        rate = int(info['defaultSampleRate'])

        def callback(data, frames, time_info, status):
            self._feed(speaker, to_mono_16k(np.frombuffer(data, dtype=np.float32), channels, rate))
            return (None, self._pyaudio.paContinue)

        stream = self._pa.open(format=self._pyaudio.paFloat32, channels=channels, rate=rate, input=True,
                               input_device_index=info['index'], frames_per_buffer=int(rate * 0.1),
                               stream_callback=callback)
        stream.start_stream()
        return stream

    def levels(self) -> dict:
        now = time.time()
        return {speaker: round(min(1.0, s.level), 3) if now - self._last_audio[speaker] < 0.5 else 0.0
                for speaker, s in self.segmenters.items() if speaker in self.devices}

    def stop(self):
        self._stop.set()
        for stream in self._streams:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        self._streams = []
        if self._pa:
            self._pa.terminate()
            self._pa = None
        for speaker, segmenter in self.segmenters.items():
            with self._locks[speaker]:
                cut = segmenter.flush()
            for at, utterance in cut:
                self.transcriber.submit(speaker, at, utterance)


class Session:
    """One meeting being recorded: live lines for the page, saved to the store as they arrive."""

    def __init__(self, store, note_id: int, started_at: float, address: str,
                 preferred_mic: str | None = None, context: str = '', recorder_factory=None):
        self.store = store
        self.note_id = note_id
        self.started_at = started_at
        self.lines: list[dict] = []
        self._lock = threading.Lock()
        self.transcriber = Transcriber(address, self._on_text, context)
        self.recorder = (recorder_factory or Recorder)(self.transcriber, preferred_mic, started_at)
        self.stopping = False

    def _on_text(self, speaker: str, at: float, text: str):
        line = {'speaker': speaker, 'at': round(at, 2), 'text': text}
        with self._lock:
            self.lines.append(line)
            self.lines.sort(key=lambda x: x['at'])
        self.store.add_line(self.note_id, speaker, at, text)

    def start(self):
        try:
            self.recorder.start()
        except Exception:
            self.transcriber.close(timeout=1)
            raise

    def stop(self) -> bool:
        """Stop recording and wait for the last utterances. False if some were not transcribed in time."""
        self.stopping = True
        self.recorder.stop()
        return self.transcriber.close()

    def snapshot(self) -> dict:
        with self._lock:
            lines = list(self.lines)
        return {
            'note_id': self.note_id,
            'started_at': self.started_at,
            'elapsed': time.time() - self.started_at,
            'lines': lines,
            'levels': self.recorder.levels(),
            'devices': dict(self.recorder.devices),
            'device_errors': dict(self.recorder.errors),
            'pending': self.transcriber.pending,
            'error': self.transcriber.error,
            'stopping': self.stopping,
        }
