import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utter import dictation
from utter.api import Api


def _load_archive():
    """The dictation client's own archive writer, so the database format is tested.

    Loaded by path: importing the util.client package would pull in the
    dictation client's runtime dependencies, which Utter does not need.
    """
    path = dictation.ROOT / 'util' / 'client' / 'diary' / 'archive.py'
    spec = importlib.util.spec_from_file_location('client_archive', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


archive = _load_archive()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'hot.txt').write_bytes(b'# words\r\nClaude\r\n')
        (self.root / 'hot-rule.txt').write_text('cloud = Claude\n(?i)^comma\\b,? = ,\n', encoding='utf-8')
        transcripts = self.root / 'transcripts'
        with mock.patch.object(archive, 'ROOT', transcripts):
            message = {'task_id': 't', 'time_start': 1792809542.0, 'is_final': True, 'text': 'ask cloud',
                       'duration': 2.0}
            archive.save_recognition(message)
            archive.save_details(message, {'process_name': 'Code.exe'},
                                 [{'kind': 'rule', 'from': 'cloud', 'to': 'Claude'}])
        self.api = Api(root=self.root, db_path=transcripts / 'transcripts.sqlite3',
                       notes_path=self.root / 'notetaker.sqlite3')

    def tearDown(self):
        self.tmp.cleanup()

    def test_dictionary_lists_counts_and_round_trips(self):
        entries = self.api.get_dictionary()['entries']
        rule = next(e for e in entries if e['kind'] == 'replacement' and not e['advanced'])
        self.assertEqual((rule['heard'], rule['text'], rule['fixes']), ('cloud', 'Claude', 1))
        self.assertTrue(any(e.get('advanced') for e in entries))

        self.assertEqual(self.api.add_word('Brightloop'), {'ok': True})
        self.assertIn('error', self.api.add_word('Claude'))
        self.assertEqual(self.api.add_replacement('bright loop', 'Brightloop'), {'ok': True})
        self.assertIn('error', self.api.add_replacement('', 'x'))
        self.assertEqual(self.api.remove_entry('word', 'manual', 'Brightloop'), {'ok': True})
        self.assertIn('error', self.api.remove_entry('word', 'manual', 'Brightloop'))
        self.assertEqual(self.api.add_word('Learned1', 'learned'), {'ok': True})
        self.assertTrue((self.root / 'hot-learned.txt').exists())
        self.assertEqual((self.root / 'hot.txt').read_bytes(), b'# words\r\nClaude\r\n')

    def test_insights_read_the_archive(self):
        result = self.api.get_insights()
        self.assertEqual(result['total_words'], 2)
        self.assertEqual(result['fixes']['rules'], 1)
        self.assertEqual(result['total_apps'], 1)

    def test_home_has_greeting_settings_and_status(self):
        home = self.api.get_home()
        self.assertTrue(home['name'])
        self.assertIn('llm_enabled', home['settings'])
        self.assertIn('client', home)

    def test_recent_lists_newest_first_and_flags_not_typed(self):
        transcripts = self.root / 'transcripts'
        with mock.patch.object(archive, 'ROOT', transcripts):
            message = {'task_id': 'u', 'time_start': 1792809600.0, 'is_final': True, 'text': 'menu had focus',
                       'duration': 1.0}
            archive.save_recognition(message)
            archive.save_output(message, 'Menu had focus')
            archive.save_details(message, {'process_name': 'notepad.exe'}, [], 'saved')
        items = self.api.get_recent(5)['items']
        self.assertEqual([i['text'] for i in items], ['Menu had focus', 'ask cloud'])
        self.assertEqual([i['saved_only'] for i in items], [True, False])
        self.assertEqual(items[0]['app'], 'Notepad')

    def test_copy_text_puts_it_on_the_clipboard(self):
        import win32clipboard

        def read():
            win32clipboard.OpenClipboard()
            try:
                return (win32clipboard.GetClipboardData(win32clipboard.CF_UNICODETEXT)
                        if win32clipboard.IsClipboardFormatAvailable(win32clipboard.CF_UNICODETEXT) else None)
            finally:
                win32clipboard.CloseClipboard()

        previous = read()   # the person's clipboard is put back afterwards
        try:
            self.assertEqual(self.api.copy_text('Utter clipboard test café ✓'), {'ok': True})
            self.assertEqual(read(), 'Utter clipboard test café ✓')
        finally:
            if previous is not None:
                self.api.copy_text(previous)

    def test_errors_are_returned_not_raised(self):
        self.assertIn('error', self.api.remove_entry('word', 'manual', None))
        self.assertIn('error', self.api.open_path('not-a-place'))


if __name__ == '__main__':
    unittest.main()
