"""Methods the desktop window calls from JavaScript (window.pywebview.api.*).

Every method returns plain JSON-able data. Errors are returned as
{'error': message} so the page can show them instead of failing silently.
"""
from __future__ import annotations

import functools
import os
import re
import sqlite3
import subprocess
import threading
import time
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path

from config_client import ClientConfig
from util import app_settings, dictionary_files
from . import (__version__, agents, codex, dictation, engine, google_calendar, lmstudio, local_state, meeting,
               meeting_detect, notes, stats, summary)

ROOT = dictation.ROOT                             # the dictation client's folder
CALL_GONE_SECONDS = 20                            # a call missing this long has ended (tabs switch, mics blink)
ZOOM_FILE = 'window.json'                         # in Utter's state/ folder
ZOOM_MIN, ZOOM_MAX = 0.5, 2.5
DB_PATH = ROOT / 'transcripts' / 'transcripts.sqlite3'
_OPENABLE = {
    'transcripts': ROOT / 'transcripts',
    'audio': ROOT,
    'logs': ROOT / 'logs',
    'hot': ROOT / 'hot.txt',
    'rules': ROOT / 'hot-rule.txt',
    'setup': ROOT.parent / 'INSTALL.md',
}
_LINKS = {
    'lmstudio_download': lmstudio.DOWNLOAD_URL,
    'google_calendar_api': 'https://console.cloud.google.com/apis/library/calendar-json.googleapis.com',
    'google_consent': 'https://console.cloud.google.com/auth/overview',
    'google_clients': 'https://console.cloud.google.com/auth/clients/create',
}


def _safe(method):
    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except Exception as e:  # shown in the page
            return {'error': f'{type(e).__name__}: {e}'}
    return wrapper


class Api:
    def __init__(self, root: Path | None = None, db_path: Path | None = None, notes_path: Path | None = None):
        self._root = Path(root) if root else None
        self._db_path = Path(db_path) if db_path else DB_PATH
        self._notes_path = notes_path
        self._notes_store = None
        self._session = None                  # the meeting being recorded
        self._today = None                    # (read at, today's calendar meetings)
        self._today_reading = threading.Lock()
        self._call = None                     # the call going on now (utter.meeting_detect), with its calendar title
        self._call_seen = 0.0
        self._dismissed_calls = set()         # calls the popup was closed for, or already taken notes of
        self._summarizing = set()             # note ids with a summary in progress
        self._notetaker_lock = threading.Lock()
        self._codex_login = codex.Login()
        self._codex_email = None              # (email, read at) cached for a minute; reading starts Codex

    # -- data helpers ----------------------------------------------------

    def _rows(self):
        try:
            return stats.load_rows(self._db_path), None
        except sqlite3.Error as e:
            return ([], []), f'The transcript archive could not be read: {e}'

    def _effective_settings(self) -> dict:
        overrides = app_settings.load()
        values = {key: getattr(ClientConfig, key, None) for key in app_settings.CLIENT_KEYS}
        values['shortcuts'] = ClientConfig.shortcuts
        values.update(app_settings.APP_DEFAULTS)
        for key, value in overrides.items():
            values[key] = (app_settings.merge_shortcuts(ClientConfig.shortcuts, value)
                           if key == 'shortcuts' else value)
        return values

    # -- pages -----------------------------------------------------------

    @_safe
    def get_status(self):
        """Cheap live status, polled every couple of seconds."""
        return {
            'server': engine.server_status(),
            'client': engine.client_status(),
            'llm': engine.llm_backend(),
            'now': time.time(),
        }

    @_safe
    def get_home(self):
        """Greeting and saved settings; the page loads insights and the dictionary separately."""
        settings = self._effective_settings()
        return {'name': settings.get('display_name') or 'there', 'settings': settings, **self.get_status()}

    @_safe
    def get_recent(self, limit=5):
        """Latest final dictations, newest first, for copy-paste recovery (read-only)."""
        return {'items': stats.dictations(self._db_path, limit)}

    @_safe
    def copy_text(self, text):
        """Put text on the Windows clipboard (more reliable than the browser clipboard in WebView2)."""
        import win32clipboard
        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(str(text), win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        return {'ok': True}

    @_safe
    def get_theme(self):
        return self._effective_settings().get('theme') or 'light'

    @_safe
    def get_insights(self):
        (rows, learned), error = self._rows()
        return {**stats.insights(rows, learned), 'error': error}

    # -- dictionary ------------------------------------------------------

    @_safe
    def get_dictionary(self):
        (rows, learned), error = self._rows()
        word_counts, rule_counts = stats.fix_counts(rows)
        learned_at, learned_by = {}, {}
        for item in learned:
            learned_at[item['corrected']] = item['learned_at']
            # the client records who learned it: the AI reviewer, or the app you corrected it in
            learned_by[item['corrected']] = 'review' if item.get('app_process') == 'AI review' else 'edit'
        p = dictionary_files.paths(self._root)

        entries = []
        for source, path in (('manual', p['words']), ('learned', p['learned_words'])):
            for word in dictionary_files.read_words(path):
                entries.append({'kind': 'word', 'source': source, 'text': word,
                                'fixes': word_counts.get(word, 0), 'learned_at': learned_at.get(word),
                                'learned_by': learned_by.get(word)})
        for source, path in (('manual', p['rules']), ('learned', p['learned_rules'])):
            for rule in dictionary_files.read_rules(path):
                count = 0
                for (heard, replacement), n in rule_counts.items():
                    if replacement == rule['replacement']:
                        try:
                            if re.fullmatch(rule['pattern'], heard):
                                count += n
                        except re.error:
                            pass
                entries.append({'kind': 'replacement', 'source': source, 'text': rule['replacement'],
                                'heard': rule['heard'], 'pattern': rule['pattern'],
                                'advanced': rule['heard'] is None, 'fixes': count,
                                'learned_at': learned_at.get(rule['replacement']) if source == 'learned' else None,
                                'learned_by': learned_by.get(rule['replacement']) if source == 'learned' else None})
        return {'entries': entries, 'error': error,
                'auto_learn': bool(self._effective_settings().get('auto_learn'))}

    @_safe
    def add_word(self, word, source='manual'):
        word = (word or '').strip()
        if not word:
            return {'error': 'Type a word or name first.'}
        if word in dictionary_files.all_words(self._root):
            return {'error': f'"{word}" is already in your dictionary.'}
        p = dictionary_files.paths(self._root)
        dictionary_files.add_word(p['learned_words'] if source == 'learned' else p['words'], word)
        return {'ok': True}

    @_safe
    def add_replacement(self, heard, replacement, source='manual'):
        heard, replacement = (heard or '').strip(), (replacement or '').strip()
        if not heard or not replacement:
            return {'error': 'Fill in both what Utter hears and what it should write.'}
        if heard == replacement:
            return {'error': 'The replacement is the same as the original.'}
        p = dictionary_files.paths(self._root)
        added = dictionary_files.add_rule(p['learned_rules'] if source == 'learned' else p['rules'],
                                          heard, replacement)
        return {'ok': True} if added else {'error': f'There is already a replacement for "{heard}".'}

    @_safe
    def remove_entry(self, kind, source, key):
        p = dictionary_files.paths(self._root)
        if kind == 'word':
            path = p['learned_words'] if source == 'learned' else p['words']
            removed = dictionary_files.remove_word(path, key)
        else:
            path = p['learned_rules'] if source == 'learned' else p['rules']
            removed = dictionary_files.remove_rule(path, key)
        return {'ok': True} if removed else {'error': 'That entry was already removed.'}

    # -- settings --------------------------------------------------------

    @_safe
    def get_settings(self):
        return {
            'values': self._effective_settings(),
            'launch_at_login': engine.launch_at_login(),
            'version': __version__,
            'llm': engine.llm_backend(),
            'paths': {key: str(path) for key, path in _OPENABLE.items()},
            'storage': self._storage(),
            'notetaker': {**self._notes.prefs(), 'codex': bool(codex.find_codex()), 'path': str(self._notes.path)},
        }

    @_safe
    def set_setting(self, key, value):
        if key == 'launch_at_login':
            return {'ok': True, 'value': engine.set_launch_at_login(bool(value))}
        values = app_settings.update({key: value})
        return {'ok': True, 'value': values[key]}

    def _storage(self):
        audio = sum(1 for _ in ROOT.glob('[0-9][0-9][0-9][0-9]/*/assets/*'))
        size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
        return {'audio_files': audio, 'archive_bytes': size}

    # -- notetaker -------------------------------------------------------

    @property
    def _notes(self) -> notes.Store:
        if self._notes_store is None:
            self._notes_store = notes.Store(self._notes_path)
        return self._notes_store

    def _me(self) -> str:
        return self._effective_settings().get('display_name') or 'Me'

    @_safe
    def get_notetaker(self, query=''):
        """Past notes (newest first, optionally searched), the live meeting and notetaker preferences."""
        session = self._session
        return {'notes': self._notes.list_notes(query or ''), 'live': session.snapshot() if session else None,
                'prefs': self._notes.prefs(), 'me': self._me(), 'codex': bool(codex.find_codex())}

    @_safe
    def get_today_meetings(self, refresh=False):
        """Today's timed Google Calendar events for the Notetaker page.
        Each is {'title', 'start', 'end' (ISO times), 'join_url', 'attendees'}.

        Reading Google takes about 2 s, so the last copy is returned at once and, when it is
        over a minute old, read again in the background (main.py also reads it at launch)."""
        if not google_calendar.status()['connected']:
            return {'connected': False, 'meetings': []}
        cached = self._today
        if cached and not refresh:
            if time.time() - cached[0] >= 60 and not self._today_reading.locked():
                threading.Thread(target=self._read_today, daemon=True, name='calendar-today').start()
            return cached[1]
        return self._read_today()

    def _read_today(self):
        with self._today_reading:
            return self._read_today_now()

    def _read_today_now(self):
        day = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
        try:
            events = google_calendar.events(day, day + timedelta(days=1))
        except Exception as e:  # offline or the sign-in was revoked: keep the page working
            return {'connected': True, 'meetings': [], 'error': f'Google Calendar could not be read: {e}'}
        result = {'connected': True, 'meetings': [
            {'title': e['title'], 'start': e['start'], 'end': e['end'], 'join_url': google_calendar.join_link(e),
             'attendees': e['attendees']} for e in events if not e['all_day']]}
        self._today = (time.time(), result)
        return result

    @_safe
    def get_live(self):
        session = self._session
        return {'live': session.snapshot() if session else None}

    @_safe
    def start_notetaker(self, title=None, attendees=None):
        """Record the microphone and what the PC plays, transcribing live.
        Started from a calendar event, `title` and `attendees` come from it."""
        attendees = [str(a).strip() for a in attendees or [] if str(a).strip() and '@' not in str(a)]
        with self._notetaker_lock:
            if self._session:
                return {'error': 'The notetaker is already recording.'}
            server = engine.server_status()
            if not server['listening']:
                return {'error': 'The speech engine is off. Start dictation, then try again.', 'engine_off': True}
            client = engine.client_status()
            preferred = (self._effective_settings().get('audio_input_device')
                         or (client.get('microphone') or {}).get('name'))
            started_at = time.time()
            note_id = self._notes.create_note(title, started_at, attendees)
            # Invited people, contact names and dictionary words help the speech model spell people and jargon.
            words = list(dict.fromkeys(attendees + self._notes.contact_names()))[:100]
            words += [w for w in sorted(dictionary_files.all_words(self._root)) if w not in words][:150 - len(words)]
            address = server['address'].replace('0.0.0.0', '127.0.0.1')
            session = meeting.Session(self._notes, note_id, started_at, address, preferred, context=', '.join(words))
            try:
                session.start()
            except Exception:
                self._notes.delete_note(note_id)
                raise
            self._session = session
        return {'ok': True, 'note_id': note_id, 'live': session.snapshot()}

    @_safe
    def stop_notetaker(self):
        """Stop recording; the last words are transcribed and the summary is written in the background."""
        session = self._session
        if not session or session.stopping:
            return {'error': 'The notetaker is not recording.'}

        def finish():
            complete = session.stop()
            with self._notetaker_lock:
                self._session = None
            if not self._notes.lines(session.note_id):
                self._notes.set_status(session.note_id, 'empty', 'No speech was heard.', ended_at=time.time())
                return
            self._notes.set_status(session.note_id, 'summarizing', ended_at=time.time())
            self._summarize(session.note_id, self._notes.prefs()['summarizer'],
                            None if complete else 'The speech engine fell behind, so the last few seconds may be missing.')

        threading.Thread(target=finish, daemon=True, name='notetaker-finish').start()
        return {'ok': True, 'note_id': session.note_id}

    def _summarize(self, note_id, backend, warning=None):
        if note_id in self._summarizing:
            return
        self._summarizing.add(note_id)
        try:
            self._notes.set_status(note_id, 'summarizing')
            note = self._notes.get_note(note_id)
            result = summary.summarize(note['lines'], self._me(), self._notes.contact_names(), backend,
                                       invited=note['attendees'])
            if warning:
                result['warning'] = warning
            self._notes.set_summary(note_id, result, backend)
        except Exception as e:
            message = str(e) if isinstance(e, summary.SummaryError) else f'{type(e).__name__}: {e}'
            self._notes.set_status(note_id, 'failed', message)
        finally:
            self._summarizing.discard(note_id)

    @_safe
    def summarize_note(self, note_id, backend=None):
        """Write (or rewrite) a note's summary in the background; poll get_note for the result."""
        note_id = int(note_id)
        if self._session and self._session.note_id == note_id:
            return {'error': 'This meeting is still being recorded.'}
        if note_id in self._summarizing:
            return {'error': 'This meeting is already being summarized.'}
        backend = backend or self._notes.prefs()['summarizer']
        if backend not in notes.PREFS['summarizer']:
            return {'error': f'Unknown summarizer {backend}'}
        self._notes.set_status(note_id, 'summarizing')
        threading.Thread(target=self._summarize, args=(note_id, backend), daemon=True).start()
        return {'ok': True}

    @_safe
    def get_note(self, note_id):
        return self._notes.get_note(int(note_id)) or {'error': 'That note was deleted.'}

    @_safe
    def rename_note(self, note_id, title):
        title = (title or '').strip()
        if not title:
            return {'error': 'Give the note a title.'}
        return {'ok': True} if self._notes.rename_note(int(note_id), title) else {'error': 'That note was deleted.'}

    @_safe
    def delete_note(self, note_id):
        if self._session and self._session.note_id == int(note_id):
            return {'error': 'Stop the notetaker before deleting this meeting.'}
        return {'ok': True} if self._notes.delete_note(int(note_id)) else {'error': 'That note was already deleted.'}

    # -- calls: offer to take notes when one starts --------------------------

    def _start_call_watch(self, show_popup, hide_popup, open_main, interval=3.0):
        """Watch for calls in the background (main.py passes the popup window's show/hide)."""
        self._popup = {'show': show_popup, 'hide': hide_popup, 'open_main': open_main, 'shown': False}
        threading.Thread(target=self._watch_calls, args=(interval,), daemon=True, name='call-watch').start()

    def _watch_calls(self, interval):
        while True:
            try:
                self._check_call()
            except Exception:
                pass                    # a failed look is retried on the next tick
            time.sleep(interval)

    def _check_call(self, found=None):
        """One look: remember the call going on, then show or hide the popup."""
        on = self._notes.prefs()['call_popup'] == 'on'
        call = (found if found is not None else meeting_detect.current_call()) if on else None
        now = time.time()
        if call:
            self._call_seen = now
            if not self._call or self._call['key'] != call['key']:
                self._call = self._name_call(call)
        elif self._call and now - self._call_seen > CALL_GONE_SECONDS:
            self._call = None
        session = self._session
        from_popup = bool(session and getattr(session, 'call_key', None))
        offer = bool(self._call and self._call['key'] not in self._dismissed_calls and not session)
        want = (offer or from_popup) and on
        popup = getattr(self, '_popup', None)
        if popup and want != popup['shown']:
            popup['shown'] = want
            (popup['show'] if want else popup['hide'])()
        return want

    def _name_call(self, call):
        """Use the calendar event for this call, when there is one, for its title and invited names."""
        call = {**call, 'title': call['app'], 'attendees': []}
        try:
            meetings = self.get_today_meetings().get('meetings') or []
        except Exception:
            meetings = []
        now = datetime.now().astimezone()
        for m in meetings:
            link = m.get('join_url') or ''
            same_meet = call.get('code') and call['code'] in link
            happening = (datetime.fromisoformat(m['start']) <= now + timedelta(minutes=10)
                         and datetime.fromisoformat(m['end']) >= now)
            same_app = happening and call['app'] != 'Google Meet' and (
                ('zoom.us' in link) == (call['app'] == 'Zoom'))
            if same_meet or same_app:
                return {**call, 'title': m['title'], 'attendees': m.get('attendees') or []}
        return call

    @_safe
    def get_call_popup(self):
        """What the call popup shows: an offer for the call going on, or the recording it started."""
        session = self._session
        if session and getattr(session, 'call_key', None):
            return {'mode': 'recording', 'live': session.snapshot(), 'call': self._call}
        if self._call and not session:
            return {'mode': 'offer', 'call': self._call}
        return {'mode': 'none'}

    @_safe
    def start_call_notes(self):
        call = self._call
        if not call:
            return {'error': 'The call has ended.'}
        result = self.start_notetaker(call['title'] if call['title'] != call['app'] else None, call['attendees'])
        if result.get('ok'):
            self._session.call_key = call['key']
            self._dismissed_calls.add(call['key'])      # stopping early does not offer again for this call
        return result

    @_safe
    def dismiss_call(self):
        if self._call:
            self._dismissed_calls.add(self._call['key'])
        self._check_call(found=self._call or False)
        return {'ok': True}

    @_safe
    def open_notetaker(self):
        popup = getattr(self, '_popup', None)
        if popup:
            popup['open_main']()
        return {'ok': True}

    # -- the ChatGPT account Codex uses -------------------------------------

    @_safe
    def get_codex_account(self, refresh=False):
        """The email the Codex CLI is signed in to (Utter has no login of its own), and any sign-in in progress."""
        login = self._codex_login
        if login.state == 'done':           # a new account: read it again
            login.state, refresh = 'idle', True
        if refresh or self._codex_email is None or time.time() - self._codex_email[1] > 60:
            if not codex.find_codex():
                return {'installed': False, 'email': None, 'login': 'idle'}
            self._codex_email = (codex.account_email(), time.time())
        return {'installed': True, 'email': self._codex_email[0], 'login': login.state, 'error': login.error}

    @_safe
    def switch_codex_account(self):
        """Open ChatGPT sign-in in the browser; the Codex CLI switches when it finishes."""
        try:
            self._codex_login.start()
        except codex.CodexError as e:
            return {'error': str(e)}
        return {'ok': True}

    @_safe
    def cancel_codex_login(self):
        self._codex_login.cancel()
        return {'ok': True}

    @_safe
    def set_notetaker_pref(self, key, value):
        self._notes.set_pref(key, value)
        return {'ok': True, 'prefs': self._notes.prefs()}

    # -- contacts ----------------------------------------------------------

    @_safe
    def get_contacts(self):
        return {'contacts': self._notes.list_contacts()}

    @_safe
    def get_contact(self, contact_id):
        return self._notes.get_contact(int(contact_id)) or {'error': 'That contact was deleted.'}

    @_safe
    def save_contact(self, contact, note_id=None, mention=None):
        """Create or update a contact. Given a note and a name as written in it, also link that name."""
        try:
            contact_id = self._notes.save_contact(contact or {})
        except ValueError as e:
            return {'error': str(e)}
        if note_id and mention:
            self._notes.link(int(note_id), mention, contact_id)
        return {'ok': True, 'id': contact_id}

    @_safe
    def delete_contact(self, contact_id):
        return {'ok': True} if self._notes.delete_contact(int(contact_id)) else {'error': 'That contact was already deleted.'}

    @_safe
    def link_mention(self, note_id, mention, contact_id):
        self._notes.link(int(note_id), mention, int(contact_id))
        return {'ok': True}

    @_safe
    def unlink_mention(self, note_id, mention):
        self._notes.unlink(int(note_id), mention)
        return {'ok': True}

    # -- actions ---------------------------------------------------------

    @_safe
    def engine_action(self, action):
        actions = {'start': engine.start_engine, 'stop': engine.stop_engine, 'restart': engine.restart_client}
        if action not in actions:
            return {'error': f'Unknown action {action}'}
        actions[action]()
        return {'ok': True}

    # -- zoom (main.py applies it to the window) ----------------------------

    def get_zoom(self) -> float:
        try:
            return min(ZOOM_MAX, max(ZOOM_MIN, float(local_state.read_json(ZOOM_FILE).get('zoom', 1.0))))
        except (TypeError, ValueError):
            return 1.0

    @_safe
    def set_zoom(self, factor):
        factor = round(min(ZOOM_MAX, max(ZOOM_MIN, float(factor))), 2)
        local_state.write_json(ZOOM_FILE, {'zoom': factor})
        apply = getattr(self, '_apply_zoom', None)
        if apply:
            apply(factor)
        return {'ok': True, 'zoom': factor}

    @_safe
    def open_url(self, url):
        """Open a web link (a calendar event's meeting link) in the default browser."""
        if not re.match(r'https://', str(url or '')):
            return {'error': 'Only https links can be opened.'}
        os.startfile(url)
        return {'ok': True}

    @_safe
    def open_path(self, key):
        path = self._notes.path.parent if key == 'notes' else _OPENABLE.get(key)
        if not path or not path.exists():
            return {'error': 'That file or folder does not exist yet.'}
        os.startfile(str(path))
        return {'ok': True}

    @_safe
    def open_link(self, key):
        url = _LINKS.get(key)
        if not url:
            return {'error': f'Unknown link {key}'}
        webbrowser.open(url)
        return {'ok': True}

    # -- connectors and MCP ------------------------------------------------

    @_safe
    def get_connectors(self):
        return {'google': google_calendar.status(), 'lmstudio': lmstudio.status(), 'agents': agents.status()}

    @_safe
    def add_to_lmstudio(self):
        lmstudio.add()
        return {'ok': True}

    @_safe
    def remove_from_lmstudio(self):
        lmstudio.remove()
        return {'ok': True}

    @_safe
    def choose_google_client(self):
        """Pick the OAuth client JSON downloaded from Google Cloud, then start sign-in."""
        import webview
        paths = webview.windows[0].create_file_dialog(webview.FileDialog.OPEN,
                                                      file_types=('Google OAuth client (*.json)',))
        if not paths:
            return {'cancelled': True}
        google_calendar.set_client_file(paths[0])
        google_calendar.connect()
        return {'ok': True}

    @_safe
    def connect_google(self):
        google_calendar.connect()
        return {'ok': True}

    @_safe
    def disconnect_google(self):
        google_calendar.disconnect()
        return {'ok': True}
