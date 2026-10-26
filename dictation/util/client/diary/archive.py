"""Durable local dictation records for later review."""
import json
from contextlib import contextmanager
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3] / 'transcripts'


def _local(timestamp=None):
    """An aware datetime in this PC's local time zone (now, or at `timestamp`)."""
    moment = datetime.now(timezone.utc) if timestamp is None else datetime.fromtimestamp(timestamp, timezone.utc)
    return moment.astimezone()

# Columns added after the first release; older archives are migrated in place.
_EXTRA_COLUMNS = {
    'app_process': 'TEXT',   # foreground process that received the text
    'app_title': 'TEXT',     # its window title at output time
    'fixes': 'TEXT',         # JSON list of corrections the dictation client applied
    'delivery': 'TEXT',      # 'typed', or 'saved' when there was nowhere to type it
    'reviewed_at': 'TEXT',   # when the AI dictionary reviewer read this dictation
}


@contextmanager
def connect(root=None):
    root = Path(root) if root else ROOT
    root.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(root / 'transcripts.sqlite3', timeout=10)
    db.execute('''CREATE TABLE IF NOT EXISTS dictations (
        task_id TEXT NOT NULL, time_start REAL NOT NULL, started_at TEXT NOT NULL,
        raw_text TEXT NOT NULL, final INTEGER NOT NULL, output_text TEXT,
        audio_path TEXT, server_message TEXT NOT NULL,
        PRIMARY KEY(task_id, time_start))''')
    existing = {row[1] for row in db.execute('PRAGMA table_info(dictations)')}
    for name, kind in _EXTRA_COLUMNS.items():
        if name not in existing:
            db.execute(f'ALTER TABLE dictations ADD COLUMN {name} {kind}')
    db.execute('''CREATE TABLE IF NOT EXISTS learned_words (
        learned_at TEXT NOT NULL, heard TEXT NOT NULL, corrected TEXT NOT NULL,
        kind TEXT NOT NULL, app_process TEXT)''')
    try:
        yield db
        db.commit()
    finally:
        db.close()


def save_recognition(message):
    started = _local(message['time_start']).isoformat()
    with connect() as db:
        db.execute('''INSERT INTO dictations
            (task_id,time_start,started_at,raw_text,final,server_message) VALUES (?,?,?,?,?,?)
            ON CONFLICT(task_id,time_start) DO UPDATE SET
            raw_text=excluded.raw_text,final=excluded.final,server_message=excluded.server_message''',
            (message['task_id'],message['time_start'],started,message.get('text',''),
             bool(message['is_final']),json.dumps(message,ensure_ascii=False)))


def save_output(message, text, audio_path=None):
    with connect() as db:
        db.execute('''UPDATE dictations SET output_text=?,audio_path=COALESCE(?,audio_path)
            WHERE task_id=? AND time_start=?''',
            (text,str(audio_path) if audio_path else None,message['task_id'],message['time_start']))


def save_details(message, window_info=None, fixes=None, delivery='typed'):
    """Record where the text went, which corrections were applied, and whether it was typed."""
    window_info = window_info or {}
    with connect() as db:
        db.execute('''UPDATE dictations SET app_process=?,app_title=?,fixes=?,delivery=?
            WHERE task_id=? AND time_start=?''',
            (window_info.get('process_name') or None, window_info.get('title') or None,
             json.dumps(fixes or [], ensure_ascii=False), delivery, message['task_id'], message['time_start']))


def unreviewed(limit=20, root=None):
    """Oldest final dictations the AI reviewer has not read yet: [(task_id, time_start, raw_text)]."""
    with connect(root) as db:
        return db.execute('''SELECT task_id, time_start, raw_text FROM dictations
            WHERE final=1 AND reviewed_at IS NULL AND TRIM(raw_text) != ''
            ORDER BY time_start LIMIT ?''', (limit,)).fetchall()


def mark_reviewed(keys, root=None):
    stamp = _local().isoformat()
    with connect(root) as db:
        db.executemany('UPDATE dictations SET reviewed_at=? WHERE task_id=? AND time_start=?',
                       [(stamp, task_id, time_start) for task_id, time_start in keys])


def save_learned(heard, corrected, kind, app_process=None, root=None):
    with connect(root) as db:
        db.execute('INSERT INTO learned_words VALUES (?,?,?,?,?)',
                   (_local().isoformat(), heard, corrected, kind, app_process))
