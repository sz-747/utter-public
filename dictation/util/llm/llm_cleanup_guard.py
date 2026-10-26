"""Output guard for the default transcript cleanup.

The default role only edits the original transcript. If the model expands it into an answer
or a technical plan, fall back to the original text so runaway output is never typed into the
app that has focus.
"""

import math
import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from util.text_metrics import tokenize


@dataclass(frozen=True)
class CleanupValidation:
    text: str
    accepted: bool
    reason: str = ""


# Lower-case, with straight apostrophes; matched case-insensitively against the output.
_ANSWER_PHRASES = (
    "here's a breakdown",
    "here is a breakdown",
    "broken down into the following",
    "here are some options",
    "here are a few options",
    "here's an approach",
    "here is an approach",
    "here's a solution",
    "here is a solution",
    "the solution is as follows",
    "i'd suggest",
    "i would suggest",
    "i recommend",
    "let me know if",
    "would you like me to",
    "do you want me to",
)


def is_default_cleanup_role(role_config) -> bool:
    """Only the default role (no prefix) is the automatic transcript cleanup."""
    return not str(getattr(role_config, "name", "") or "").strip()


def validate_cleanup_output(source: str, candidate: str) -> CleanupValidation:
    """Accept a reasonable cleanup; fall back to the original on runaway expansion or an answer."""
    source = (source or "").strip()
    candidate = (candidate or "").strip()

    if not candidate:
        return CleanupValidation(source, False, "model returned empty text")

    # Punctuation and proper-noun fixes can add a few characters, but a cleanup should never be much longer than the original.
    max_length = max(len(source) + 20, math.ceil(len(source) * 1.15))
    if len(candidate) > max_length:
        return CleanupValidation(
            source,
            False,
            f"output expanded unexpectedly (input {len(source)} characters, output {len(candidate)} characters)",
        )

    # ASR text rarely contains Markdown. Several structure markers mean the model started writing its own answer.
    source_has_structure = _has_answer_structure(source)
    if not source_has_structure and _has_answer_structure(candidate):
        return CleanupValidation(source, False, "output turned into a structured answer")

    source_folded = _fold(source)
    candidate_folded = _fold(candidate)
    if any(phrase in candidate_folded and phrase not in source_folded for phrase in _ANSWER_PHRASES):
        return CleanupValidation(source, False, "output contains answer-style wording")

    # A cleanup should be almost exactly what was said: it may drop fillers and restarts, but must not
    # reword or cut large parts
    added, deleted_share = _edit_amounts(source, candidate)
    if added > max(_MAX_NEW_WORDS, _MAX_NEW_SHARE * len(tokenize(candidate))):
        return CleanupValidation(source, False, f"output rewrote too much ({added} words added or replaced)")
    if deleted_share > _MAX_DELETED_SHARE:
        return CleanupValidation(source, False, f"output deleted too much ({deleted_share:.0%} of the words removed)")

    return CleanupValidation(plain_dashes(candidate), True)


def _fold(text: str) -> str:
    return text.lower().replace("’", "'")


# No em dashes in dictated text; the model still adds them, so replace any that are left.
_DASH = re.compile(r"\s*—+\s*|\s+–\s+")


def plain_dashes(text: str) -> str:
    """Em dashes (and spaced en dashes) become ' - '; number ranges like 0.3–0.6 stay."""
    return _DASH.sub(" - ", text).strip()


# Calibrated on sample dictations: a minimal-edit cleanup adds 0-3 words of its
# own (misheard-name fixes) and deletes up to ~20% (fillers, stutters, restarts).
_MAX_NEW_WORDS = 3
_MAX_NEW_SHARE = 0.06
_MAX_DELETED_SHARE = 0.45


def _edit_amounts(source: str, candidate: str):
    """(words the model added or substituted, share of source words it deleted); case-insensitive."""
    a = [t.lower() for t in tokenize(source)]
    b = [t.lower() for t in tokenize(candidate)]
    added = deleted = 0
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op in ("replace", "insert"):
            added += j2 - j1
        if op in ("replace", "delete"):
            deleted += i2 - i1
    return added, deleted / max(len(a), 1)


def _has_answer_structure(text: str) -> bool:
    heading_count = len(re.findall(r"(?m)^\s*#{1,6}\s+", text))
    bullet_count = len(re.findall(r"(?m)^\s*[-*]\s+", text))
    numbered_count = len(re.findall(r"(?m)^\s*\d+\.\s*", text))
    return (
        heading_count > 0
        or bullet_count >= 2
        or numbered_count >= 2
        or text.count("**") >= 4
        or len(re.findall(r"(?m)^\s*---+\s*$", text)) > 0
    )
