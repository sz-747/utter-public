import unittest

from util.hotword.hot_phoneme import PhonemeCorrector

WORDS = '\n'.join(['Claude', 'Claude Code', 'Codex', 'PyTorch', 'Brightloop', 'GitHub', 'Tailscale', 'ChatGPT',
                   'DeepSeek', 'Anthropic', 'OpenAI', 'LM Studio', 'WebView2', 'Ollama', 'Notion'])


class DictionaryMatchingTests(unittest.TestCase):
    def setUp(self):
        self.corrector = PhonemeCorrector(threshold=0.85, similar_threshold=0.6)
        self.corrector.update_hotwords(WORDS)

    def test_split_or_misheard_words_become_dictionary_words(self):
        cases = {
            'bright loop launches today': 'Brightloop launches today',
            'push it to git hub': 'push it to GitHub',
            'set up tail scale on the laptop': 'set up Tailscale on the laptop',
            'chat gpt said no': 'ChatGPT said no',
            'deep seek r1': 'DeepSeek r1',
            'anthropic and open ai': 'Anthropic and OpenAI',
            'start lm studio': 'start LM Studio',
            'web view 2 runtime': 'WebView2 runtime',
            'write it in notion': 'write it in Notion',
        }
        for heard, expected in cases.items():
            with self.subTest(heard=heard):
                self.assertEqual(self.corrector.correct(heard).text, expected)

    def test_reports_what_it_replaced(self):
        result = self.corrector.correct('llama and o llama')
        self.assertEqual(result.text, 'llama and Ollama')
        self.assertEqual([word for _, word, _ in result.matchs], ['Ollama'])

    def test_leaves_ordinary_and_already_correct_text_alone(self):
        for text in ('nothing to fix here at all', 'um so we ship it tomorrow', 'Claude Code is great',
                     'use Codex to review', '', 'a'):
            with self.subTest(text=text):
                result = self.corrector.correct(text)
                self.assertEqual(result.text, text)
                self.assertEqual(result.matchs, [])

    def test_sounds_too_far_away_are_only_suggestions(self):
        result = self.corrector.correct('ask cloud about it')
        self.assertEqual(result.text, 'ask cloud about it')
        self.assertIn('Claude', [word for _, word, _ in result.similars])

    def test_every_occurrence_is_fixed(self):
        self.assertEqual(self.corrector.correct('GitHub GitHub git hub').text, 'GitHub GitHub GitHub')


if __name__ == '__main__':
    unittest.main()
