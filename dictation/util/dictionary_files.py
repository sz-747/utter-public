"""Read and edit the dictionary files the hotword engine loads.

The text files stay the single source of truth:
  hot.txt               words you added (fuzzy-matched, phoneme RAG)
  hot-learned.txt       words learned from your edits
  hot-rule.txt          replacement rules you added ("pattern = replacement")
  hot-rule-learned.txt  exact replacements learned from your edits
Edits keep comments, other lines and the file's line endings untouched.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_HEADERS = {
    'hot-learned.txt': '# Words Utter learned from your corrections. One per line.\n'
                       '# Remove a line (or use the Dictionary page) to forget a word.\n',
    'hot-rule-learned.txt': '# Exact replacements Utter learned from your corrections.\n'
                            '# Format: heard = corrected\n',
}


def paths(root=None):
    root = Path(root) if root else ROOT
    return {
        'words': root / 'hot.txt',
        'learned_words': root / 'hot-learned.txt',
        'rules': root / 'hot-rule.txt',
        'learned_rules': root / 'hot-rule-learned.txt',
    }


def _read_lines(path):
    path = Path(path)
    if not path.exists():
        return [], '\n'
    raw = path.read_bytes().decode('utf-8')
    newline = '\r\n' if '\r\n' in raw else '\n'
    return raw.splitlines(), newline


def _write_lines(path, lines, newline):
    Path(path).write_bytes((newline.join(lines) + newline).encode('utf-8'))


def _is_entry(line):
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith('#')


def read_words(path):
    lines, _ = _read_lines(path)
    return [line.strip() for line in lines if _is_entry(line)]


def add_word(path, word):
    word = word.strip()
    if not word or word.startswith('#') or '\n' in word:
        raise ValueError('A dictionary word must be one line and cannot start with #')
    if word in read_words(path):
        return False
    path = Path(path)
    lines, newline = _read_lines(path)
    if not path.exists() and path.name in _HEADERS:
        lines = _HEADERS[path.name].splitlines()
    _write_lines(path, lines + [word], newline)
    return True


def remove_word(path, word):
    lines, newline = _read_lines(path)
    kept = [line for line in lines if not (_is_entry(line) and line.strip() == word)]
    if len(kept) == len(lines):
        return False
    _write_lines(path, kept, newline)
    return True


# -- replacement rules ----------------------------------------------------

def literal_pattern(heard):
    """Regex that matches `heard` literally, as whole words where it starts/ends with a letter."""
    pattern = re.escape(heard.strip())
    if re.match(r'[A-Za-z0-9_]', heard.strip()):
        pattern = r'\b' + pattern
    if re.search(r'[A-Za-z0-9_]$', heard.strip()):
        pattern += r'\b'
    return pattern


def literal_text(pattern):
    """The plain text a rule pattern matches, or None for a real regular expression."""
    core = pattern
    if core.startswith(r'\b'):
        core = core[2:]
    if core.endswith(r'\b') and not core.endswith(r'\\b'):
        core = core[:-2]
    text = re.sub(r'\\(.)', r'\1', core)
    return text if text and re.escape(text) == core else None


def _parse_rule(line):
    if line.rstrip().endswith(' =') and line.count(' = ') == 0:   # same as RuleCorrector: empty replacement
        line = line.rstrip() + ' '
    parts = line.split(' = ')
    if len(parts) != 2:
        return None
    pattern, replacement = parts[0].strip(), parts[1].strip()
    return {'pattern': pattern, 'replacement': replacement, 'heard': literal_text(pattern)}


def read_rules(path):
    lines, _ = _read_lines(path)
    rules = []
    for line in lines:
        if line.startswith('#') or not line.strip():
            continue
        rule = _parse_rule(line)
        if rule:
            rules.append(rule)
    return rules


def add_rule(path, heard, replacement):
    heard, replacement = heard.strip(), replacement.strip()
    if not heard or ' = ' in heard or ' = ' in replacement or '\n' in heard + replacement:
        raise ValueError('Replacements must be single lines and cannot contain " = "')
    pattern = literal_pattern(heard)
    if any(rule['pattern'] == pattern for rule in read_rules(path)):
        return False
    path = Path(path)
    lines, newline = _read_lines(path)
    if not path.exists() and path.name in _HEADERS:
        lines = _HEADERS[path.name].splitlines()
    _write_lines(path, lines + [f'{pattern} = {replacement}'], newline)
    return True


def remove_rule(path, pattern):
    lines, newline = _read_lines(path)
    kept = []
    removed = False
    for line in lines:
        rule = None if line.startswith('#') else _parse_rule(line)
        if rule and rule['pattern'] == pattern:
            removed = True
            continue
        kept.append(line)
    if removed:
        _write_lines(path, kept, newline)
    return removed


def all_words(root=None):
    p = paths(root)
    return set(read_words(p['words'])) | set(read_words(p['learned_words']))


def ordered_words(root=None):
    """Your words, then learned ones, each once, in file order."""
    p = paths(root)
    return list(dict.fromkeys(read_words(p['words']) + read_words(p['learned_words'])))
