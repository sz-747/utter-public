"""Keep an inferred word correction from becoming an unconditional rewrite of an ordinary word."""
from util import dictionary_files
from util.hotword.hot_phoneme import is_common_english_word


def guarded_learned_rules(text):
    """Return usable learned rule text and ambiguous sources held back; never edit files.

    Manual hot-rule.txt is deliberately outside this guard. Learned terms still enter
    the speech model's dictionary and contextual polish, where surrounding words can disambiguate.
    """
    kept, skipped = [], []
    for line in text.splitlines():
        parts = line.split(' = ', 1)
        heard = dictionary_files.literal_text(parts[0].strip()) if len(parts) == 2 and not line.lstrip().startswith('#') else None
        if heard and is_common_english_word(heard):
            skipped.append(heard)
        else:
            kept.append(line)
    return '\n'.join(kept), skipped
