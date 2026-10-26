import unittest

from util.hotword.hot_phoneme import PhonemeCorrector, has_uncommon_word

WORDS = 'Codex\nskill\nHerdr\nCline\n'


def corrector(rare=None):
    c = PhonemeCorrector(threshold=0.85, similar_threshold=0.6, rare_threshold=rare)
    c.update_hotwords(WORDS)
    return c


class UncommonWordTests(unittest.TestCase):
    def test_misheard_names_are_uncommon(self):
        for heard in ('Kodex', 'Herda', 'MCPP', 'Roblox copy'):
            self.assertTrue(has_uncommon_word(heard), heard)

    def test_everyday_words_are_common(self):
        for heard in ('still', 'Claude code', 'open a', 'one line', 'sessions'):
            self.assertFalse(has_uncommon_word(heard), heard)


class RareThresholdTests(unittest.TestCase):
    def test_uncommon_word_is_replaced_at_the_lower_threshold(self):
        self.assertEqual(corrector(0.75).correct('Cause if Kodex tells Pi').text, 'Cause if Codex tells Pi')
        self.assertEqual(corrector(0.75).correct('make a new terminal in Herda').text, 'make a new terminal in Herdr')

    def test_everyday_words_keep_the_full_threshold(self):
        for text in ('there seems to still be a gap', 'if it is just one line', 'Since Claude code might differ'):
            self.assertEqual(corrector(0.75).correct(text).text, text)

    def test_without_a_rare_threshold_nothing_changes(self):
        self.assertEqual(corrector().correct('Cause if Kodex tells Pi').text, 'Cause if Kodex tells Pi')


if __name__ == '__main__':
    unittest.main()
