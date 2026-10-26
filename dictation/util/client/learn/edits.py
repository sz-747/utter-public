"""Find word corrections the user made to dictated text, and decide what to learn.

Only distinctive words are learned (names, brands, acronyms, mixed case or
digits), and only when the corrected word still resembles what was heard, so
ordinary rewording never enters the dictionary.
"""
import re
from difflib import SequenceMatcher

_WORD = re.compile(r"[A-Za-z0-9]+(?:['’\-.][A-Za-z0-9]+)*")
_MAX_HEARD_WORDS = 3
_MAX_CORRECTED_WORDS = 2
_MAX_CORRECTIONS = 3


def normalize_newlines(text):
    return (text or '').replace('\r\n', '\n').replace('\r', '\n')


def _letters(text):
    return re.sub(r'[^0-9a-z]', '', text.lower())


def _common_prefix(a, b):
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i


def _common_suffix(a, b, limit):
    i = 0
    while i < limit and a[-1 - i] == b[-1 - i]:
        i += 1
    return i


def _sentence_start(text, pos):
    before = text[:pos].rstrip(' \t"\'(')
    return not before or before[-1] in '.!?\n:'


def is_distinctive(word, text, pos):
    """True for words the speech model is unlikely to know: names, brands, acronyms."""
    tokens = word.split()
    if any(ch.isdigit() for ch in word):
        return True
    if any(any(ch.isupper() for ch in token[1:]) for token in tokens):
        return True  # GitHub, NASA, iPhone
    return word[:1].isupper() and not _sentence_start(text, pos)  # a mid-sentence proper noun


def find_corrections(before, start, inserted, after):
    """
    Compare the field text right after dictation (`before`, dictated text at
    `start`) with a later snapshot (`after`). Returns [(heard, corrected)].
    An empty list means no learnable edit, including heavy rewrites.
    """
    end = start + len(inserted)
    prefix = min(_common_prefix(before, after), start)
    tail = len(before) - end
    suffix = _common_suffix(before, after, min(tail, len(after) - prefix))
    old_region = before[prefix:len(before) - suffix]
    new_region = after[prefix:len(after) - suffix]
    if old_region == new_region:
        return []

    old = list(_WORD.finditer(old_region))
    new = list(_WORD.finditer(new_region))
    if not old:
        return []
    matcher = SequenceMatcher(None, [m.group(0) for m in old], [m.group(0) for m in new], autojunk=False)
    opcodes = matcher.get_opcodes()
    # Most dictated words must survive; otherwise this is a rewrite, not a fix.
    # (Text typed after the dictation shows up as inserts and is ignored.)
    removed = sum(i2 - i1 for op, i1, i2, _, _ in opcodes if op in ('replace', 'delete'))
    if removed > max(_MAX_HEARD_WORDS, 0.5 * len(_WORD.findall(inserted))):
        return []

    corrections = []
    for op, i1, i2, j1, j2 in opcodes:
        if op != 'replace':
            continue
        if not (1 <= i2 - i1 <= _MAX_HEARD_WORDS and 1 <= j2 - j1 <= _MAX_CORRECTED_WORDS):
            continue
        heard = old_region[old[i1].start():old[i2 - 1].end()]
        corrected = new_region[new[j1].start():new[j2 - 1].end()]
        position = prefix + new[j1].start()
        if _worth_learning(heard, corrected, after, position):
            corrections.append((heard, corrected))
    return corrections if len(corrections) <= _MAX_CORRECTIONS else []


def _worth_learning(heard, corrected, text, pos):
    a, b = _letters(heard), _letters(corrected)
    if len(b) < 3 or b.isdigit():
        return False
    if a == b:
        # Only a casing change: learn it when the new casing is unusual.
        return heard != corrected and is_distinctive(corrected, text, pos)
    if SequenceMatcher(None, a, b).ratio() < 0.5:
        return False
    return is_distinctive(corrected, text, pos)


def plan(heard, corrected, known_words, fuzzy_fixes):
    """
    What to add for one correction.
      known_words: words already in the dictionary
      fuzzy_fixes(heard, word) -> bool: would the fuzzy matcher, given `word`,
        already turn `heard` into it?
    Returns {'word': str|None, 'rule': (heard, corrected)|None}.
    """
    word = None if corrected in known_words else corrected
    rule = None if fuzzy_fixes(heard, corrected) else (heard, corrected)
    return {'word': word, 'rule': rule}
