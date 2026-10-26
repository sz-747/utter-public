"""The Utter MCP server: lets an AI read your dictations, insights, dictionary and meetings.

Every tool is read-only. Codex, Claude Code, Pi (each through its own MCP config) and
LM Studio (utter/lmstudio.py) start it on this PC over stdio:

    .venv\\Scripts\\python.exe -m utter.mcp_server

Nothing may print to stdout here: stdout is the MCP channel.
"""
from __future__ import annotations

import os
import re
import time
from datetime import datetime, timedelta

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from util import dictionary_files
from . import dictation, google_calendar, local_state, stats

DB_PATH = dictation.ROOT / 'transcripts' / 'transcripts.sqlite3'
DICTIONARY_ROOT = None                      # None: the dictation client's folder
MAX_RESULTS = 200

server = MCPServer(
    'Utter',
    instructions=(
        "Utter is the user's voice dictation app on their Windows PC. These tools read what the user "
        "dictated (text typed into apps by voice), their dictation insights, their custom dictionary, and "
        "their Google Calendar meetings. Times are in the user's local time zone unless they include an offset. "
        "To answer questions about a meeting, use list_meetings, which includes what was dictated during it."),
)
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True,
                            open_world_hint=False)


def _record(tool: str) -> None:
    """Remember the last call per app (UTTER_MCP_CLIENT, set by whoever starts this server) so Utter
    can show when each one last read your data."""
    client = re.sub(r'[^a-z0-9]', '', os.environ.get('UTTER_MCP_CLIENT', '').lower()) or 'other'
    activity = {'tool': tool, 'at': time.time()}
    if client == 'lmstudio':
        # LM Studio does not say which model is calling; the loaded one is.
        from . import lmstudio
        activity['models'] = [m['name'] for m in lmstudio.loaded_models() or []]
    try:
        local_state.write_json(f'mcp-activity-{client}.json', activity)
    except OSError:
        pass


def _when(text: str, end: bool = False) -> datetime | None:
    """'2026-10-25' or an ISO date-time to an aware local datetime; a bare end date includes that whole day."""
    text = (text or '').strip()
    if not text:
        return None
    value = datetime.fromisoformat(text.replace('Z', '+00:00'))
    if end and len(text) == 10:
        value += timedelta(days=1)
    return value if value.tzinfo else value.astimezone()


def _today() -> tuple[datetime, datetime]:
    start = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1)


def _limit(n: int) -> int:
    return max(1, min(int(n or 1), MAX_RESULTS))


@server.tool(annotations=READ_ONLY)
def search_dictations(query: str = '', start: str = '', end: str = '', limit: int = 50) -> dict:
    """Find what the user dictated, newest first.

    Args:
        query: Words to look for in the dictated text. Leave empty to list everything in the time range.
        start: Earliest date or date-time, e.g. "2026-10-25" or "2026-10-25T14:00". Optional.
        end: Latest date or date-time. A date includes that whole day. Optional.
        limit: Maximum number of dictations to return (1-200).
    """
    _record('search_dictations')
    since, until = _when(start), _when(end, end=True)
    items = stats.dictations(DB_PATH, _limit(limit), query, since and since.timestamp(), until and until.timestamp())
    return {'count': len(items), 'dictations': [_dictation(item) for item in items]}


def _dictation(item: dict) -> dict:
    return {'at': item['at'], 'text': item['text'], 'app': item['app'],
            'typed': not item['saved_only']}


@server.tool(annotations=READ_ONLY)
def get_insights() -> dict:
    """The user's dictation statistics: words per minute, total words, words today and this month,
    streaks, corrections made, words per day, and which apps they dictate into most. Also: time saved
    against a 110 wpm typing speed (negative if typing is faster), how much cleanup changed their words
    per app, and a learning curve of misheard words (new ones per 1,000 words by day, and how often known
    ones get fixed before vs after Utter learned them)."""
    _record('get_insights')
    rows, learned = stats.load_rows(DB_PATH)
    result = stats.insights(rows, learned)
    result['words_per_day'] = result.pop('calendar')
    result['categories'] = [{'label': c['label'], 'dictations': c['count'], 'percent': c['percent']}
                            for c in result['categories'] if c['count']]
    return result


@server.tool(annotations=READ_ONLY)
def get_dictionary() -> dict:
    """The user's custom dictionary: words and names dictation should spell their way, and replacements
    (what speech recognition hears -> what Utter writes). 'learned' entries were added automatically from
    the user's corrections."""
    _record('get_dictionary')
    p = dictionary_files.paths(DICTIONARY_ROOT)
    words = [{'word': w, 'source': source} for source, key in (('manual', 'words'), ('learned', 'learned_words'))
             for w in dictionary_files.read_words(p[key])]
    replacements = [{'heard': r['heard'] or r['pattern'], 'writes': r['replacement'], 'source': source,
                     'pattern': r['heard'] is None}
                    for source, key in (('manual', 'rules'), ('learned', 'learned_rules'))
                    for r in dictionary_files.read_rules(p[key])]
    return {'words': words, 'replacements': replacements}


@server.tool(annotations=READ_ONLY)
def list_meetings(start: str = '', end: str = '', include_dictations: bool = True) -> dict:
    """The user's Google Calendar events, with what they dictated during each one.

    Args:
        start: Earliest date or date-time, e.g. "2026-10-25". Defaults to the start of today.
        end: Latest date or date-time. A date includes that whole day. Defaults to the end of the start day.
        include_dictations: Add the dictations made between each timed event's start and end.
    """
    _record('list_meetings')
    since = _when(start) or _today()[0]
    until = _when(end, end=True) or since.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    if not google_calendar.status()['connected']:
        return {'error': 'Google Calendar is not connected. The user can connect it in Utter: Settings > Connectors.'}
    meetings = google_calendar.events(since, until)
    if include_dictations:
        attach_dictations(meetings)
    return {'count': len(meetings), 'meetings': meetings}


def attach_dictations(meetings: list[dict]) -> None:
    """Add the dictations made during each timed meeting (all-day events would match the whole day)."""
    for meeting in meetings:
        if meeting['all_day']:
            continue
        begin = datetime.fromisoformat(meeting['start']).timestamp()
        finish = datetime.fromisoformat(meeting['end']).timestamp()
        meeting['dictations'] = [_dictation(item) for item in
                                 reversed(stats.dictations(DB_PATH, MAX_RESULTS, since=begin, until=finish))]


def main() -> None:
    server.run('stdio')


if __name__ == '__main__':
    main()
