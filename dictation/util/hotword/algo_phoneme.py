# coding: utf-8
"""
Phonemes

Turns text into phoneme sequences for dictionary matching. English words and
numbers are the units; matching works on their letters.
"""

import re
from typing import List, Tuple, Literal
from dataclasses import dataclass
from . import logger


@dataclass(frozen=True)
class Phoneme:
    """
    A phoneme with its kind

    Attributes:
        value: the phoneme ('python', '4', or one letter)
        lang: kind ('en' = letters, 'num' = digits, 'other' = anything else)
        is_word_start: the phoneme starts a word
        is_word_end: the phoneme ends a word
        char_start: start index in the original text
        char_end: end index in the original text
    """
    value: str
    lang: Literal['en', 'num', 'other']
    is_word_start: bool = False
    is_word_end: bool = False
    char_start: int = 0
    char_end: int = 0

    @property
    def is_english(self) -> bool:
        return self.lang == 'en'

    @property
    def info(self) -> Tuple[str, str, bool, bool, bool, int, int]:
        """(value, kind, word start, word end, False, char start, char end); the fifth field is kept for older callers"""
        return (self.value, self.lang, self.is_word_start, self.is_word_end, False, self.char_start, self.char_end)

    def __str__(self) -> str:
        return self.value

    def __repr__(self) -> str:
        return f"Phoneme({self.value}, {self.lang}, start={self.is_word_start}, end={self.is_word_end})"



def normalize_text(text: str) -> str:
    """
    Normalise text: split camelCase, turn separators into spaces, lowercase

    So that:
    - `BrightLoop` -> `bright loop`
    - `iPhone15Pro` -> `iphone 15 pro`
    - `7-Zip` / `7 zip` -> `7 zip`
    """
    result = []
    prev_char = ''

    for char in text:
        if char.isalnum():
            # camelCase: a space before an upper-case letter that follows a lower-case one
            if char.isupper() and prev_char.islower():
                result.append(' ')
            # letter/digit boundaries
            elif char.isdigit() and prev_char.isalpha():
                result.append(' ')
            elif char.isalpha() and prev_char.isdigit():
                result.append(' ')

            result.append(char.lower())
            prev_char = char
        else:
            # Anything else separates words
            if result and result[-1] != ' ':
                result.append(' ')
            prev_char = ''

    return ''.join(result).strip()


def split_mixed_label(input_str: str) -> List[str]:
    """
    Split a string into tokens

    Rules:
    - an English word is one token
    - a number is one token
    - any other character is a token of its own

    Examples:
    - "hello world" -> ['hello', 'world']
    - "iphone15" -> ['iphone', '15']
    - "7zip" -> ['7', 'zip']
    """
    tokens = []
    s = input_str.lower()

    while len(s) > 0:
        if s[0] == ' ':
            s = s[1:]
            continue

        # ASCII letters
        match = re.match(r'[a-z]+', s)
        if match:
            tokens.append(match.group(0))
            s = s[len(match.group(0)):]
            continue

        # Digits
        match = re.match(r'[0-9]+', s)
        if match:
            tokens.append(match.group(0))
            s = s[len(match.group(0)):]
            continue

        # Anything else, one character at a time
        tokens.append(s[0])
        s = s[1:]

    return tokens


def get_phoneme_seq(text: str, ascii_split_char: bool = False) -> List[Phoneme]:
    """
    Phoneme sequence of a text
    """
    normalized = normalize_text(text)

    phoneme_seq: List[Phoneme] = []
    for token in split_mixed_label(normalized):
        if re.match(r'^[a-z0-9]+$', token):
            lang = 'num' if token.isdigit() else 'en'
            if ascii_split_char:
                phoneme_seq.extend([Phoneme(c, lang, is_word_start=True, is_word_end=True) for c in token])
            else:
                phoneme_seq.append(Phoneme(token, lang, is_word_start=True, is_word_end=True))
            continue

        phoneme_seq.append(Phoneme(token, 'other', is_word_start=True, is_word_end=True))

    return phoneme_seq


def get_phoneme_info(text: str, ascii_split_char: bool = True) -> List[Phoneme]:
    """
    Phoneme sequence with positions and kinds
    """
    phoneme_seq: List[Phoneme] = []
    pos = 0
    while pos < len(text):
        char = text[pos]

        if 'a' <= char.lower() <= 'z' or '0' <= char <= '9':
            # English letters and digits (ASCII only)
            pos = _process_en_num(text, pos, phoneme_seq, ascii_split_char)
        else:
            # Spaces, punctuation and other characters are skipped so the phonemes stay continuous
            pos += 1

    return phoneme_seq


def _process_en_num(text: str, pos: int, seq: List[Phoneme], split_char: bool) -> int:
    """One run of letters or digits, split at camelCase and letter/digit boundaries"""
    start_pos = pos
    while pos < len(text):
        char = text[pos]
        low_char = char.lower()
        if not ('a' <= low_char <= 'z' or '0' <= char <= '9'): break

        # Boundaries: camelCase aA, letter-digit a1, digit-letter 1a
        if pos > start_pos:
            prev = text[pos-1]
            if (prev.islower() and char.isupper()) or \
               (prev.isalpha() and char.isdigit()) or \
               (prev.isdigit() and char.isalpha()):
                break
        pos += 1

    end_pos = pos
    token = text[start_pos:end_pos].lower()
    lang = 'num' if token.isdigit() else 'en'

    if split_char:
        for i, c in enumerate(token):
            seq.append(Phoneme(c, lang, is_word_start=(i==0), is_word_end=(i==len(token)-1),
                               char_start=start_pos+i, char_end=start_pos+i+1))
    else:
        seq.append(Phoneme(token, lang, is_word_start=True, is_word_end=True,
                           char_start=start_pos, char_end=end_pos))
    return end_pos
