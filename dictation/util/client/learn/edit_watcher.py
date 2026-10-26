"""Watch the field the dictation client just typed into and learn words the user corrects.

After each dictation the watcher reads the focused input field, then re-reads
it every 1.5 s for up to 90 s (or until the next dictation). Corrections that
pass `edits.find_corrections` are added to hot-learned.txt and, when the fuzzy
matcher would not catch the mishearing, to hot-rule-learned.txt.
"""
from __future__ import annotations

import queue
import threading
import time

from config_client import ClientConfig as Config
from util import dictionary_files
from util.client.diary.archive import save_learned
from . import logger
from .edits import find_corrections, normalize_newlines, plan

_POLL_SECONDS = 1.5
_WATCH_SECONDS = 90
# Terminals show a screen buffer, not an editable field; password managers are private.
_SKIP_PROCESSES = {
    'windowsterminal.exe', 'cmd.exe', 'powershell.exe', 'pwsh.exe', 'conhost.exe',
    'openconsole.exe', 'wezterm-gui.exe', 'alacritty.exe', 'mintty.exe',
    '1password.exe', 'keepass.exe', 'keepassxc.exe', 'bitwarden.exe',
}


class _Observation:
    def __init__(self, element, before, start, inserted, process):
        self.element = element
        self.before = before
        self.start = start
        self.inserted = inserted
        self.process = process
        self.began = time.time()
        self.corrections = []


def fuzzy_fixes(heard: str, word: str) -> bool:
    """Would the fuzzy hotword matcher alone turn `heard` into `word`?"""
    from util.hotword.hot_phoneme import PhonemeCorrector
    corrector = PhonemeCorrector(threshold=Config.hot_thresh, similar_threshold=Config.hot_similar)
    corrector.update_hotwords(word)
    return corrector.correct(heard).text.strip() == word


def learn(corrections, process=None, root=None, notify=None) -> list:
    """Apply corrections to the learned dictionary files; returns what was added."""
    p = dictionary_files.paths(root)
    known = dictionary_files.all_words(root)
    added = []
    for heard, corrected in corrections:
        step = plan(heard, corrected, known, fuzzy_fixes)
        if step['word'] and dictionary_files.add_word(p['learned_words'], step['word']):
            known.add(step['word'])
            added.append(('word', heard, corrected))
        if step['rule'] and dictionary_files.add_rule(p['learned_rules'], *step['rule']):
            added.append(('rule', heard, corrected))
    for kind, heard, corrected in added:
        try:
            save_learned(heard, corrected, kind, process, root=None if root is None else root / 'transcripts')
        except Exception as e:
            logger.warning(f'Could not log learned word: {e}')
    if added and notify:
        notify(sorted({corrected for _, _, corrected in added}))
    return added


class EditWatcher:
    def __init__(self):
        self._queue: 'queue.Queue[tuple]' = queue.Queue()
        self._thread = threading.Thread(target=self._run, name='edit-watcher', daemon=True)
        self._thread.start()

    def observe(self, inserted: str, process_name: str = '') -> None:
        if not getattr(Config, 'auto_learn', False) or not inserted or not inserted.strip():
            return
        if (process_name or '').lower() in _SKIP_PROCESSES:
            return
        self._queue.put(('observe', inserted, process_name))

    def shutdown(self) -> None:
        self._queue.put(('shutdown',))

    def _run(self) -> None:
        try:
            import comtypes
            comtypes.CoInitialize()
            from .uia_text import UiaReader
            reader = UiaReader()
        except Exception as e:
            logger.warning(f'Auto-learn unavailable (UI Automation): {e}')
            return

        current = None
        while True:
            try:
                event = self._queue.get(timeout=_POLL_SECONDS if current else None)
            except queue.Empty:
                event = None
            try:
                if event and event[0] == 'shutdown':
                    if current:
                        self._finish(current)
                    return
                if event and event[0] == 'observe':
                    if current:
                        self._finish(current)
                    current = self._begin(reader, event[1], event[2])
                elif current and not self._poll(reader, current):
                    self._finish(current)
                    current = None
            except Exception as e:
                logger.warning(f'Auto-learn error: {e}')
                current = None

    def _begin(self, reader, inserted, process):
        inserted = normalize_newlines(inserted)
        # Typed text can take a moment to land in the target app.
        for _ in range(6):
            time.sleep(0.5)
            element = reader.focused()
            if element is None or reader.is_password(element):
                return None
            text = reader.text(element)
            if text is None:
                return None
            text = normalize_newlines(text)
            start = text.rfind(inserted)
            if start >= 0:
                logger.debug(f'Auto-learn watching {process or "field"} for edits')
                return _Observation(element, text, start, inserted, process)
        logger.debug('Auto-learn: dictated text not visible in the focused field')
        return None

    def _poll(self, reader, obs) -> bool:
        if time.time() - obs.began > _WATCH_SECONDS:
            return False
        text = reader.text(obs.element)
        if text is None:
            return False
        found = find_corrections(obs.before, obs.start, obs.inserted, normalize_newlines(text))
        # Keep the last snapshot that showed a fix: a chat box that is sent and
        # cleared afterwards must not erase what the user corrected before sending.
        if found:
            obs.corrections = found
        return True

    def _finish(self, obs) -> None:
        if obs.corrections:
            # No pop-up: learned words show in Utter's Dictionary instead.
            added = learn(obs.corrections, obs.process)
            for kind, heard, corrected in added:
                logger.info(f'Auto-learned {kind}: {heard} -> {corrected}')


_watcher = None


def get_edit_watcher() -> EditWatcher:
    global _watcher
    if _watcher is None:
        _watcher = EditWatcher()
    return _watcher
