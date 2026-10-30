"""Check Utter's dictation pipeline end to end: recognition, its speed, local resources and AI polish.

Kind: diagnostic helper, run by hand or by an agent following SKILL.md; no automatic trigger.
Run from the repo root with the repo's venv:

    .venv\\Scripts\\python.exe skills\\utter-stabilise\\scripts\\pipeline_check.py doctor [--client <folder>]

`doctor` sends a bundled synthetic recording (assets/doctor-check.wav, Windows TTS, no user data)
through the speech server as a dictation and times it, reports the local resources the speech
server and polish model share (GPU memory, the models Ollama holds), then sends the recognised
text through the client's own AI polish path and output guard, and says which stage fails.
It only reads: nothing is saved, typed or learned. It uses the running speech server and calls
the AI polish model.
`homophones` checks both directions: saved mishearings against today's dictionary, then synthetic
speech of dictionary words and ordinary words that sound alike. It reads the archive and dictionary,
closes the archive before transcribing, and types or saves nothing.
Exit codes: 0 check completed, 1 doctor stage failed, 2 client folder not found,
3 homophones blocked by a stopped speech server.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import unicodedata
import uuid
import wave
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
CLIENT_ROOT = HERE.parents[2] / 'dictation'       # this repo's dictation/ folder
SAMPLE = HERE.parent / 'assets' / 'doctor-check.wav'
SAMPLE_TEXT = 'This is the Utter doctor check. Um, the quick brown fox jumps over the lazy dog.'
SAMPLE_SECONDS = 6.4
MAX_SAMPLE_CER = 0.25        # the sample is clean TTS; worse than this means recognition is broken
SLOW_RECOGNITION_SECONDS = 2.0   # the sample takes ~0.3 s on a desktop GPU; 5.7 s with the GPU's memory full
SLOW_POLISH_SECONDS = 8.0    # the client gives a local model 20 s; past this a dictation visibly waits
GPU_FULL = 0.90              # share of GPU memory in use past which the speech server spills to system RAM
OLLAMA_URL = 'http://127.0.0.1:11434'
SEGMENT, OVERLAP = 60, 4     # what dictation sends (config_client mic_seg_duration / overlap)


# -- text comparison (pure; tested offline) -----------------------------------------------------

def norm(text: str) -> str:
    """Lowercase letters and digits only: punctuation and spacing don't count."""
    text = unicodedata.normalize('NFKC', text or '').lower()
    return ''.join(ch for ch in text if ch.isalnum())


def edit_distance(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def cer(hyp: str, ref: str) -> float:
    """Character error rate of hyp against ref, after norm()."""
    h, r = norm(hyp), norm(ref)
    return edit_distance(h, r) / max(len(r), 1)


# -- the speech server ---------------------------------------------------------------------------

def read_wav(path: Path):
    import numpy as np
    with wave.open(str(path), 'rb') as w:
        if w.getsampwidth() != 2 or w.getframerate() != 16000:
            raise ValueError(f'{path.name} must be 16 kHz 16-bit PCM')
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, w.getnchannels())
    return (data.mean(axis=1) / 32768).astype(np.float32)


class Server:
    def __init__(self):
        from config_client import ClientConfig as Config
        from util.client.audio.recorder import recording_context
        self.host = Config.addr if Config.addr not in ('0.0.0.0', '') else '127.0.0.1'
        self.port = int(Config.port)
        self.context = recording_context()        # the same context dictation sends

    def listening(self) -> bool:
        # A websocket handshake, not a bare TCP connect: the server logs a traceback for those.
        try:
            from websockets.sync.client import connect
            with connect(f'ws://{self.host}:{self.port}', subprotocols=['binary'], open_timeout=2):
                return True
        except Exception:
            return False

    async def _transcribe(self, pcm) -> str:
        import websockets
        task = str(uuid.uuid1())
        base = {'task_id': task, 'seg_duration': SEGMENT, 'seg_overlap': OVERLAP, 'source': 'mic',
                'time_start': time.time(), 'time_frame': time.time(), 'context': self.context}
        async with websockets.connect(f'ws://{self.host}:{self.port}', subprotocols=['binary'],
                                      max_size=None, open_timeout=10) as ws:
            for i in range(0, len(pcm), 32000):                       # 2 s per message, like a live mic
                await ws.send(json.dumps({**base, 'is_final': False,
                                          'data': base64.b64encode(pcm[i:i + 32000].tobytes()).decode()}))
            await ws.send(json.dumps({**base, 'is_final': True, 'data': ''}))
            async for raw in ws:
                msg = json.loads(raw)
                if msg.get('task_id') == task and msg.get('is_final'):
                    return msg.get('text') or ''
        return ''

    def transcribe(self, pcm) -> str:
        return asyncio.run(asyncio.wait_for(self._transcribe(pcm), timeout=max(60, len(pcm) / 16000)))


# -- local resources -------------------------------------------------------------------------------

def gpu_memory() -> tuple[int, int] | None:
    """(used, total) MiB of the first NVIDIA GPU, or None without nvidia-smi."""
    try:
        out = subprocess.run(['nvidia-smi', '--query-gpu=memory.used,memory.total', '--format=csv,noheader,nounits'],
                             capture_output=True, text=True, check=True, timeout=10,
                             creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
        used, total = out.splitlines()[0].split(',')
        return int(used), int(total)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None


def ollama_loaded(url: str = OLLAMA_URL) -> list[dict] | None:
    """Models Ollama holds in memory (`ollama ps`), or None when Ollama does not answer."""
    try:
        import requests
        return requests.get(url + '/api/ps', timeout=5).json().get('models', [])
    except (OSError, ValueError):
        return None


def resource_verdict(gpu: tuple[int, int] | None, models: list[dict] | None) -> tuple[bool | None, str]:
    """(ok, detail) for the GPU the speech server and polish model share. Other programs' models
    loaded with keep_alive forever stay after their job ends; two such models once filled a 16 GB
    GPU and recognition of the sample went from 0.3 s to 5.7 s."""
    parts, held, forever = [], [], []
    if gpu:
        parts.append(f'GPU memory {gpu[0]} / {gpu[1]} MiB ({gpu[0] / gpu[1]:.0%})')
    for m in models or []:
        pinned = (m.get('expires_at') or '')[:4] > str(datetime.now().year + 1)   # "forever" = year 2300+
        if pinned:
            forever.append(m.get('name', '?'))
        held.append(f"{m.get('name', '?')} {(m.get('size_vram') or 0) / 1e9:.1f} GB{' (kept forever)' if pinned else ''}")
    if models is not None:
        parts.append('Ollama holds ' + (', '.join(held) if held else 'nothing'))
    if not gpu:
        return None, '; '.join(['nvidia-smi not available'] + parts)
    ok = gpu[0] / gpu[1] < GPU_FULL
    if not ok:
        parts.append('the GPU is nearly full, so recognition and polish slow down; '
                     + (f"free it with `ollama stop {' / '.join(forever)}` once their job is done" if forever
                        else 'close other GPU programs (games, emulators, other models)'))
    return ok, '; '.join(parts)


# -- doctor --------------------------------------------------------------------------------------

RESULT_OF = {'recognition speed': 'recognition_slow', 'local resources': 'resources_full', 'polish speed': 'polish_slow'}


def doctor() -> int:
    failures = []

    def line(stage, ok, detail):
        print(f"{'PASS' if ok else 'FAIL' if ok is False else 'SKIP'}  {stage}: {detail}")
        if ok is False:
            failures.append(stage)

    def finish():
        print('\nResult: ' + (RESULT_OF[failures[0]] if failures else 'ok'))
        return 1 if failures else 0

    server = Server()
    if not server.listening():
        line('speech server', False, f'nothing answers at {server.host}:{server.port}; start dictation in Utter')
        print('\nResult: server_down')
        return 1
    line('speech server', True, f'{server.host}:{server.port} answers')

    t = time.time()
    heard = server.transcribe(read_wav(SAMPLE))
    rate = min(cer(heard, SAMPLE_TEXT), cer(heard, SAMPLE_TEXT.replace('Um, ', '')))
    seconds = time.time() - t
    line('recognition', rate <= MAX_SAMPLE_CER, f'{rate:.0%} character error in {seconds:.1f} s: "{heard}"')
    if rate > MAX_SAMPLE_CER:
        print('\nResult: recognition_wrong')
        return 1
    line('recognition speed', seconds <= SLOW_RECOGNITION_SECONDS,
         f'{seconds:.1f} s for {SAMPLE_SECONDS:g} s of audio (limit {SLOW_RECOGNITION_SECONDS:g} s)')
    line('local resources', *resource_verdict(gpu_memory(), ollama_loaded()))

    from util import app_settings
    from config_client import ClientConfig as Config
    enabled = app_settings.load().get('llm_enabled', getattr(Config, 'llm_enabled', True))
    from util.llm.llm_client_pool import ClientPool, local_server_listening
    from util.llm.llm_cleanup_guard import validate_cleanup_output
    from util.llm.llm_handler import LLMHandler
    handler = LLMHandler()
    role, content = handler.detect_role(heard)
    if role is None:
        line('AI polish', None, 'no polish role matches; dictation is typed as recognised')
        return finish()
    url = ClientPool.api_url_for(role.provider, role.api_url)
    where = f'{role.model} on {role.provider} ({url})'
    if not local_server_listening(url):
        line('polish server', False, f'nothing listens at {url}; start it (Ollama: ollama serve; LM Studio: lms server start)')
        print('\nResult: polish_unreachable')
        return 1
    line('polish server', True, where + (' answers' if enabled else ' answers (AI polish is OFF in Settings, checked anyway)'))
    if role.provider == 'ollama':
        try:
            import requests
            names = {m.get('name') for m in requests.get(url.rstrip('/') + '/api/tags', timeout=5).json().get('models', [])}
            found = role.model in names or f'{role.model}:latest' in names
            line('polish model', found, 'installed' if found else f'not in `ollama list` ({", ".join(sorted(names)) or "none"})')
            if not found:
                print('\nResult: polish_model_missing')
                return 1
        except (OSError, ValueError) as e:
            line('polish model', None, f'could not list Ollama models: {e}')
    t = time.time()
    try:
        out, _, _ = handler.process(role, content)
    except Exception as e:                                         # the client falls back to the raw text
        line('AI polish', False, f'request failed: {e}')
        print('\nResult: polish_error')
        return 1
    seconds = time.time() - t
    check = validate_cleanup_output(content, out)
    if not (out or '').strip():
        line('AI polish', False, f'empty reply after {seconds:.1f} s (a thinking model with think unset does this)')
        print('\nResult: polish_empty')
        return 1
    line('AI polish', check.accepted, f'{seconds:.1f} s: "{out.strip()}"' + ('' if check.accepted else f' - rejected by the output guard: {check.reason}'))
    if not check.accepted:
        print('\nResult: polish_rejected')
        return 1
    line('polish speed', seconds <= SLOW_POLISH_SECONDS, f'{seconds:.1f} s (limit {SLOW_POLISH_SECONDS:g} s; the first call after the model unloads includes loading it)')
    return finish()



def decode(path: Path):
    """Decode a saved recording as 16 kHz mono float32 through ffmpeg."""
    import numpy as np
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(path), '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'],
                         capture_output=True, check=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).stdout
    return np.frombuffer(raw, dtype=np.float32)
# -- homophones ------------------------------------------------------------------------------------

# Ordinary words people really say that sound like dictionary words, in sentences where they mean
# the ordinary word: none of these should come out as the dictionary word.
KEEP_SENTENCES = [
    ('Switch the car to auto mode.', 'auto'), ('Press the Alt key twice.', 'Alt'),
    ('This piece of art is old.', 'art'), ('I baked an apple pie.', 'pie'),
    ('Cloud storage is cheap.', 'cloud'), ('We need to scale up the servers.', 'scale'),
    ('The noise outside was loud.', 'noise'), ('The audio codec failed.', 'codec'),
    ('I will utter a single word.', 'utter'), ('Whatever is fine with me.', 'whatever'),
]


def mentions(text: str, term: str) -> bool:
    """`term` in `text` as a whole word, ignoring case."""
    import re
    if any(c.isascii() and c.isalpha() for c in term):
        return re.search(r'(?<![A-Za-z])' + re.escape(term) + r'(?![A-Za-z])', text, re.I) is not None
    return term in text


def live_pairs(learned: list[tuple[str, str]], words: set[str], rules: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Learned heard -> corrected pairs whose correction is still in the dictionary (words or rule
    replacements), each once; dropped corrections and half-finished edits ("whateverIs") fall out."""
    targets = {w.lower() for w in words} | {rep.lower() for _, rep in rules}
    out = []
    for heard, corrected in learned:
        if corrected.lower() in targets and heard.lower() != corrected.lower() and (heard, corrected) not in out:
            out.append((heard, corrected))
    return out


def verdict(text: str, heard: str, corrected: str) -> str:
    """'right' (the correction came out), 'wrong' (the sound-alike stayed) or 'other' (neither)."""
    if mentions(text, corrected) and not mentions(text, heard):
        return 'right'
    return 'wrong' if mentions(text, heard) else 'other'


def corrections():
    """The bundled client's post-recognition steps, in result_processor's order, with today's dictionary files.
    Returns text -> (final text, [stage names that changed it])."""
    from config_client import ClientConfig as Config
    from util.hotword.manager import HotwordManager
    from util.client.output.text_output import TextOutput
    m = HotwordManager({'hot': Path('hot.txt'), 'rule': Path('hot-rule.txt'), 'rectify': Path('hot-rectify.txt'),
                        'learned': Path('hot-learned.txt'), 'rule_learned': Path('hot-rule-learned.txt')},
                       threshold=Config.hot_thresh, similar_threshold=Config.hot_similar, rectify_threshold=Config.hot_rectify)
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):               # the loaders print counts
        m.load_all()

    def run(text):
        stages = []
        if Config.hot:
            fixed = m.get_phoneme_corrector().correct(text, k=10).text
            if fixed != text:
                stages.append('dictionary')
            text = fixed
        text = TextOutput.strip_punc(text)
        if getattr(Config, 'hot_rule', True):
            text, log = m.get_rule_corrector().substitute_with_log(text)
            stages += [f'rule {old!r} -> {new!r}' for old, new in log]
        return text, stages
    return run


def synthesize(sentences: list[str], folder: Path, voice: str) -> list[Path]:
    """Windows TTS (System.Speech) reads each sentence into a 16 kHz mono wav."""
    paths = [folder / f'{i}.wav' for i in range(len(sentences))]
    (folder / 'say.json').write_text(json.dumps([[s, str(p)] for s, p in zip(sentences, paths)]), encoding='utf-8')
    safe_voice = voice.replace("'", "''")
    safe_list = str(folder / 'say.json').replace("'", "''")
    script = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
              f"try {{ $s.SelectVoice('{safe_voice}') }} catch {{}}; "
              "$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, 'Sixteen', 'Mono'); "
              f"foreach ($p in (Get-Content -Raw -Encoding utf8 '{safe_list}' | ConvertFrom-Json)) "
              "{ $s.SetOutputToWaveFile($p[1], $fmt); $s.Speak($p[0]) }; $s.Dispose()")
    subprocess.run(['powershell', '-NoProfile', '-Command', script], check=True, capture_output=True,
                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return paths


def homophones(root: Path, voice: str) -> int:
    server = Server()
    if not server.listening():
        print(f'BLOCKED: the speech server does not answer at {server.host}:{server.port}; start dictation in Utter.', file=sys.stderr)
        return 3
    from util import dictionary_files as d
    from util.hotword.hot_phoneme import is_common_english_word
    p = d.paths(root)
    rules = [(r['heard'], r['replacement']) for r in d.read_rules(p['learned_rules']) + d.read_rules(p['rules'])]
    # Read everything first and close: an open read during the minutes of transcribing below holds a
    # lock that makes dictation's own archive writes fail ("database is locked", 2026-10-29).
    try:
        db = sqlite3.connect(f'file:{root / "transcripts" / "transcripts.sqlite3"}?mode=ro', uri=True)
    except sqlite3.Error as exc:
        print(f'BLOCKED: the dictation archive cannot be read: {exc}', file=sys.stderr)
        return 3
    try:
        learned = db.execute('SELECT heard, corrected FROM learned_words ORDER BY learned_at').fetchall()
        dictations = db.execute('SELECT started_at, raw_text, audio_path FROM dictations '
                                'WHERE final=1 AND audio_path IS NOT NULL ORDER BY time_start').fetchall()
    finally:
        db.close()
    pairs = live_pairs(learned, d.all_words(root), rules)
    fix = corrections()

    print('== Your recordings: dictations that had a learned mishearing, recognised and corrected again today ==')
    tally, wrong = {'right': 0, 'wrong': 0, 'other': 0}, []
    for started, raw, audio in dictations:
        hits = [(h, c) for h, c in pairs if raw and mentions(raw, h) and not mentions(raw, c)]
        if not hits or not (root / audio).exists():
            continue
        try:
            final, _ = fix(server.transcribe(decode(root / audio)))
        except (OSError, subprocess.CalledProcessError, asyncio.TimeoutError):
            continue
        for h, c in hits:
            v = verdict(final, h, c)
            tally[v] += 1
            if v != 'right':
                held = ' (held back: an ordinary English word)' if is_common_english_word(h) else ''
                wrong.append(f'  {started[:16]}  "{h}" -> {c}: {v}{held}')
    total = sum(tally.values())
    print(f"right {tally['right']}/{total}, sound-alike still typed {tally['wrong']}, something else {tally['other']}")
    print('\n'.join(wrong) or '  none wrong')

    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        targets = sorted({c for _, c in pairs if c.isascii()})
        catch = [f'Please open {c} for me.' for c in targets]
        try:
            audio = synthesize(catch + [s for s, _ in KEEP_SENTENCES], Path(tmp), voice)
        except (OSError, subprocess.CalledProcessError) as exc:
            print(f'BLOCKED: Windows speech synthesis failed: {exc}', file=sys.stderr)
            return 3
        print(f'\n== Synthetic voice ({voice}) says each dictionary word: is it written that way? ==')
        missed = []
        for c, path in zip(targets, audio):
            final, _ = fix(server.transcribe(read_wav(path)))
            if not mentions(final, c):
                missed.append(f'  {c}: "{final}"')
        print(f'{len(targets) - len(missed)}/{len(targets)} written right')
        print('\n'.join(missed) or '  none missed')

        print('\n== Synthetic voice says the ordinary sound-alike on purpose: is it left alone? ==')
        twisted = []
        for (sentence, word), path in zip(KEEP_SENTENCES, audio[len(targets):]):
            heard = server.transcribe(read_wav(path))
            final, stages = fix(heard)
            if not mentions(final, word):
                by = 'the speech model' if not mentions(heard, word) else ', '.join(stages) or 'unknown'
                twisted.append(f'  "{sentence}" -> "{final}"  (changed by {by})')
        print(f'{len(KEEP_SENTENCES) - len(twisted)}/{len(KEEP_SENTENCES)} left alone')
        print('\n'.join(twisted) or '  none twisted')
    return 0


# -- entry ---------------------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    sub = parser.add_subparsers(dest='command', required=True)
    doc = sub.add_parser('doctor', help='send a synthetic sample through recognition and AI polish')
    doc.add_argument('--client', type=Path, default=CLIENT_ROOT, help="the dictation client's folder (default: this repo's dictation/)")
    ho = sub.add_parser('homophones', help='check dictionary sound-alikes in both directions')
    ho.add_argument('--client', type=Path, default=CLIENT_ROOT)
    ho.add_argument('--voice', default='Microsoft Zira Desktop')
    args = parser.parse_args(argv)
    if not (args.client / 'config_client.py').is_file():
        print(f'BLOCKED: not a dictation client folder: {args.client}', file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding='utf-8')
    sys.path.insert(0, str(args.client))
    os.chdir(args.client)                        # client modules open hot.txt, LLM/ and appdata/ relative to here
    import logging
    logging.disable(logging.WARNING)             # the client logs every step at INFO; keep the report readable
    return homophones(args.client, args.voice) if args.command == 'homophones' else doctor()


if __name__ == '__main__':
    sys.exit(main())
