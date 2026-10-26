# coding: utf-8
"""
Correction history search for AI polish

Finds the person's own corrections (wrong sentence => right sentence) that relate
to a new dictation, and gives them to AI polish as background.

How it works:
1. take the changed fragments (before and after) from each "wrong => right" pair
2. match those fragments against the recognised text
3. return the best-scoring complete corrections
"""

import threading
import time
from pathlib import Path
from typing import List, Tuple, Dict, Set, Optional
from difflib import SequenceMatcher
from dataclasses import dataclass

from .algo_phoneme import get_phoneme_seq, Phoneme
from .algo_calc import fuzzy_substring_distance
from . import logger


@dataclass
class Fragment:
    """
    A changed fragment

    Attributes:
        text: the fragment
        source_text: the whole wrong or right sentence it came from
        start: start position in source_text
        end: end position in source_text
    """
    text: str
    source_text: str
    start: int
    end: int

    def __repr__(self):
        return f"Fragment('{self.text}', pos={self.start}:{self.end})"

def _get_word_boundaries(text: str) -> List[Tuple[int, int, str]]:
    """
    Every word in a text, split at camelCase
    Returns [(start, end, word), ...]
    """
    boundaries = []
    i, n = 0, len(text)
    while i < n:
        if not text[i].isalnum():
            i += 1
            continue
        start = i
        last_was_lower = text[i].islower()
        while i < n and text[i].isalnum():
            if text[i].isupper() and last_was_lower and i > start:
                break
            last_was_lower = text[i].islower()
            i += 1
        boundaries.append((start, i, text[start:i]))
    return boundaries


def _extract_continuous_fragment(bounds: List[Tuple[int, int, str]], start_idx: int, end_idx: int, original_text: str) -> str:
    """The text spanning words start_idx..end_idx (keeping the separators between them)."""
    if start_idx >= end_idx or start_idx >= len(bounds):
        return ""
    return original_text[bounds[start_idx][0] : bounds[end_idx - 1][1]]


def extract_diff_fragments(wrong: str, right: str) -> List[str]:
    """
    The fragments that differ between two sentences (both the wrong and the right version),
    compared word by word
    """
    wrong_bounds = _get_word_boundaries(wrong)
    right_bounds = _get_word_boundaries(right)

    matcher = SequenceMatcher(None, [b[2] for b in wrong_bounds], [b[2] for b in right_bounds])
    fragments: List[Fragment] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag in ('replace', 'delete') and i2 > i1:
            frag_text = _extract_continuous_fragment(wrong_bounds, i1, i2, wrong)
            if frag_text:
                fragments.append(Fragment(frag_text, wrong, wrong_bounds[i1][0], wrong_bounds[i2-1][1]))
        if tag in ('replace', 'insert') and j2 > j1:
            frag_text = _extract_continuous_fragment(right_bounds, j1, j2, right)
            if frag_text:
                fragments.append(Fragment(frag_text, right, right_bounds[j1][0], right_bounds[j2-1][1]))

    result = [frag.text for frag in fragments if get_phoneme_seq(frag.text)]
    return list(dict.fromkeys(result))  # unique, in order


class RectifyRecord:
    """One correction"""
    def __init__(self, wrong: str, right: str, fragments: List[str]):
        self.wrong = wrong
        self.right = right
        self.fragments = fragments
        # Phonemes of each fragment, computed once
        self.fragment_phonemes = {
            f: get_phoneme_seq(f) for f in fragments
        }

    def __repr__(self):
        return f"RectifyRecord('{self.wrong}' => '{self.right}', fragments={self.fragments})"


class RectificationRAG:
    """
    Correction history search

    Loads 'hot-rectify.txt', finds corrections whose changed fragments resemble the
    input, and returns the complete corrections as prompt context.

    File format: blocks separated by ---
    In each block:
    - first line: the original (wrong) text
    - second line: the corrected text
    Lines starting with # and blank lines are ignored
    """

    def __init__(self, rectify_file: str = 'hot-rectify.txt', threshold: float = 0.5):
        """
        Args:
            rectify_file: path of the correction history file
            threshold: similarity threshold (default 0.5)
        """
        self.rectify_file = Path(rectify_file)
        self.threshold = threshold
        self.records: List[RectifyRecord] = []
        self._lock = threading.Lock()

        self.load_history()

    def load_history(self):
        """Load the correction history (format in the class docstring)."""
        if not self.rectify_file.exists():
            # Start from the example next to it (hot-rectify.example.txt), else a commented header
            example = self.rectify_file.with_name(self.rectify_file.stem + '.example' + self.rectify_file.suffix)
            if example.exists():
                self.rectify_file.write_text(example.read_text(encoding='utf-8'), encoding='utf-8')
            else:
                with open(self.rectify_file, 'w', encoding='utf-8') as f:
                    f.write('# Correction history\n')
                    f.write('# Blocks separated by ---\n')
                    f.write('# In each block the first line is the original text, the second the corrected text\n')
                    f.write('# For example:\n')
                    f.write('# ---\n')
                    f.write('# ask cloud code\n')
                    f.write('# ask Claude Code\n')
                return

        try:
            with open(self.rectify_file, 'r', encoding='utf-8') as f:
                content = f.read()

            new_records = []

            blocks = content.split('---')

            start_time = time.time()
            for block in blocks:
                lines = block.strip().split('\n')

                valid_lines = []
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        valid_lines.append(line)

                # Each block needs the original and the corrected text
                if len(valid_lines) >= 2:
                    wrong = valid_lines[0]
                    right = valid_lines[1]

                    if wrong and right:
                        fragments = extract_diff_fragments(wrong, right)
                        if not fragments:
                            # No word-level difference (the whole sentence changed): search with the wrong sentence
                            fragments = [wrong]

                        record = RectifyRecord(wrong, right, fragments)
                        new_records.append(record)
                        logger.debug(f"Loaded correction: '{wrong}' => '{right}', search fragments: {fragments}")

            with self._lock:
                self.records = new_records

            count = len(new_records)
            if count > 0:
                total_fragments = sum(len(r.fragments) for r in new_records)
                logger.debug(f"Loaded {count} corrections, {total_fragments} search fragments, in {time.time() - start_time:.3f}s")
                logger.info(f"Loaded {count} corrections for AI polish")

        except Exception as e:
            logger.error(f"Loading the correction history failed: {e}")

    def _score_record(self, input_phonemes: List[Phoneme], record: RectifyRecord) -> Tuple[float, List[dict]]:
        """Score one correction against the input, with per-fragment details."""
        fragment_details = []
        for fragment, frag_phonemes in record.fragment_phonemes.items():
            if not frag_phonemes: continue

            # fuzzy_substring_distance works on info tuples
            input_info = [p.info for p in input_phonemes]
            frag_info = [p.info for p in frag_phonemes]

            # 1 - normalised edit distance
            min_dist = fuzzy_substring_distance(frag_info, input_info)
            score = 1.0 - (min_dist / len(frag_info))

            fragment_details.append({
                'fragment': fragment,
                'score': round(score, 3),
                'phonemes': len(frag_info)
            })

        if not fragment_details:
            return 0.0, []

        # The correction scores as its best fragment
        fragment_details.sort(key=lambda x: x['score'], reverse=True)
        return fragment_details[0]['score'], fragment_details

    def search(self, text: str, top_k: int = 5) -> List[Tuple[str, str, float]]:
        """Corrections related to a text."""
        if not text or not self.records: return []

        input_phonemes = get_phoneme_seq(text)
        if not input_phonemes: return []

        logger.debug(f"Correction search: input='{text}', phonemes={len(input_phonemes)}")

        with self._lock:
            records = self.records[:]

        matches = []
        for record in records:
            best_score, _ = self._score_record(input_phonemes, record)
            if best_score >= self.threshold:
                matches.append((record.wrong, record.right, round(best_score, 3)))

        matches.sort(key=lambda x: x[2], reverse=True)
        results = matches[:top_k]

        if results:
            logger.debug(f"Correction matches: {results}")
        else:
            logger.debug(f"No correction matched (threshold={self.threshold})")

        return results

    def format_prompt(self, text: str, top_k: int = 5, prefix: str = "Correction history:") -> str:
        """
        Prompt text with the related corrections

        Args:
            text: input text
            top_k: most results
            prefix: heading line

        Returns:
            the prompt section, or an empty string when nothing matched
        """
        logger.debug(f"Correction format_prompt: text='{text}', top_k={top_k}, loaded={len(self.records) if self.records else 0}")

        if not self.records:
            logger.debug("Correction search: no corrections loaded")
            return ""

        results = self.search(text, top_k=top_k)
        if not results:
            logger.debug("Correction search: nothing related found")
            return ""

        lines = [prefix]
        for wrong, right, score in results:
            lines.append(f"- {wrong} => {right}")

        result = "\n".join(lines)
        logger.debug(f"Correction prompt:\n{result}")
        return result

    def search_detailed(self, text: str, top_k: int = 5) -> List[dict]:
        """Corrections related to a text, with per-fragment scores."""
        if not text or not self.records: return []

        input_phonemes = get_phoneme_seq(text)
        if not input_phonemes: return []

        with self._lock:
            records = self.records[:]

        results = []
        for record in records:
            best_score, fragment_details = self._score_record(input_phonemes, record)
            if best_score >= self.threshold:
                results.append({
                    'wrong': record.wrong,
                    'right': record.right,
                    'score': best_score,
                    'fragments': fragment_details
                })

        results.sort(key=lambda x: x['score'], reverse=True)
        return results[:top_k]
