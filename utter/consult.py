"""Ask two advisors about a meeting while it is still going on.

During a call you press "Ask advisors" on the call popup. The last few minutes
of the live transcript go to the notetaker's AI (the same two backends as
utter.summary, DS-008) with a product lens, an engineering lens and what you
offer. The answer is one card for you only: what the other side said their
problem is, one thing to say and one question to ask next, the product read,
the engineering read and where they differ. With Codex the card fills in while
it is written, what to say first (about 2 s after the press).

The lenses ship in utter/advisors/. Your own files in ADVISORS_DIR replace
them: offer.md (what you offer; start from offer.example.md), product.md and
engineering.md.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

from . import summary

LENSES = Path(__file__).resolve().parent / 'advisors'
ADVISORS_DIR = Path(os.environ.get('UTTER_ADVISORS_DIR')
                    or Path(os.environ.get('APPDATA') or Path.home()) / 'Utter' / 'advisors')
NO_OFFER = ('{me} has not described what they offer. Advise on the problem only: do not describe, name or promise '
            'any product or service.')
# Only the recent part of the call: advice is about what was just said.
RECENT_SECONDS = 600
MAX_CHARS = 12000
# Local models often load with a 4k-token context (see summary.LOCAL_CHUNK_CHARS); the lenses take about 1k.
LOCAL_MAX_CHARS = 4000
# 'low' answered as fast as 'medium' (~5 s); a live call cannot wait for a long think.
CODEX_EFFORT = 'low'
_TIMEOUT = 90
PARTIAL_EVERY = 0.15        # seconds between readings of a card being written; the popup looks every 0.25 s

PROMPT = """You privately advise {me} during a live call. Only {me} sees your answer.

What {me} offers:
{offer}

Two advisors read what the other side said, each through their own lens.

=== Product advisor
{product}

=== Engineering advisor
{engineering}

The meeting: {title}. Invited: {invited}.
Below are the last minutes of the transcript, from speech recognition, so expect misheard words. "{me}" is {me}; "Others" is everyone else on the call.

Reply with JSON only:
- "heard": the other side's problem or current workflow in one sentence, from what they actually said.
- "say": 1 or 2 sentences {me} could say now, drawing on both advisors' reads: plain spoken words, in the language the others are speaking. Honest: no invented results, numbers or customers, and no promise beyond what {me} offers.
- "ask": the one question {me} should ask next.
- "product": the product advisor's read in at most 2 sentences: the outcome that matters and what to cut or test first.
- "engineering": the engineering advisor's read in at most 2 sentences: the real bottleneck, what must stay approved by a person, what would fail first.
- "differ": where the two advisors would disagree, in one sentence, or "" if they agree.

Rules:
- Use only what is in the transcript. If no problem has been described yet, say so in "heard" and make "ask" a question that draws it out.
- Never write he, him, his, she or her about anyone: you do not know their pronouns. Use names or they.
- Do not run commands or read files; answer from the text below.

Transcript:
{transcript}"""

# Written in this order, so what to say arrives first; "heard" comes before it to ground it in what was said.
FIELDS = ('heard', 'say', 'ask', 'product', 'engineering', 'differ')
SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': list(FIELDS),
    'properties': {key: {'type': 'string'} for key in FIELDS},
}


def lens(name: str, me: str = '') -> str:
    """Your own file in ADVISORS_DIR if you wrote one, else the one Utter ships (none for offer)."""
    for folder in (ADVISORS_DIR, LENSES):
        try:
            text = (folder / f'{name}.md').read_text(encoding='utf-8').strip()
        except OSError:
            continue
        if text:
            return text.replace('{me}', me)
    return NO_OFFER.format(me=me) if name == 'offer' else ''


def recent(lines: list[dict]) -> list[dict]:
    if not lines:
        return []
    since = lines[-1]['at'] - RECENT_SECONDS
    return [line for line in lines if line['at'] >= since]


def newest(transcript: str, max_chars: int) -> str:
    """The newest whole lines that fit; a single line too long to fit keeps its speaker and its end."""
    kept, size = [], 0
    for line in reversed(transcript.splitlines()):
        grown = size + len(line) + (1 if kept else 0)      # a line break between lines, none after the last
        if grown > max_chars:
            if not kept:
                head = line[:line.find(': ') + 2]
                kept.append(head + '…' + line[len(line) - (max_chars - len(head) - 1):])
            break
        kept.append(line)
        size = grown
    return '\n'.join(reversed(kept))


def prompt(lines: list[dict], me: str, title: str | None = None, invited: list[str] = (),
           max_chars: int = MAX_CHARS) -> str:
    transcript = newest(summary.transcript_text(recent(lines), me), max_chars)
    return PROMPT.format(me=me, offer=lens('offer', me), product=lens('product'), engineering=lens('engineering'),
                         title=title or 'not known', invited=', '.join(invited[:30]) or 'not known',
                         transcript=transcript)


def parse(reply: str) -> dict:
    data = summary.reply_json(reply, 'advice')
    return {key: str(data.get(key) or '').strip() for key in SCHEMA['properties']}


_FIELD = re.compile(r'"(\w+)"\s*:\s*"((?:[^"\\]|\\.)*)')


def partial(written: str) -> dict:
    """The fields of a card still being written: the finished ones and the one being written so far."""
    card = {}
    for match in _FIELD.finditer(written):
        # Drop an escape cut in half, but not an escaped backslash followed by a written "u00".
        key, raw = match[1], re.sub(r'(?<!\\)((?:\\\\)*)\\u[0-9a-fA-F]{0,3}$', r'\1', match[2])
        if key in SCHEMA['properties']:
            try:
                value = json.loads(f'"{raw}"')
            except ValueError:
                continue
            if value and '\ud800' <= value[-1] <= '\udbff':     # half of an emoji, its other half not yet written
                value = value[:-1]
            card[key] = value.strip()
    return card


def advise(lines: list[dict], me: str, backend: str = 'codex', title: str | None = None,
           invited: list[str] = (), ask=None, warm=None, on_partial=None) -> dict:
    """warm: a codex.Warm to ask; on_partial(card_so_far) is called while Codex writes the card."""
    if not lines:
        raise summary.SummaryError('Nothing has been said yet, so there is nothing to advise on.')
    if not ask:
        ask = summary.ask_local if backend != 'codex' else lambda text, schema: ask_codex(text, schema, warm, on_partial)
    max_chars = MAX_CHARS if backend == 'codex' else LOCAL_MAX_CHARS
    return parse(ask(prompt(lines, me, title, invited, max_chars), SCHEMA))


def ask_codex(text: str, schema: dict | None = None, warm=None, on_partial=None) -> str:
    on_text, read_at = None, [0.0]
    if on_partial:
        def on_text(written):
            if time.monotonic() - read_at[0] >= PARTIAL_EVERY:
                read_at[0] = time.monotonic()
                on_partial(partial(written))
    return summary.ask_codex(text, schema, CODEX_EFFORT, _TIMEOUT, warm, on_text)
