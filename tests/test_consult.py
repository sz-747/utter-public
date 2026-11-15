import tempfile
import unittest
from pathlib import Path
from unittest import mock

from utter import consult, summary


def line(at, text, speaker='others'):
    return {'speaker': speaker, 'at': at, 'text': text}


class ConsultTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mine = Path(self.tmp.name)                               # your own advisor files
        patcher = mock.patch.object(consult, 'ADVISORS_DIR', self.mine)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_prompt_has_both_lenses_and_only_the_recent_call(self):
        lines = [line(10, 'an old topic from the start'), line(900, 'we lose jobs because quotes take three days'),
                 line(905, 'Which tool do you quote in?', 'me')]
        text = consult.prompt(lines, 'Alex', 'Intro call', ['Sam Lee'])
        self.assertIn('=== Product advisor\nProduct judgment', text)
        self.assertIn('=== Engineering advisor\nEngineering judgment', text)
        self.assertIn('Intro call. Invited: Sam Lee.', text)
        self.assertIn('[15:00] Others: we lose jobs because quotes take three days', text)
        self.assertIn('[15:05] Alex: Which tool do you quote in?', text)
        self.assertNotIn('an old topic', text)                       # older than RECENT_SECONDS before the last line

    def test_what_you_offer_comes_from_your_own_file(self):
        text = consult.prompt([line(1, 'hi')], 'Alex')
        self.assertIn('Alex has not described what they offer', text)  # nothing is invented for you
        self.assertNotIn('Northwind', text)                              # the example is only an example
        (self.mine / 'offer.md').write_text('{me} runs a bakery delivery service.', encoding='utf-8')
        (self.mine / 'product.md').write_text('My own product lens.', encoding='utf-8')
        text = consult.prompt([line(1, 'hi')], 'Alex')
        self.assertIn('What Alex offers:\nAlex runs a bakery delivery service.', text)
        self.assertIn('=== Product advisor\nMy own product lens.', text)
        self.assertIn('=== Engineering advisor\nEngineering judgment', text)

    def test_a_long_call_keeps_the_newest_whole_lines(self):
        lines = [line(i, f'line {i} ' + 'x' * 200) for i in range(200)]
        transcript = consult.prompt(lines, 'Alex').split('Transcript:\n', 1)[1]
        self.assertLessEqual(len(transcript), consult.MAX_CHARS)
        self.assertTrue(transcript.startswith('['))
        self.assertTrue(transcript.endswith('x'))
        self.assertIn('line 199 ', transcript)

    def test_trimming_keeps_whole_lines_or_the_end_of_one_long_line(self):
        text = '[00:01] Others: aaaa\n[00:02] Me: bbbb'
        self.assertEqual(consult.newest(text, len(text)), text)                  # a cut on a line start drops nothing
        self.assertEqual(consult.newest(text, len(text) - 1), '[00:02] Me: bbbb')
        long = '[00:03] Others: ' + 'x' * 50 + 'END'
        kept = consult.newest(long, 40)
        self.assertLessEqual(len(kept), 40)
        self.assertTrue(kept.startswith('[00:03] Others: …'))
        self.assertTrue(kept.endswith('END'))

    def test_the_local_model_gets_a_shorter_transcript(self):
        lines = [line(i, f'line {i} ' + 'x' * 200) for i in range(200)]
        sizes = {}
        for backend in ('codex', 'local'):
            consult.advise(lines, 'Alex', backend, ask=lambda p, s, b=backend: sizes.__setitem__(b, len(p)) or '{}')
        self.assertLess(sizes['local'], sizes['codex'] - (consult.MAX_CHARS - consult.LOCAL_MAX_CHARS) + 300)

    def test_advise_sends_the_schema_and_reads_the_card(self):
        asked = []

        def ask(prompt, schema):
            asked.append(schema)
            return 'Here you go: {"heard": "h", "product": "s", "engineering": "k", "differ": "", "say": " say ", "ask": "q?"}'
        card = consult.advise([line(1, 'hi')], 'Alex', ask=ask)
        self.assertEqual(card, {'heard': 'h', 'product': 's', 'engineering': 'k', 'differ': '', 'say': 'say', 'ask': 'q?'})
        self.assertIs(asked[0], consult.SCHEMA)

    def test_what_to_say_is_written_right_after_what_was_heard(self):
        self.assertEqual(consult.SCHEMA['required'][:3], ['heard', 'say', 'ask'])
        text = consult.prompt([line(1, 'hi')], 'Alex')
        self.assertLess(text.index('- "say"'), text.index('- "product"'))

    def test_a_card_still_being_written(self):
        self.assertEqual(consult.partial(''), {})
        self.assertEqual(consult.partial('{"hea'), {})
        self.assertEqual(consult.partial('{"heard": "They lose'), {'heard': 'They lose'})
        written = r'{"heard":"Quotes \"wait\"","bogus":"x","say":"Caf\u00e9 then \u00'
        self.assertEqual(consult.partial(written), {'heard': 'Quotes "wait"', 'say': 'Café then'})
        self.assertEqual(consult.partial('{"heard":"a\\'), {'heard': 'a'})          # an escape cut in half
        self.assertEqual(consult.partial(r'{"say":"C:\\u12'), {'say': 'C:\\u12'})   # a written backslash, then "u12"
        self.assertEqual(consult.partial(r'{"say":"Great \ud83d'), {'say': 'Great'})  # half an emoji

    def test_advise_with_codex_kept_ready_fills_in_the_card_while_written(self):
        warm, seen = object(), []

        def ask_codex(text, schema, effort, timeout, warm_arg, on_text):
            self.assertIs(warm_arg, warm)
            on_text('{"heard":"h","say":"Sa')
            return '{"heard":"h","say":"Say.","ask":"","product":"","engineering":"","differ":""}'
        with mock.patch.object(summary, 'ask_codex', side_effect=ask_codex):
            card = consult.advise([line(1, 'hi')], 'Alex', warm=warm, on_partial=seen.append)
        self.assertEqual((seen, card['say']), ([{'heard': 'h', 'say': 'Sa'}], 'Say.'))

    def test_nothing_said_or_no_card(self):
        with self.assertRaisesRegex(summary.SummaryError, 'Nothing has been said'):
            consult.advise([], 'Alex', ask=lambda *a: '{}')
        with self.assertRaisesRegex(summary.SummaryError, 'did not reply with advice'):
            consult.advise([line(1, 'hi')], 'Alex', ask=lambda *a: 'Sorry, I cannot help.')


if __name__ == '__main__':
    unittest.main()
