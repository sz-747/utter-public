import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from util import dictionary_files
from util.client.diary import archive
from util.client.learn import reviewer

# A reply in the shape Codex gives, with grounded, invented and weak entries.
REPLY = '''```json
{"fixes":[{"heard":"codecs","correct":"Codex","why":"coding agent","confidence":0.99},
{"heard":"Quinn","correct":"Qwen","why":"ASR model","confidence":0.99},
{"heard":"pie torch","correct":"PyTorch","why":"library","confidence":0.97},
{"heard":"Gemini Pro","correct":"Gemini","why":"not in the text","confidence":0.99},
{"heard":"pipeline","correct":"Pipeline","why":"weak","confidence":0.5},
{"heard":"Claude","correct":"Claude Code","why":"already a word","confidence":0.95}]}
```'''

TRANSCRIPTS = ['where codecs comes from and this config', 'smarter than the Quinn model',
               'train it with pie torch, just keep the pipeline', 'ask Claude about it']


class AcceptTests(unittest.TestCase):
    def test_keeps_grounded_confident_new_fixes_only(self):
        fixes = reviewer.accept(reviewer.parse_reply(REPLY), TRANSCRIPTS, {'Claude', 'ChatGPT'})
        self.assertEqual(fixes, [('codecs', 'Codex'), ('Quinn', 'Qwen'), ('pie torch', 'PyTorch')])

    def test_bad_replies_give_no_fixes(self):
        self.assertEqual(reviewer.parse_reply('no json here'), [])
        self.assertEqual(reviewer.parse_reply('{"fixes": "nope"'), [])

    def test_prompt_contains_transcripts_and_dictionary(self):
        prompt = reviewer.build_prompt(TRANSCRIPTS, {'Claude'})
        self.assertIn('[1] smarter than the Quinn model', prompt)
        self.assertIn('Known words in their dictionary: Claude', prompt)
        self.assertIn('{"fixes": [{"heard"', prompt)                     # JSON example left intact


class ReviewOnceTests(unittest.TestCase):
    def test_learns_marks_reviewed_and_never_reviews_twice(self):
        from util.client.learn.edit_watcher import learn
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'hot.txt').write_text('Claude\n', encoding='utf-8')
            transcripts = root / 'transcripts'
            with mock.patch.object(archive, 'ROOT', transcripts):
                for i, text in enumerate(TRANSCRIPTS):
                    archive.save_recognition({'task_id': f't{i}', 'time_start': 1000.0 + i, 'is_final': True, 'text': text})
                rows = archive.unreviewed()
                learned = reviewer.review_once(rows, 'codex.exe', lambda fixes, source: learn(fixes, source, root=root),
                                               root=root, ask=lambda prompt, codex: REPLY)
                self.assertEqual(archive.unreviewed(), [])
            words = dictionary_files.read_words(root / 'hot-learned.txt')
            self.assertEqual(set(words), {'Codex', 'Qwen', 'PyTorch'})
            self.assertIn(('word', 'codecs', 'Codex'), learned)
            db = sqlite3.connect(transcripts / 'transcripts.sqlite3')
            sources = {row[0] for row in db.execute('SELECT app_process FROM learned_words')}
            db.close()
            self.assertEqual(sources, {reviewer.REVIEW_SOURCE})


if __name__ == '__main__':
    unittest.main()
