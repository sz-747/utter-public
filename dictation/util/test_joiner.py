import unittest

from util.client.output import joiner


class JoinTests(unittest.TestCase):
    def test_new_sentence_after_plain_text(self):
        self.assertEqual(joiner.join('I went home', 'then I ate'), ('. ', 'Then I ate'))

    def test_space_only_after_sentence_end(self):
        self.assertEqual(joiner.join('Are we launching?', 'yes'), (' ', 'Yes'))
        self.assertEqual(joiner.join('Two things:', 'first'), (' ', 'first'))

    def test_nothing_before(self):
        self.assertEqual(joiner.join('', 'hello'), ('', 'hello'))
        self.assertEqual(joiner.join('done', '.'), ('', '.'))


class PrepareTests(unittest.TestCase):
    def setUp(self):
        joiner.watch()
        self.window = (101, 'WindowsTerminal.exe')
        joiner.remember(self.window, 'I went home')

    def test_joins_in_same_window_untouched(self):
        self.assertEqual(joiner.prepare(self.window, 'then I ate'), ('. ', 'Then I ate'))

    def test_key_or_click_since_last_output_stops_join(self):
        joiner.note_user_input()
        self.assertEqual(joiner.prepare(self.window, 'then I ate'), ('', 'then I ate'))

    def test_other_window_stops_join(self):
        self.assertEqual(joiner.prepare((202, 'chrome.exe'), 'then I ate'), ('', 'then I ate'))

    def test_unknown_window_stops_join(self):
        joiner.remember(None, 'I went home')
        self.assertEqual(joiner.prepare(None, 'then I ate'), ('', 'then I ate'))

    def test_window_key(self):
        self.assertEqual(joiner.window_key({'hwnd': 101, 'process_name': 'WindowsTerminal.exe'}), self.window)
        self.assertIsNone(joiner.window_key({}))


if __name__ == '__main__':
    unittest.main()
