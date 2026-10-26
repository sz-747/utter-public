import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from util.client.diary import archive
from util.hotword.hot_rule import RuleCorrector
from util.hotword.manager import HotwordManager
from util.text_metrics import changed_words, count_words


class TextMetricsTests(unittest.TestCase):
    def test_counts_english_words(self):
        self.assertEqual(count_words("Don't ship it, it's 2 days late"), 7)
        self.assertEqual(count_words('use Claude Code to write it'), 6)

    def test_changed_words_counts_rewrites_and_insertions(self):
        self.assertEqual(changed_words('um so I think we ship', 'I think we ship'), 2)
        self.assertEqual(changed_words('same text', 'same text'), 0)
        self.assertEqual(changed_words('send it to cloud', 'send it to Claude'), 1)


class RuleLogTests(unittest.TestCase):
    def test_logs_each_applied_replacement(self):
        rules = RuleCorrector()
        rules.update_rules('cloud = Claude\n(\\w+)\\s+at\\s+(\\w+)\\s+dot\\s+com = \\1@\\2.com\nnoop = noop\n')
        text, log = rules.substitute_with_log('ask cloud, mail sam at example dot com, noop')
        self.assertEqual(text, 'ask Claude, mail sam@example.com, noop')
        self.assertEqual(log, [('cloud', 'Claude'), ('sam at example dot com', 'sam@example.com')])

    def test_rule_with_trimmed_empty_replacement_still_deletes(self):
        rules = RuleCorrector()
        self.assertEqual(rules.update_rules('(?i)\\bum\\b,?\\s* =\n'), 1)
        self.assertEqual(rules.substitute('So, um, ship it'), 'So, ship it')

    def test_matches_plain_substitute(self):
        rules = RuleCorrector()
        rules.update_rules('a+ = b\n')
        self.assertEqual(rules.substitute_with_log('caaat')[0], rules.substitute('caaat'))


class ArchiveDetailsTests(unittest.TestCase):
    def test_migrates_old_archive_and_saves_details(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = sqlite3.connect(Path(tmp) / 'transcripts.sqlite3')
            db.execute('''CREATE TABLE dictations (
                task_id TEXT NOT NULL, time_start REAL NOT NULL, started_at TEXT NOT NULL,
                raw_text TEXT NOT NULL, final INTEGER NOT NULL, output_text TEXT,
                audio_path TEXT, server_message TEXT NOT NULL, PRIMARY KEY(task_id, time_start))''')
            db.execute("INSERT INTO dictations VALUES ('t',1.0,'2026-10-24T10:00:00+00:00','cloud',1,NULL,NULL,'{}')")
            db.commit()
            db.close()

            original = archive.ROOT
            archive.ROOT = Path(tmp)
            try:
                archive.save_details({'task_id': 't', 'time_start': 1.0},
                                     {'process_name': 'Code.exe', 'title': 'main.py'},
                                     [{'kind': 'dictionary', 'from': 'cloud', 'to': 'Claude'}])
                archive.save_learned('bright loop', 'Brightloop', 'word', 'chrome.exe')
                with archive.connect() as conn:
                    row = conn.execute('SELECT app_process, app_title, fixes FROM dictations').fetchone()
                    learned = conn.execute('SELECT heard, corrected, kind FROM learned_words').fetchall()
            finally:
                archive.ROOT = original

            self.assertEqual(row[:2], ('Code.exe', 'main.py'))
            self.assertEqual(json.loads(row[2])[0]['to'], 'Claude')
            self.assertEqual(learned, [('bright loop', 'Brightloop', 'word')])


class LearnedFilesTests(unittest.TestCase):
    def test_learned_words_and_rules_join_the_manual_lists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'hot.txt').write_text('# manual\nClaude\n', encoding='utf-8')
            (root / 'hot-learned.txt').write_text('Brightloop\n', encoding='utf-8')
            (root / 'hot-rule.txt').write_text('', encoding='utf-8')
            (root / 'hot-rule-learned.txt').write_text('bright loop = Brightloop\n', encoding='utf-8')
            manager = HotwordManager({
                'hot': root / 'hot.txt', 'rule': root / 'hot-rule.txt',
                'rectify': root / 'hot-rectify.txt', 'learned': root / 'hot-learned.txt',
                'rule_learned': root / 'hot-rule-learned.txt'}, threshold=0.85)
            (root / 'hot-learned.txt').write_text('Brightloop\nPyTorch\n', encoding='utf-8')
            manager.load_all()
            self.assertEqual(set(manager.phoneme_corrector.hotwords), {'Claude', 'Brightloop', 'PyTorch'})
            self.assertEqual(manager.rule_corrector.substitute('use bright loop'), 'use Brightloop')

    def test_missing_files_start_from_their_examples(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'hot.example.txt').write_text('# example\nGitHub\n', encoding='utf-8')
            (root / 'hot-rectify.example.txt').write_text('---\nask cloud code\nask Claude Code\n---\n', encoding='utf-8')
            manager = HotwordManager({
                'hot': root / 'hot.txt', 'rule': root / 'hot-rule.txt', 'rectify': root / 'hot-rectify.txt'})
            manager.load_all()
            self.assertEqual((root / 'hot.txt').read_text(encoding='utf-8'), '# example\nGitHub\n')
            self.assertEqual(set(manager.phoneme_corrector.hotwords), {'GitHub'})
            self.assertEqual(len(manager.rectify_rag.records), 1)
            self.assertTrue((root / 'hot-rule.txt').exists())

    def test_missing_learned_files_are_not_created(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manager = HotwordManager({
                'hot': root / 'hot.txt', 'rule': root / 'hot-rule.txt',
                'rectify': root / 'hot-rectify.txt', 'learned': root / 'hot-learned.txt',
                'rule_learned': root / 'hot-rule-learned.txt'})
            manager.load_all()
            self.assertFalse((root / 'hot-learned.txt').exists())


if __name__ == '__main__':
    unittest.main()
