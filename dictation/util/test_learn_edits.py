import tempfile
import unittest
from pathlib import Path

from util import dictionary_files as files
from util.client.learn.edits import find_corrections, is_distinctive, plan
from util.hotword.hot_rule import RuleCorrector


def corrections(before_text, inserted, after_text):
    start = before_text.rfind(inserted)
    return find_corrections(before_text, start, inserted, after_text)


class FindCorrectionsTests(unittest.TestCase):
    def test_learns_a_misheard_product_name(self):
        text = "Can we ask bright loop about the order today"
        self.assertEqual(
            corrections(text, text, "Can we ask Brightloop about the order today"),
            [('bright loop', 'Brightloop')])

    def test_learns_inside_surrounding_text(self):
        before = "Notes:\nSend it to cloud code tomorrow\nThanks"
        inserted = "Send it to cloud code tomorrow"
        after = "Notes:\nSend it to Claude Code tomorrow\nThanks"
        self.assertEqual(corrections(before, inserted, after), [('cloud code', 'Claude Code')])

    def test_ignores_text_typed_after_the_dictation(self):
        text = "ping the NASA team"
        self.assertEqual(corrections(text, text, "ping the NASA team about the launch, Alex"), [])

    def test_ignores_common_word_fixes(self):
        text = "I think there going to ship it"
        self.assertEqual(corrections(text, text, "I think they're going to ship it"), [])

    def test_ignores_sentence_start_capitals(self):
        text = "Their plan works"
        self.assertEqual(corrections(text, text, "There plan works"), [])

    def test_ignores_rewrites(self):
        text = "we should meet tomorrow about the quarterly numbers"
        self.assertEqual(corrections(text, text, "Let's skip the Monday sync entirely"), [])

    def test_ignores_unrelated_replacement(self):
        text = "please email Sarah about it"
        self.assertEqual(corrections(text, text, "please email Michael about it"), [])

    def test_learns_unusual_casing(self):
        text = "push it to github later"
        self.assertEqual(corrections(text, text, "push it to GitHub later"), [('github', 'GitHub')])

    def test_cleared_field_learns_nothing(self):
        text = "message for Brightloop"
        self.assertEqual(corrections(text, text, ""), [])

    def test_distinctive_words(self):
        self.assertTrue(is_distinctive('NASA', 'use NASA', 4))
        self.assertTrue(is_distinctive('Qwen3', 'Qwen3 is', 0))
        self.assertTrue(is_distinctive('Brightloop', 'ask Brightloop', 4))
        self.assertFalse(is_distinctive('Brightloop', 'Brightloop is', 0))
        self.assertFalse(is_distinctive('there', 'over there', 5))


class PlanTests(unittest.TestCase):
    def test_adds_word_and_rule_when_fuzzy_match_would_miss(self):
        result = plan('bright loop', 'Brightloop', set(), lambda heard, word: False)
        self.assertEqual(result, {'word': 'Brightloop', 'rule': ('bright loop', 'Brightloop')})

    def test_known_word_caught_by_fuzzy_match_needs_nothing(self):
        result = plan('Claud', 'Claude', {'Claude'}, lambda heard, word: True)
        self.assertEqual(result, {'word': None, 'rule': None})


class LearnTests(unittest.TestCase):
    def test_learns_word_rule_and_logs_once(self):
        import sqlite3
        from util.client.learn.edit_watcher import learn
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'hot.txt').write_text('Claude\n', encoding='utf-8')
            shown = []
            added = learn([('bright loop', 'Brightloop'), ('Claud', 'Claude')], 'chrome.exe',
                          root=root, notify=shown.append)
            again = learn([('bright loop', 'Brightloop')], root=root)
            p = files.paths(root)
            # "bright loop" has the same letters as Brightloop, so the fuzzy matcher
            # handles it and only the word is needed. "Claud" scores below the
            # threshold, so the known word gets an exact replacement instead.
            self.assertEqual(files.read_words(p['learned_words']), ['Brightloop'])
            self.assertEqual([r['heard'] for r in files.read_rules(p['learned_rules'])], ['Claud'])
            self.assertEqual(again, [])
            self.assertEqual(shown, [['Brightloop', 'Claude']])
            self.assertNotIn(('word', 'Claud', 'Claude'), added)
            db = sqlite3.connect(root / 'transcripts' / 'transcripts.sqlite3')
            self.assertEqual(db.execute('SELECT count(*) FROM learned_words').fetchone()[0], len(added))
            db.close()


class DictionaryFilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.p = files.paths(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_words_keep_comments_and_crlf(self):
        self.p['words'].write_bytes(b'# mine\r\nClaude\r\n')
        self.assertTrue(files.add_word(self.p['words'], 'Brightloop'))
        self.assertFalse(files.add_word(self.p['words'], 'Brightloop'))
        self.assertEqual(self.p['words'].read_bytes(), b'# mine\r\nClaude\r\nBrightloop\r\n')
        self.assertTrue(files.remove_word(self.p['words'], 'Claude'))
        self.assertEqual(files.read_words(self.p['words']), ['Brightloop'])

    def test_learned_file_is_created_with_header(self):
        files.add_word(self.p['learned_words'], 'NASA')
        text = self.p['learned_words'].read_text(encoding='utf-8')
        self.assertTrue(text.startswith('# Words Utter learned'))
        self.assertEqual(files.read_words(self.p['learned_words']), ['NASA'])

    def test_rules_are_literal_whole_word_and_round_trip(self):
        files.add_rule(self.p['learned_rules'], 'bright loop', 'Brightloop')
        files.add_rule(self.p['learned_rules'], 'c++ dev', 'C++ developer')
        rules = files.read_rules(self.p['learned_rules'])
        self.assertEqual([r['heard'] for r in rules], ['bright loop', 'c++ dev'])
        corrector = RuleCorrector()
        corrector.update_rules(self.p['learned_rules'].read_text(encoding='utf-8'))
        self.assertEqual(corrector.substitute('a bright loop and an outbright looper, c++ dev'),
                         'a Brightloop and an outbright looper, C++ developer')
        self.assertTrue(files.remove_rule(self.p['learned_rules'], rules[0]['pattern']))
        self.assertEqual(len(files.read_rules(self.p['learned_rules'])), 1)

    def test_existing_regex_rules_are_marked_advanced(self):
        self.p['rules'].write_text('Cud = Claude\n(^comma[,.]?) = ,\n\\/sil = \n', encoding='utf-8')
        rules = files.read_rules(self.p['rules'])
        self.assertEqual([r['heard'] for r in rules], ['Cud', None, None])

    def test_rejects_entries_that_break_the_file_format(self):
        with self.assertRaises(ValueError):
            files.add_rule(self.p['rules'], 'a = b', 'c')
        with self.assertRaises(ValueError):
            files.add_word(self.p['words'], '# comment')


if __name__ == '__main__':
    unittest.main()
