"""AI dictionary reviewer: a smarter model reads finished dictations and learns misheard words.

Runs in the background through the Codex CLI (the person's ChatGPT login), so the
transcript text of reviewed dictations is sent to OpenAI; Settings > Dictation
can turn it off (auto_review). It works in batches while dictation is idle:
at least _MIN_BATCH new dictations, or any new ones after _MAX_WAIT seconds.

Every suggested fix must quote text that actually appears in the batch, be at
least _MIN_CONFIDENCE confident and be new to the dictionary; accepted fixes go
through the same learn() path as corrections you make yourself, so they show as
"Learned" in Utter and can be removed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from config_client import ClientConfig as Config
from util import dictionary_files
from util.client.diary import archive
from . import logger

REVIEW_SOURCE = 'AI review'
_MIN_CONFIDENCE = 0.9
_MIN_BATCH = 3
_MAX_WAIT = 30 * 60          # review fewer than _MIN_BATCH after this long
_IDLE_SECONDS = 60           # never while dictating, and not right after
_BATCH_SIZE = 20
_RETRY_AFTER = 15 * 60       # after a failed run (offline, signed out)
_TIMEOUT = 300

PROMPT = """You review speech-recognition transcripts from one person who dictates in English. Find words the recogniser got WRONG: misheard product, company, tool or person names, and technical terms.

Rules:
- "heard" must be copied exactly from the transcript.
- Only report fixes you are confident about from the context. Ignore ordinary English words, grammar, filler words and punctuation.
- Do not report anything already spelled correctly, or anything in the known-word list.
- Do not run commands or read files; answer from the text below.

Reply with JSON only: {"fixes": [{"heard": "...", "correct": "...", "why": "short", "confidence": 0.0-1.0}]}"""

status = {'enabled': True, 'last_run': None, 'last_result': None, 'error': None, 'learned_total': 0}


def build_prompt(transcripts, known_words):
    known = ', '.join(sorted(known_words)[:200])
    lines = '\n'.join(f'[{i}] {text}' for i, text in enumerate(transcripts))
    return f'{PROMPT}\n\nKnown words in their dictionary: {known}\n\nTranscripts:\n{lines}'


def parse_reply(reply):
    """The fixes list from the model's reply (tolerates a fenced code block)."""
    match = re.search(r'\{.*\}', reply or '', re.S)
    if not match:
        return []
    try:
        fixes = json.loads(match.group(0)).get('fixes', [])
    except (ValueError, AttributeError):
        return []
    return [f for f in fixes if isinstance(f, dict)]


def accept(fixes, transcripts, known_words):
    """Keep only fixes that are grounded in the text, confident, well-formed and new."""
    corpus = '\n'.join(transcripts).lower()
    known = {w.lower() for w in known_words}
    accepted = []
    for fix in fixes:
        heard = str(fix.get('heard', '')).strip()
        correct = str(fix.get('correct', '')).strip()
        try:
            confidence = float(fix.get('confidence', 0))
        except (TypeError, ValueError):
            continue
        if not heard or not correct or heard == correct or confidence < _MIN_CONFIDENCE:
            continue
        if len(correct) > 40 or len(heard) > 60 or '\n' in heard + correct or ' = ' in heard + correct:
            continue
        if heard.lower() not in corpus:              # must quote the transcript, not invent it
            continue
        if heard.lower() in known:                   # a dictionary word is not a mishearing
            continue
        if (heard, correct) not in accepted:
            accepted.append((heard, correct))
    return accepted


def find_codex():
    configured = getattr(Config, 'review_codex_path', None)
    candidates = [configured, str(Path.home() / '.codex/packages/standalone/current/bin/codex.exe'),
                  shutil.which('codex.exe')]
    return next((c for c in candidates if c and Path(c).exists()), None)


def ask_codex(prompt, codex):
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / 'answer.md'
        env = {k: v for k, v in os.environ.items() if k != 'CODEX_API_KEY'}   # use the saved ChatGPT login
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'BELOW_NORMAL_PRIORITY_CLASS', 0)
        result = subprocess.run([codex, 'exec', '--skip-git-repo-check', '-s', 'read-only', '-C', tmp, '-o', str(out), '-'],
                                input=prompt, capture_output=True, text=True, encoding='utf-8', env=env,
                                timeout=_TIMEOUT, creationflags=flags)
        if result.returncode != 0 or not out.exists():
            raise RuntimeError(f'Codex exited {result.returncode}: {result.stderr.strip()[-300:]}')
        return out.read_text(encoding='utf-8')


def known_words(root=None):
    p = dictionary_files.paths(root)
    words = dictionary_files.all_words(root)
    for key in ('rules', 'learned_rules'):
        words |= {r['replacement'] for r in dictionary_files.read_rules(p[key]) if r['replacement']}
    return words


def review_once(rows, codex, learn_fn, root=None, ask=ask_codex):
    """Review one batch [(task_id, time_start, text)]; returns what was learned."""
    transcripts = [text for _, _, text in rows]
    known = known_words(root)
    fixes = accept(parse_reply(ask(build_prompt(transcripts, known), codex)), transcripts, known)
    learned = learn_fn(fixes, REVIEW_SOURCE) if fixes else []
    archive.mark_reviewed([(task_id, time_start) for task_id, time_start, _ in rows],
                          root=None if root is None else Path(root) / 'transcripts')
    return learned


class Reviewer:
    def __init__(self):
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name='ai-reviewer', daemon=True)
        self._first_pending_at = None
        self._retry_at = 0.0
        self._thread.start()

    def nudge(self):
        """A dictation just finished; check soon."""
        self._wake.set()

    def shutdown(self):
        self._stop.set()
        self._wake.set()

    def _idle(self):
        from util.client.state import get_state
        state = get_state()
        if state.recording:
            return False
        last = getattr(state, 'last_output_time', None)
        return last is None or time.time() - last > _IDLE_SECONDS

    def _run(self):
        while not self._stop.is_set():
            self._wake.wait(60)
            self._wake.clear()
            status['enabled'] = bool(getattr(Config, 'auto_review', False))
            if not status['enabled'] or time.time() < self._retry_at:
                continue
            try:
                rows = archive.unreviewed(_BATCH_SIZE)
            except Exception as e:
                logger.debug(f'AI review: archive unavailable: {e}')
                continue
            if not rows:
                self._first_pending_at = None
                continue
            self._first_pending_at = self._first_pending_at or time.time()
            waited = time.time() - self._first_pending_at
            if (len(rows) < _MIN_BATCH and waited < _MAX_WAIT) or not self._idle():
                continue
            codex = find_codex()
            if not codex:
                status['error'] = 'Codex CLI not found'
                self._retry_at = time.time() + _RETRY_AFTER
                continue
            try:
                from .edit_watcher import learn
                learned = review_once(rows, codex, lambda fixes, source: learn(fixes, source))
                status.update(last_run=time.time(), error=None,
                              last_result=f'{len(rows)} dictations, {len(learned)} learned')
                status['learned_total'] += len(learned)
                self._first_pending_at = None
                for kind, heard, corrected in learned:
                    logger.info(f'AI review learned {kind}: {heard} -> {corrected}')
                self._wake.set()                      # more backlog? go again
            except Exception as e:
                status['error'] = str(e)[:200]
                self._retry_at = time.time() + _RETRY_AFTER
                logger.warning(f'AI review failed, retrying later: {e}')


_reviewer = None


def get_reviewer() -> Reviewer:
    global _reviewer
    if _reviewer is None:
        _reviewer = Reviewer()
    return _reviewer
