import unittest

from util.llm.llm_cleanup_guard import plain_dashes, validate_cleanup_output


class CleanupGuardTests(unittest.TestCase):
    def test_accepts_shorter_polished_transcript(self):
        source = "Um, so, I think this plan, uh, can basically just use the existing API to get it done."
        candidate = "I think this plan can just use the existing API to get it done."

        result = validate_cleanup_output(source, candidate)

        self.assertTrue(result.accepted)
        self.assertEqual(result.text, candidate)

    def test_rejects_expanded_answer(self):
        source = "I want to switch to reading mode on English web pages and translate the whole page."
        candidate = source + " Below is a complete browser extension plan with implementation steps and deployment advice." * 4

        result = validate_cleanup_output(source, candidate)

        self.assertFalse(result.accepted)
        self.assertEqual(result.text, source)
        self.assertIn("expanded unexpectedly", result.reason)

    def test_rejects_structured_answer_even_when_length_is_close(self):
        source = "Please write this idea down, I still need to think about how to build it."
        candidate = "1. Write down the idea\n2. Think about how to build it"

        result = validate_cleanup_output(source, candidate)

        self.assertFalse(result.accepted)
        self.assertEqual(result.text, source)
        self.assertIn("structured answer", result.reason)

    def test_rejects_answer_phrase(self):
        source = "Let's talk about this sync problem later, I haven't thought it through yet."
        for candidate in (
            "Here's a breakdown: let's talk about this sync problem later.",
            "Here are some options: talk about this sync problem later.",
            "I’d suggest we talk about this sync problem later.",
            "Let's talk about this sync problem later. Let me know if that works.",
        ):
            with self.subTest(candidate=candidate):
                result = validate_cleanup_output(source, candidate)

                self.assertFalse(result.accepted)
                self.assertEqual(result.text, source)
                self.assertIn("answer-style wording", result.reason)

    def test_answer_phrase_already_in_source_is_allowed(self):
        source = "um I'd suggest we ship it on Friday"
        candidate = "I'd suggest we ship it on Friday."

        result = validate_cleanup_output(source, candidate)

        self.assertTrue(result.accepted)
        self.assertEqual(result.text, candidate)

    def test_empty_output_falls_back_to_original(self):
        result = validate_cleanup_output("ship it on Friday", "  ")

        self.assertFalse(result.accepted)
        self.assertEqual(result.text, "ship it on Friday")


class StaysCloseToOriginalTests(unittest.TestCase):
    # A rambling dictation with a restart and a stutter, and cleanups of it
    SOURCE = ("I wrote, I set up the the the the weekly report template for my team in Notion when we would have "
              "several projects in one kind of sprint. So you use that template and continuously update that template "
              "and make this whole process faster and continually improving.")

    def test_minimal_cleanup_is_accepted(self):
        candidate = ("I set up the weekly report template for my team in Notion when we would have several "
                     "projects in one kind of sprint. So you use that template and continuously update that template "
                     "and make this whole process faster and continually improving.")
        self.assertTrue(validate_cleanup_output(self.SOURCE, candidate).accepted)

    def test_rewording_falls_back_to_original(self):
        candidate = ("I used to set up the weekly report template for teams in Notion whenever we had several "
                     "projects in a single sprint. So use that template, keep updating it, and make the whole "
                     "process quicker and always improving.")
        result = validate_cleanup_output(self.SOURCE, candidate)
        self.assertFalse(result.accepted)
        self.assertEqual(result.text, self.SOURCE)
        self.assertIn("rewrote too much", result.reason)

    def test_summarising_falls_back_to_original(self):
        result = validate_cleanup_output(self.SOURCE, "I set up the weekly report template.")
        self.assertFalse(result.accepted)
        self.assertIn("deleted too much", result.reason)


class PlainDashTests(unittest.TestCase):
    def test_em_dashes_become_hyphens(self):
        # A model that sets off an aside with em dashes
        source = "I think the difficulty with the current plan, something the next release will address, is the fact"
        candidate = "I think the difficulty with the current plan—something the next release will address—is the fact"
        result = validate_cleanup_output(source, candidate)
        self.assertTrue(result.accepted)
        self.assertEqual(result.text, "I think the difficulty with the current plan - something the "
                                      "next release will address - is the fact")

    def test_ranges_and_hyphens_stay(self):
        self.assertEqual(plain_dashes("about 0.3–0.6 s, a well-known case"), "about 0.3–0.6 s, a well-known case")
        self.assertEqual(plain_dashes("ship it – then test"), "ship it - then test")
        self.assertEqual(plain_dashes("put simply——that's it"), "put simply - that's it")


if __name__ == "__main__":
    unittest.main()
