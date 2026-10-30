"""Turn a meeting transcript into notes: a title, an overview, key points and action items.

Two summarizers:
- 'local': the AI polish model on this PC (Ollama, LM Studio or another
  OpenAI-style server in the dictation client's LLM/default.py). Nothing leaves the PC.
- 'codex' (the default): the Codex app server (utter/codex.py) running
  CODEX_MODEL with the ChatGPT account the Codex CLI is signed in to. The
  transcript is sent to OpenAI.

Nebius Token Factory is an optional online backend. Its key comes from NEBIUS_API_KEY.

The AI lists the people it named; mark_people() then wraps each name as
[[Name]] so the page can link it to a saved contact.
"""
from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path

import requests

from . import codex, dictation

_TIMEOUT = 300
# Pinned so a change to the Codex CLI's own default does not change the notes.
CODEX_MODEL = 'gpt-6-luna'
CODEX_EFFORT = 'medium'
# Local models often load with a 4k-token context, so long meetings are summarized in parts first.
LOCAL_CHUNK_CHARS = 6000

PROMPT = """You take notes for {me}. Below is the transcript of a meeting, transcribed by speech recognition, so expect misheard words. Lines from "{me}" are what {me} said into their microphone; lines from "Others" are everyone else on the call, possibly several people.

Write the meeting notes:
- "title": a short, specific title (3 to 7 words), like "Planning the Q3 Product Launch".
- "overview": 2 to 4 plain sentences on what the meeting was about and what was decided. Refer to people by name, e.g. "{me} reached out to ...".
- "key_points": up to 6 short bullet strings with the facts, decisions and numbers worth keeping.
- "action_items": things someone agreed to do, each {{"owner": "name or empty", "task": "..."}}. Empty list if none.
- "people": every individual person you named in the notes, spelled exactly as in the notes. Only people: no companies, products, teams, events, schools or places.

Rules:
- Use names as said in the transcript. People invited to this meeting in the calendar: {invited}. People {me} has saved as contacts: {contacts}. Use a contact's spelling when the transcript clearly names that person, but do not expand a first name to a contact's full name unless the transcript says it.
- Never write he, him, his, she or her about anyone, including {me}: you do not know their pronouns. Repeat the name or use they/their.
- Never invent facts, names or decisions that are not in the transcript. If the meeting was short or unclear, say less.
- Do not run commands or read files; answer from the text below.

Reply with JSON only: {{"title": "...", "overview": "...", "key_points": ["..."], "action_items": [{{"owner": "...", "task": "..."}}], "people": ["..."]}}

Transcript:
{transcript}"""

PART_PROMPT = """You take notes for {me}. Below is part {part} of {parts} of a meeting transcript from speech recognition ("{me}" is {me}; "Others" is everyone else). Write concise bullet notes of what was said, decided and agreed in this part, keeping names, numbers and commitments. Never write he/him/his/she/her about anyone; use names or they. Plain bullets only, no preamble.

Transcript part:
{transcript}"""

# The notes' shape, enforced by the Codex app server (outputSchema) and by local servers that support it.
SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['title', 'overview', 'key_points', 'action_items', 'people'],
    'properties': {
        'title': {'type': 'string'},
        'overview': {'type': 'string'},
        'key_points': {'type': 'array', 'items': {'type': 'string'}},
        'action_items': {'type': 'array', 'items': {
            'type': 'object', 'additionalProperties': False, 'required': ['owner', 'task'],
            'properties': {'owner': {'type': 'string'}, 'task': {'type': 'string'}}}},
        'people': {'type': 'array', 'items': {'type': 'string'}},
    },
}


class SummaryError(Exception):
    pass


class UnreadableReply(SummaryError):
    """The model answered, but not with notes; worth one more try."""


def transcript_text(lines: list[dict], me: str) -> str:
    out = []
    for line in lines:
        minutes, seconds = divmod(int(line['at']), 60)
        who = me if line['speaker'] == 'me' else 'Others'
        out.append(f'[{minutes:02d}:{seconds:02d}] {who}: {line["text"]}')
    return '\n'.join(out)


def _chunks(text: str, size: int) -> list[str]:
    """Split on line breaks into pieces of at most about `size` characters."""
    parts, current = [], ''
    for line in text.splitlines(keepends=True):
        if current and len(current) + len(line) > size:
            parts.append(current)
            current = ''
        current += line
    return parts + ([current] if current else [])


def mark_people(text: str, people: list[str]) -> str:
    """Wrap each person's name as [[Name]] so the page can link it; longer names first, whole words only."""
    text = re.sub(r'\[\[([^\]]*)\]\]', r'\1', text or '')     # the model's own markers are not trusted
    names = sorted({p for p in people if p}, key=len, reverse=True)
    if not names:
        return text
    pattern = re.compile(r'(?<![\w\[])(' + '|'.join(re.escape(n) for n in names) + r')(?![\w\]])')
    return pattern.sub(r'[[\1]]', text)


_NAME_PARTICLES = {'de', 'da', 'del', 'van', 'von', 'der', 'le', 'la', 'bin', 'al'}


def looks_like_person(name: str, me: str = '') -> bool:
    """Small local models list teams, companies and speaker labels as people; keep only name-shaped entries."""
    words = name.replace("'s", '').split()
    if not words or len(words) > 4 or name.strip().lower() in {'others', 'the others', 'me', 'you', 'speaker', me.lower() + 's'}:
        return False
    return all(_name_word(word) for word in words)


def _name_word(word: str) -> bool:
    """"Jordan", "José", "O'Brien", "Jean-Luc", "McDonald", "Søren"; not "team", "MIT", "OpenAI", "GitHub"."""
    if word.lower() in _NAME_PARTICLES:
        return True
    if not word[0].isalpha():
        return False
    if not word[0].isupper():
        return word[0].lower() == word[0].upper()      # names in scripts without capitals
    body = re.sub(r'^(Mc|Mac)(?=[A-Z])', '', word)
    for i, char in enumerate(body[1:], 1):
        if not (char.isalpha() or char in "'’-"):
            return False
        if char.isupper() and body[i - 1] not in "'’-":
            return False
    return True


def parse(reply: str, me: str = '') -> dict:
    """The notes from the model's reply (tolerates a fenced block or text around the JSON)."""
    reply = re.sub(r'<think>.*?</think>', '', reply or '', flags=re.S)
    match = re.search(r'\{.*\}', reply, re.S)
    if not match:
        raise UnreadableReply('The AI did not reply with notes.')
    try:
        data = json.loads(match.group(0))
    except ValueError as e:
        raise UnreadableReply(f'The AI reply was not valid JSON: {e}') from None
    people = [str(p).strip() for p in data.get('people') or [] if looks_like_person(str(p).strip(), me)]
    people += [me] if me else []
    mark = lambda value: mark_people(str(value or '').strip(), people)
    items = []
    for item in data.get('action_items') or []:
        if isinstance(item, dict) and str(item.get('task', '')).strip():
            items.append({'owner': mark(item.get('owner')), 'task': mark(item['task'])})
        elif isinstance(item, str) and item.strip():
            items.append({'owner': '', 'task': mark(item)})
    return {
        'title': str(data.get('title') or '').strip()[:120],
        'overview': mark(data.get('overview')),
        'key_points': [mark(p) for p in data.get('key_points') or [] if str(p).strip()],
        'action_items': items,
    }


def summarize(lines: list[dict], me: str, contacts: list[str], backend: str = 'local', ask=None,
              invited: list[str] = ()) -> dict:
    if not lines:
        raise SummaryError('Nothing was said, so there is nothing to summarize.')
    ask = ask or (ask_codex if backend == 'codex' else ask_nebius if backend == 'nebius' else ask_local)
    transcript = transcript_text(lines, me)
    if backend != 'codex' and len(transcript) > LOCAL_CHUNK_CHARS:
        parts = _chunks(transcript, LOCAL_CHUNK_CHARS)
        notes = [ask(PART_PROMPT.format(me=me, part=i + 1, parts=len(parts), transcript=part))
                 for i, part in enumerate(parts)]
        transcript = '\n'.join(re.sub(r'<think>.*?</think>', '', n, flags=re.S).strip() for n in notes)
    prompt = PROMPT.format(me=me, contacts=', '.join(contacts[:100]) or 'none yet',
                           invited=', '.join(invited[:30]) or 'not known', transcript=transcript)
    try:
        return parse(ask(prompt, SCHEMA), me)
    except UnreadableReply:
        return parse(ask(prompt, SCHEMA), me)     # one more try: a reply is occasionally cut or malformed


# -- local model (the AI polish backend) -------------------------------------

def local_config(path: Path | None = None):
    """The dictation client's AI polish settings module (LLM/default.py), loaded by path."""
    path = path or dictation.ROOT / 'LLM' / 'default.py'
    spec = importlib.util.spec_from_file_location('dictation_llm_default', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ask_local(prompt: str, schema: dict | None = None, config=None) -> str:
    config = config or local_config()
    provider = getattr(config, 'provider', 'ollama')
    model = getattr(config, 'model', '')
    messages = [{'role': 'user', 'content': prompt}]
    try:
        if provider == 'ollama':
            url = (getattr(config, 'api_url', '') or 'http://127.0.0.1:11434').rstrip('/')
            body = {'model': model, 'messages': messages, 'stream': False, 'think': False,
                    'options': {'temperature': 0.2}}
            if schema:
                body['format'] = schema
            response = requests.post(f'{url}/api/chat', timeout=_TIMEOUT, json=body)
            response.raise_for_status()
            return response.json()['message']['content']
        url = (getattr(config, 'api_url', '') or '').rstrip('/')
        if not url:
            raise SummaryError(f'No server address is set for {provider} in LLM/default.py.')
        body = {'model': model, 'messages': messages, 'temperature': 0.2, 'max_tokens': 2048}
        # LM Studio and other servers on this PC can hold the reply to the schema; online APIs vary, so they get the prompt only.
        if schema and re.match(r'https?://(127\.0\.0\.1|localhost|\[::1\])[:/]', url + '/'):
            body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'notes', 'strict': True, 'schema': schema}}
        options = dict(getattr(config, 'extra_options', {}) or {})
        body.update(options.pop('extra_body', {}) or {})
        body.update(options)
        api_key = os.environ.get('NEBIUS_API_KEY', '') if provider == 'nebius' else getattr(config, 'api_key', '')
        headers = {'Authorization': f'Bearer {api_key or "none"}'}
        response = requests.post(f'{url}/chat/completions', json=body, headers=headers, timeout=_TIMEOUT)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except requests.ConnectionError:
        if _start_local_ai(url):
            return ask_local(prompt, schema, config)
        if provider == 'nebius':
            raise SummaryError('Nebius Token Factory is not answering. Check your connection and NEBIUS_API_KEY.') from None
        raise SummaryError(f'The local AI ({model or provider}) is not answering. Start it, or summarize with Codex.') from None
    except requests.RequestException as e:
        name = 'Nebius Token Factory' if provider == 'nebius' else f'The local AI ({model or provider})'
        raise SummaryError(f'{name} failed: {e}') from None


def ask_nebius(prompt: str, schema: dict | None = None) -> str:
    """Use the Nebius reasoning role, without storing or logging its API key."""
    if not os.environ.get('NEBIUS_API_KEY'):
        raise SummaryError('Set NEBIUS_API_KEY to use Nebius Token Factory.')
    config = local_config()
    config.provider = 'nebius'
    config.api_url = 'https://api.tokenfactory.nebius.com/v1/'
    config.api_key = ''
    config.model = os.environ.get('NEBIUS_ULTRA_MODEL', 'nvidia/Nemotron-3-Ultra-550b-a55b')
    return ask_local(prompt, schema, config)


_local_ai_tried = 0.0


def _start_local_ai(url: str) -> bool:
    """Start the local AI's server when it is off: `ollama serve` for Ollama (port 11434), or LM
    Studio's server (headless, with the lms CLI, port 1234). It loads the model on the first
    request. At most one try every 5 minutes."""
    global _local_ai_tried
    ollama = re.match(r'https?://(127\.0\.0\.1|localhost):11434\b', url or '')
    lms = Path.home() / '.lmstudio' / 'bin' / 'lms.exe'
    lm_studio = re.match(r'https?://(127\.0\.0\.1|localhost):1234\b', url or '')
    if time.time() - _local_ai_tried < 300:
        return False
    if ollama and shutil.which('ollama'):
        _local_ai_tried = time.time()
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) | getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0)
        try:
            subprocess.Popen([shutil.which('ollama'), 'serve'], creationflags=flags, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            return False
        for _ in range(40):                    # it listens within a second or two
            try:
                with socket.create_connection(('127.0.0.1', 11434), timeout=0.25):
                    return True
            except OSError:
                time.sleep(0.25)
        return False
    if lm_studio and lms.exists():
        _local_ai_tried = time.time()
        try:
            result = subprocess.run([str(lms), 'server', 'start'], capture_output=True, text=True, timeout=90,
                                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            return result.returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False
    return False


# -- Codex app server (utter/codex.py) ----------------------------------------------

def ask_codex(prompt: str, schema: dict | None = None) -> str:
    try:
        return codex.ask(prompt, schema, CODEX_MODEL, CODEX_EFFORT, timeout=_TIMEOUT)
    except codex.CodexError as e:
        raise SummaryError(str(e)) from None

