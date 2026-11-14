"""Meeting notes and contacts, kept in Utter's own SQLite file.

Utter owns this store; the dictation client never reads it. A note is one meeting: its
transcript lines (who spoke, seconds from the start, text), the AI summary and
which saved contact each name in that summary refers to.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

# UTTER_NOTES_DB points the app at another store, e.g. imported test meetings.
DEFAULT_PATH = Path(os.environ.get('UTTER_NOTES_DB')
                    or Path(os.environ.get('APPDATA') or Path.home()) / 'Utter' / 'notetaker.sqlite3')

# recording -> summarizing -> done; failed keeps the transcript so the summary can be retried.
OPEN_STATUSES = ('recording', 'summarizing')

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    title_set INTEGER NOT NULL DEFAULT 0,   -- 1: given by you or the calendar, so the summary keeps it
    started_at REAL NOT NULL,
    ended_at REAL,
    status TEXT NOT NULL,
    summary TEXT,                           -- JSON from utter.summary
    summarizer TEXT,
    error TEXT,
    attendees TEXT                          -- JSON list of names invited in the calendar, or NULL
);
CREATE TABLE IF NOT EXISTS lines (
    id INTEGER PRIMARY KEY,
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    speaker TEXT NOT NULL,                  -- 'me' (microphone) or 'others' (what the PC played)
    at REAL NOT NULL,                       -- seconds from the start of the meeting
    text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS lines_note ON lines(note_id, at);
CREATE TABLE IF NOT EXISTS contacts (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS mentions (
    note_id INTEGER NOT NULL REFERENCES notes(id) ON DELETE CASCADE,
    name TEXT NOT NULL,                     -- the name as the summary wrote it
    contact_id INTEGER NOT NULL REFERENCES contacts(id) ON DELETE CASCADE,
    PRIMARY KEY (note_id, name)
);
CREATE TABLE IF NOT EXISTS prefs (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

CONTACT_FIELDS = ('name', 'email', 'company', 'notes')
# Notetaker preferences live here, not in the client's settings.json, whose keys the client owns.
PREFS = {'summarizer': ('local', 'codex'), 'call_popup': ('on', 'off')}
PREF_DEFAULTS = {'summarizer': 'codex',   # Codex (gpt-6-luna); see DS-008
                 'call_popup': 'on'}      # offer to take notes when a call starts; see DS-010


class Store:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else DEFAULT_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(SCHEMA)
            if 'attendees' not in {row[1] for row in db.execute('PRAGMA table_info(notes)')}:   # stores made before it
                db.execute('ALTER TABLE notes ADD COLUMN attendees TEXT')
            # A note still open from an earlier run lost its recorder when Utter closed.
            db.execute("UPDATE notes SET status='failed', ended_at=COALESCE(ended_at, started_at), "
                       "error='Utter closed before this meeting was summarized.' "
                       f"WHERE status IN {OPEN_STATUSES}")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys = ON')
        try:
            with db:
                yield db
        finally:
            db.close()

    # -- notes -------------------------------------------------------------

    def create_note(self, title: str | None = None, started_at: float | None = None,
                    attendees: list[str] | None = None) -> int:
        started_at = started_at or time.time()
        with self._db() as db:
            cursor = db.execute(
                "INSERT INTO notes (title, title_set, started_at, status, attendees) VALUES (?, ?, ?, 'recording', ?)",
                ((title or '').strip() or 'Meeting notes', int(bool((title or '').strip())), started_at,
                 json.dumps(attendees, ensure_ascii=False) if attendees else None))
            return cursor.lastrowid

    def add_line(self, note_id: int, speaker: str, at: float, text: str) -> None:
        with self._db() as db:
            db.execute('INSERT INTO lines (note_id, speaker, at, text) VALUES (?, ?, ?, ?)',
                       (note_id, speaker, round(at, 2), text))

    def lines(self, note_id: int) -> list[dict]:
        with self._db() as db:
            rows = db.execute('SELECT speaker, at, text FROM lines WHERE note_id=? ORDER BY at, id', (note_id,))
            return [dict(row) for row in rows]

    def set_status(self, note_id: int, status: str, error: str | None = None, ended_at: float | None = None):
        with self._db() as db:
            db.execute('UPDATE notes SET status=?, error=?, ended_at=COALESCE(?, ended_at) WHERE id=?',
                       (status, error, ended_at, note_id))

    def set_summary(self, note_id: int, summary: dict, summarizer: str) -> None:
        with self._db() as db:
            db.execute("UPDATE notes SET summary=?, summarizer=?, status='done', error=NULL, "
                       "title=CASE WHEN title_set=1 OR ?='' THEN title ELSE ? END WHERE id=?",
                       (json.dumps(summary, ensure_ascii=False), summarizer,
                        summary.get('title', ''), summary.get('title', ''), note_id))

    def rename_note(self, note_id: int, title: str) -> bool:
        with self._db() as db:
            return db.execute('UPDATE notes SET title=?, title_set=1 WHERE id=?', (title, note_id)).rowcount > 0

    def delete_note(self, note_id: int) -> bool:
        with self._db() as db:
            return db.execute('DELETE FROM notes WHERE id=?', (note_id,)).rowcount > 0

    def list_notes(self, query: str = '') -> list[dict]:
        """Newest first. A query matches the title, the summary or anything said."""
        sql = ('SELECT id, title, started_at, ended_at, status FROM notes')
        args = ()
        if query.strip():
            like = f'%{query.strip()}%'
            sql += (' WHERE title LIKE ? OR summary LIKE ? OR id IN '
                    '(SELECT note_id FROM lines WHERE text LIKE ?)')
            args = (like, like, like)
        with self._db() as db:
            return [dict(row) for row in db.execute(sql + ' ORDER BY started_at DESC', args)]

    def get_note(self, note_id: int) -> dict | None:
        with self._db() as db:
            row = db.execute('SELECT * FROM notes WHERE id=?', (note_id,)).fetchone()
            if not row:
                return None
            links = db.execute(
                'SELECT m.name, c.id, c.name AS contact_name, c.email, c.company FROM mentions m '
                'JOIN contacts c ON c.id = m.contact_id WHERE m.note_id=?', (note_id,)).fetchall()
        note = dict(row)
        note['summary'] = json.loads(note['summary']) if note['summary'] else None
        note['attendees'] = json.loads(note['attendees']) if note['attendees'] else []
        note['lines'] = self.lines(note_id)
        note['links'] = {link['name']: {'id': link['id'], 'name': link['contact_name'],
                                        'email': link['email'], 'company': link['company']} for link in links}
        return note

    # -- contacts ----------------------------------------------------------

    def list_contacts(self) -> list[dict]:
        with self._db() as db:
            rows = db.execute(
                'SELECT c.*, COUNT(DISTINCT m.note_id) AS meetings, MAX(n.started_at) AS last_met '
                'FROM contacts c LEFT JOIN mentions m ON m.contact_id = c.id '
                'LEFT JOIN notes n ON n.id = m.note_id GROUP BY c.id ORDER BY c.name COLLATE NOCASE')
            return [dict(row) for row in rows]

    def get_contact(self, contact_id: int) -> dict | None:
        with self._db() as db:
            row = db.execute('SELECT * FROM contacts WHERE id=?', (contact_id,)).fetchone()
            if not row:
                return None
            met = db.execute('SELECT DISTINCT n.id, n.title, n.started_at FROM mentions m '
                             'JOIN notes n ON n.id = m.note_id WHERE m.contact_id=? '
                             'ORDER BY n.started_at DESC', (contact_id,)).fetchall()
        return {**dict(row), 'notes_met': [dict(n) for n in met]}

    def save_contact(self, contact: dict) -> int:
        """Create a contact, or update it when it has an id. Returns the id."""
        values = {key: str(contact.get(key) or '').strip() for key in CONTACT_FIELDS}
        if not values['name']:
            raise ValueError('A contact needs a name.')
        with self._db() as db:
            if contact.get('id'):
                updated = db.execute('UPDATE contacts SET name=?, email=?, company=?, notes=? WHERE id=?',
                                     (*values.values(), int(contact['id']))).rowcount
                if not updated:
                    raise ValueError('That contact no longer exists.')
                return int(contact['id'])
            return db.execute('INSERT INTO contacts (name, email, company, notes, created_at) VALUES (?, ?, ?, ?, ?)',
                              (*values.values(), time.time())).lastrowid

    def delete_contact(self, contact_id: int) -> bool:
        with self._db() as db:
            return db.execute('DELETE FROM contacts WHERE id=?', (contact_id,)).rowcount > 0

    def link(self, note_id: int, name: str, contact_id: int) -> None:
        with self._db() as db:
            db.execute('INSERT OR REPLACE INTO mentions (note_id, name, contact_id) VALUES (?, ?, ?)',
                       (note_id, name, contact_id))

    def unlink(self, note_id: int, name: str) -> bool:
        with self._db() as db:
            return db.execute('DELETE FROM mentions WHERE note_id=? AND name=?', (note_id, name)).rowcount > 0

    def contact_names(self) -> list[str]:
        with self._db() as db:
            return [row[0] for row in db.execute('SELECT DISTINCT name FROM contacts ORDER BY name')]

    # -- preferences -------------------------------------------------------

    def prefs(self) -> dict:
        with self._db() as db:
            saved = dict(db.execute('SELECT key, value FROM prefs').fetchall())
        return {key: saved.get(key) if saved.get(key) in PREFS[key] else default
                for key, default in PREF_DEFAULTS.items()}

    def set_pref(self, key: str, value: str) -> None:
        if value not in PREFS.get(key, ()):
            raise ValueError(f'{key} must be one of {", ".join(PREFS.get(key, ()))}')
        with self._db() as db:
            db.execute('INSERT OR REPLACE INTO prefs (key, value) VALUES (?, ?)', (key, value))
