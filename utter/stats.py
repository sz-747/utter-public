"""Usage insights computed from the local transcript archive (read-only)."""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path

from util.text_metrics import count_words

DEFAULT_TYPING_WPM = 110

# Ordered: the first matching category wins. Matched against process name and window title.
CATEGORIES = [
    ('ai', 'AI prompts', ['chatgpt', 'claude', 'gemini', 'copilot', 'perplexity', 'grok', 'codex',
                          'deepseek', 'cursor agent']),
    ('email', 'Emails', ['outlook', 'thunderbird', 'gmail', 'inbox', 'mail']),
    ('messages', 'Messages', ['slack', 'discord', 'telegram', 'whatsapp', 'ms-teams', 'teams', 'wechat',
                              'weixin', 'signal', 'messenger', 'imessage', 'zalo', 'line.exe']),
    ('code', 'Coding', ['code.exe', 'cursor', 'windowsterminal', 'pycharm', 'idea64', 'devenv',
                                 'sublime', 'notepad++', 'powershell', 'cmd.exe', 'wezterm', 'zed']),
    ('documents', 'Documents', ['winword', 'notepad', 'obsidian', 'notion', 'onenote', 'wordpad',
                                'excel', 'powerpnt', 'acrobat', 'google docs', 'evernote']),
]
OTHER = ('other', 'Other tasks')


def categorize(process: str | None, title: str | None) -> tuple[str, str]:
    haystack = f'{process or ""} {title or ""}'.lower()
    for key, label, needles in CATEGORIES:
        if any(needle in haystack for needle in needles):
            return key, label
    return OTHER


def app_label(process: str | None) -> str:
    if not process:
        return 'Unknown app'
    name = process[:-4] if process.lower().endswith('.exe') else process
    known = {'code': 'VS Code', 'windowsterminal': 'Windows Terminal', 'chrome': 'Chrome',
             'msedge': 'Edge', 'winword': 'Word', 'ms-teams': 'Teams', 'explorer': 'File Explorer'}
    return known.get(name.lower(), name[:1].upper() + name[1:])


def load_rows(db_path: Path) -> tuple[list[dict], list[dict]]:
    """Final dictations and learned words; empty lists when the archive does not exist yet."""
    if not Path(db_path).exists():
        return [], []
    db = sqlite3.connect(f'file:{Path(db_path).as_posix()}?mode=ro', uri=True, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        columns = {row[1] for row in db.execute('PRAGMA table_info(dictations)')}
        extra = [c for c in ('app_process', 'app_title', 'fixes') if c in columns]
        select = ', '.join(['started_at', 'raw_text', 'output_text', 'server_message'] + extra)
        rows = [dict(r) for r in db.execute(f'SELECT {select} FROM dictations WHERE final=1 ORDER BY time_start')]
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        learned = ([dict(r) for r in db.execute('SELECT * FROM learned_words ORDER BY learned_at')]
                   if 'learned_words' in tables else [])
    finally:
        db.close()
    for row in rows:
        try:
            row['duration'] = float(json.loads(row.get('server_message') or '{}').get('duration') or 0)
        except (ValueError, TypeError):
            row['duration'] = 0.0
        try:
            row['fixes'] = json.loads(row.get('fixes') or '[]')
        except ValueError:
            row['fixes'] = []
        row['day'] = datetime.fromisoformat(row['started_at']).date()
        row['words'] = count_words(row.get('output_text') or row.get('raw_text'))
        row['spoken_words'] = count_words(row.get('raw_text'))
    return rows, learned


def dictations(db_path: Path, limit: int = 50, query: str = '', since: float | None = None,
               until: float | None = None) -> list[dict]:
    """Final dictations newest first, optionally matching text and a time range (epoch seconds)."""
    if not Path(db_path).exists():
        return []
    db = sqlite3.connect(f'file:{Path(db_path).as_posix()}?mode=ro', uri=True, timeout=5)
    try:
        columns = {row[1] for row in db.execute('PRAGMA table_info(dictations)')}
        delivery = 'delivery' if 'delivery' in columns else "'typed'"
        app = 'app_process' if 'app_process' in columns else 'NULL'
        text = "COALESCE(NULLIF(output_text, ''), raw_text)"
        where, args = ["final=1", "TRIM(raw_text) != ''"], []
        if query.strip():
            where.append(f"{text} LIKE ? ESCAPE '\\'")
            args.append('%' + re.sub(r'([%_\\])', r'\\\1', query.strip()) + '%')
        if since is not None:
            where.append('time_start >= ?')
            args.append(since)
        if until is not None:
            where.append('time_start < ?')
            args.append(until)
        rows = db.execute(f"SELECT started_at, time_start, {text}, {app}, {delivery} FROM dictations "
                          f"WHERE {' AND '.join(where)} ORDER BY time_start DESC LIMIT ?",
                          (*args, int(limit))).fetchall()
    finally:
        db.close()
    return [{'at': at, 'time': start, 'text': body, 'app': app_label(process), 'saved_only': kind == 'saved'}
            for at, start, body, process, kind in rows]


def _streaks(active_days: set[date], today: date) -> tuple[int, int]:
    longest = run = 0
    previous = None
    for day in sorted(active_days):
        run = run + 1 if previous and day - previous == timedelta(days=1) else 1
        longest = max(longest, run)
        previous = day
    # The current streak survives until the end of today even if today is still empty.
    anchor = today if today in active_days else today - timedelta(days=1)
    current = 0
    while anchor in active_days:
        current += 1
        anchor -= timedelta(days=1)
    return current, longest


def changed_words(raw: str | None, output: str | None) -> int:
    """Raw words the cleanup step removed or replaced (word-level diff, case-insensitive)."""
    before = (raw or '').lower().split()
    after = (output or '').lower().split()
    matched = sum(block.size for block in SequenceMatcher(None, before, after, autojunk=False).get_matching_blocks())
    return len(before) - matched


def cleanup_by_app(rows: list[dict]) -> list[dict]:
    """Share of spoken words the cleanup step changed, per app, busiest app first."""
    apps = defaultdict(lambda: {'spoken_words': 0, 'changed_words': 0})
    for row in rows:
        if not row['spoken_words']:
            continue
        app = apps[app_label(row.get('app_process'))]
        app['spoken_words'] += row['spoken_words']
        app['changed_words'] += changed_words(row.get('raw_text'), row.get('output_text') or row.get('raw_text'))
    return sorted(({'name': name, **v, 'percent': round(v['changed_words'] / v['spoken_words'] * 100)}
                   for name, v in apps.items()), key=lambda a: -a['spoken_words'])[:8]


def _term(heard: str, corrected: str) -> re.Pattern:
    # Case-only corrections (Control -> control) must match case-sensitively or they never look fixed.
    flags = 0 if heard.lower() == corrected.lower() else re.IGNORECASE
    return re.compile(rf'(?<!\w){re.escape(heard)}(?!\w)', flags)


def learning_curve(rows: list[dict], learned: list[dict]) -> dict:
    """How fast Utter learns the user's vocabulary, using learned corrections as the answer key.

    A learned correction (heard -> corrected) counts as a new mishearing on the day it was first
    heard. Each later appearance of a heard form in raw text is caught when the output no longer has it.
    Only mishearings someone noticed (the AI reviewer or the user) are counted.
    """
    pairs = {}
    for item in learned:
        heard, corrected = (item.get('heard') or '').strip(), (item.get('corrected') or '').strip()
        try:
            at = datetime.fromisoformat(item.get('learned_at') or '').astimezone()
        except ValueError:
            continue
        if heard and corrected and heard != corrected:
            if (heard, corrected) not in pairs or at < pairs[heard, corrected]:
                pairs[heard, corrected] = at
    terms = [(_term(heard, corrected), at) for (heard, corrected), at in pairs.items()]

    days = defaultdict(lambda: {'words': 0, 'new_mishearings': 0, 'known_seen': 0, 'known_caught': 0})
    first_heard = {}
    totals = {'before_learned': [0, 0], 'after_learned': [0, 0]}
    for row in rows:
        day = days[row['day']]
        day['words'] += row['spoken_words']
        started = datetime.fromisoformat(row['started_at']).astimezone()
        raw, output = row.get('raw_text') or '', row.get('output_text') or row.get('raw_text') or ''
        for index, (term, learned_at) in enumerate(terms):
            seen = len(term.findall(raw))
            if not seen:
                continue
            first_heard.setdefault(index, row['day'])
            caught = max(seen - len(term.findall(output)), 0)
            day['known_seen'] += seen
            day['known_caught'] += caught
            bucket = totals['after_learned' if started >= learned_at else 'before_learned']
            bucket[0] += seen
            bucket[1] += caught
    for index, (_, learned_at) in enumerate(terms):
        days[first_heard.get(index, learned_at.date())]['new_mishearings'] += 1

    curve = [{'day': day.isoformat(), **values,
              'new_per_1k': round(values['new_mishearings'] / values['words'] * 1000, 1) if values['words'] else None}
             for day, values in sorted(days.items())]
    return {
        'learned_corrections': len(pairs),
        'days': curve,
        **{key: {'seen': seen, 'caught': caught, 'percent': round(caught / seen * 100) if seen else None}
           for key, (seen, caught) in totals.items()},
    }


def insights(rows: list[dict], learned: list[dict], today: date | None = None,
             typing_wpm: int = DEFAULT_TYPING_WPM) -> dict:
    today = today or date.today()
    total_words = sum(r['words'] for r in rows)
    timed = [r for r in rows if r['duration'] >= 1.0 and r['spoken_words']]
    speaking_minutes = sum(r['duration'] for r in timed) / 60
    wpm = round(sum(r['spoken_words'] for r in timed) / speaking_minutes) if speaking_minutes else None
    # Negative when the user types faster than they speak.
    typing_minutes = sum(r['spoken_words'] for r in timed) / typing_wpm if typing_wpm else 0

    month_start = today.replace(day=1)
    last_month_start = (month_start - timedelta(days=1)).replace(day=1)
    this_month = sum(r['words'] for r in rows if r['day'] >= month_start)
    last_month = sum(r['words'] for r in rows if last_month_start <= r['day'] < month_start)
    month_change = round((this_month - last_month) / last_month * 100) if last_month else None

    fixes = Counter()
    for row in rows:
        for fix in row['fixes']:
            if fix.get('kind') == 'ai':
                fixes['ai'] += int(fix.get('words') or 0)
            elif fix.get('kind') in ('dictionary', 'rule'):
                fixes[fix['kind']] += 1

    per_day = defaultdict(int)
    for row in rows:
        per_day[row['day']] += row['words']
    current_streak, longest_streak = _streaks(set(per_day), today)

    categories = Counter()
    apps = defaultdict(lambda: {'words': 0, 'dictations': 0})
    for row in rows:
        key, _ = categorize(row.get('app_process'), row.get('app_title'))
        categories[key] += 1
        label = app_label(row.get('app_process'))
        apps[label]['words'] += row['words']
        apps[label]['dictations'] += 1
    labels = dict((key, label) for key, label, _ in CATEGORIES)
    labels[OTHER[0]] = OTHER[1]
    category_list = [{'key': key, 'label': labels[key], 'count': categories.get(key, 0),
                      'percent': round(categories.get(key, 0) / len(rows) * 100) if rows else 0}
                     for key in ['other', 'ai', 'documents', 'code', 'messages', 'email']]
    category_list.sort(key=lambda c: -c['count'])

    today_rows = [r for r in rows if r['day'] == today]
    return {
        'total_words': total_words,
        'dictations': len(rows),
        'wpm': wpm,
        'speaking_minutes': round(speaking_minutes, 1),
        'time_saved': {'typing_wpm': typing_wpm, 'minutes': round(typing_minutes - speaking_minutes, 1)},
        'cleanup': cleanup_by_app(rows),
        'learning': learning_curve(rows, learned),
        'words_this_month': this_month,
        'month_change_percent': month_change,
        'today': {'dictations': len(today_rows), 'words': sum(r['words'] for r in today_rows)},
        'fixes': {
            'dictionary': fixes['dictionary'],
            'rules': fixes['rule'],
            'ai_words': fixes['ai'],
            'learned': len(learned),
            'total': fixes['dictionary'] + fixes['rule'] + fixes['ai'],
        },
        'streak': {'current': current_streak, 'longest': longest_streak},
        'calendar': {day.isoformat(): words for day, words in per_day.items()},
        'categories': category_list,
        'apps': sorted(({'name': k, **v} for k, v in apps.items()), key=lambda a: -a['words'])[:8],
        'total_apps': len([k for k in apps if k != 'Unknown app']),
        'first_day': rows[0]['day'].isoformat() if rows else None,
    }


def fix_counts(rows: list[dict]) -> tuple[Counter, Counter]:
    """How often fixes happened: ({word: n} for dictionary fixes, {(heard, replacement): n} for rules)."""
    words, rules = Counter(), Counter()
    for row in rows:
        for fix in row['fixes']:
            if fix.get('kind') == 'dictionary' and fix.get('to'):
                words[fix['to'].strip()] += 1
            elif fix.get('kind') == 'rule':
                rules[(fix.get('from', ''), fix.get('to', ''))] += 1
    return words, rules
