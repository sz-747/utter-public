import tempfile
import unittest
from pathlib import Path
from unittest import mock

from util import dictionary_files
from util.client.audio import recorder


class DictionaryContextTests(unittest.TestCase):
    def test_context_lists_dictionary_words_after_the_language_hint(self):
        self.assertEqual(recorder.asr_context(''), 'The speaker speaks English.')
        self.assertEqual(recorder.asr_context('Names: Utter', ['Pi', 'Codex']),
                         'Names: Utter\nThe speaker speaks English.\nWords and names the speaker often says: Pi, Codex.')

    def test_dictionary_words_stop_at_the_size_limit(self):
        words = [f'word{i:04d}' for i in range(1000)]
        context = recorder.asr_context('', words)
        listed = context.split(': ', 1)[1].rstrip('.').split(', ')
        self.assertEqual(listed, words[:len(listed)])          # the first words win, in order
        self.assertLessEqual(len(', '.join(listed)), recorder.MAX_CONTEXT_WORDS_CHARS)

    def test_dictionary_words_come_yours_first_then_learned_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'hot.txt').write_text('# mine\nUtter\nPi\n', encoding='utf-8')
            (root / 'hot-learned.txt').write_text('Codex\nPi\n', encoding='utf-8')
            self.assertEqual(dictionary_files.ordered_words(root), ['Utter', 'Pi', 'Codex'])

    def test_the_setting_turns_the_words_off(self):
        with mock.patch.object(dictionary_files, 'ordered_words', return_value=['Pi']), \
                mock.patch.object(recorder.Config, 'context', ''):
            with mock.patch.object(recorder.Config, 'dictionary_context', True):
                self.assertIn('Pi', recorder.recording_context())
            with mock.patch.object(recorder.Config, 'dictionary_context', False):
                self.assertNotIn('Pi', recorder.recording_context())


if __name__ == '__main__':
    unittest.main()
