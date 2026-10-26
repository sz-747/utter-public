"""Word counting and word-level diffs shared by the client and the desktop app."""
import re
from difflib import SequenceMatcher

# Words may contain apostrophes or hyphens.
_TOKEN = re.compile(r"[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*")


def tokenize(text):
    return _TOKEN.findall(text or '')


def count_words(text):
    return len(tokenize(text))


def changed_words(before, after):
    """Number of words in `after` that were inserted or rewritten relative to `before`."""
    a, b = tokenize(before), tokenize(after)
    changed = 0
    for op, i1, i2, j1, j2 in SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == 'replace':
            changed += max(i2 - i1, j2 - j1)
        elif op == 'insert':
            changed += j2 - j1
        elif op == 'delete':
            changed += i2 - i1
    return changed
