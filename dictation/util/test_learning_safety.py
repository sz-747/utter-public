import unittest
from util.client.learn.edits import plan
from util.client.learn.rule_safety import guarded_learned_rules
from util.hotword.hot_rule import RuleCorrector
from util.hotword.hot_phoneme import PhonemeCorrector


class LearningSafetyTests(unittest.TestCase):
    def test_old_learned_rules_do_not_rewrite_valid_english(self):
        learned, skipped = guarded_learned_rules(r'\bscale\b = skill' + '\n' + r'\bArt\b = Utter' + '\n'
                                                 + r'\bcodec\b = Codex' + '\n' + r'\bKodex\b = Codex')
        corrector = RuleCorrector()
        corrector.update_rules(learned)
        for text in ['We need to scale the audio codec service.', 'Art and music are different.']:
            self.assertEqual(corrector.substitute(text), text)
        self.assertEqual(corrector.substitute('Use Kodex.'), 'Use Codex.')
        self.assertEqual(set(skipped), {'scale', 'Art', 'codec'})

    def test_manual_rule_stays_authoritative(self):
        learned, _ = guarded_learned_rules(r'\bArt\b = Utter')
        corrector = RuleCorrector()
        corrector.update_rules(r'\bArt\b = Utter' + '\n' + learned)
        self.assertEqual(corrector.substitute('Art settings'), 'Utter settings')

    def test_new_learning_keeps_name_without_global_ordinary_word_rule(self):
        self.assertEqual(plan('scale', 'Skillify', set(), lambda *_: False), {'word': 'Skillify', 'rule': None})
        self.assertEqual(plan('Kodex', 'Codex', set(), lambda *_: False)['rule'], ('Kodex', 'Codex'))

    def test_fuzzy_matching_preserves_codec_but_retains_contextual_hint(self):
        corrector = PhonemeCorrector(threshold=0.85, similar_threshold=0.6, rare_threshold=0.75)
        corrector.update_hotwords('Codex\nUtter\nSkillify')
        result = corrector.correct('We need to scale the audio codec service.')
        self.assertEqual(result.text, 'We need to scale the audio codec service.')
        self.assertTrue(any(origin == 'codec' and word == 'Codex' for origin, word, _ in result.similars))


if __name__ == '__main__':
    unittest.main()
