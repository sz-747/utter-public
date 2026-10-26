# coding: utf-8
"""
Dictionary correction by phoneme matching (RAG)

Fuzzy matching on phoneme edit distance replaces misheard words with dictionary words.
"""

import logging
import os
import time
import threading
from typing import List, Tuple, Dict, Set, Optional, NamedTuple
from collections import defaultdict
from pathlib import Path

from .algo_phoneme import get_phoneme_info, Phoneme
from .rag_fast import FastRAG
from .algo_calc import fuzzy_substring_search_constrained

from . import logger


class MatchResult(NamedTuple):
    start: int
    end: int
    score: float
    hotword: str


class CorrectionResult(NamedTuple):
    """The corrected text and the dictionary words that matched"""
    text: str                           # corrected text
    matchs: List[Tuple[str, str, float]]  # [(heard, dictionary word, score), ...]
    similars: List[Tuple[str, str, float]]  # [(heard, dictionary word, score), ...]



class PhonemeCorrector:
    """
    Phoneme corrector

    Two-stage search:
    1. FastRAG coarse filter: an inverted index (and Numba JIT when available) narrows the candidates
    2. Fine matching: boundary-constrained fuzzy search on each candidate

    The inverted index skips most of the work, so it suits dictionaries of any size.
    Spans whose similarity passes the threshold are replaced with the dictionary word.
    """

    def __init__(self, threshold: float = 0.7, similar_threshold: float = None):
        self.threshold = threshold
        self.similar_threshold = similar_threshold if similar_threshold is not None else threshold - 0.2

        self.max_diff = 2             # largest phoneme difference allowed in sliding-window matching
        self.top_k_candidates = 100   # candidates kept by the coarse filter

        self.hotwords: Dict[str, List[Phoneme]] = {}
        self.fast_rag = FastRAG(threshold=min(self.threshold, self.similar_threshold) - 0.1)
        self._lock = threading.Lock()

    def update_hotwords(self, hotword_text: str) -> int:
        """Replace the dictionary (thread-safe)."""
        start_time = time.time()

        lines = [line.strip() for line in hotword_text.splitlines() if line.strip() and not line.strip().startswith('#')]

        new_hotwords = {}
        for hw in lines:
            phons = get_phoneme_info(hw)
            if phons:
                new_hotwords[hw] = phons

        with self._lock:
            self.hotwords = new_hotwords
            self.fast_rag = FastRAG(threshold=min(self.threshold, self.similar_threshold) - 0.1)
            self.fast_rag.add_hotwords(new_hotwords)

        logger.debug(f"PhonemeCorrector loaded {len(new_hotwords)} dictionary words in {time.time() - start_time:.3f}s")
        return len(new_hotwords)

    def _find_matches(self, text: str, fast_results: List, input_processed: List[Tuple]) -> Tuple[List[MatchResult], List[Tuple[str, str, float]]]:
        """Fine matching: boundary-constrained fuzzy search."""
        matches = []
        similars = []

        for hw, fast_score in fast_results:
            hw_phonemes = self.hotwords[hw]
            hw_compare = [p.info[:5] for p in hw_phonemes]

            # Search the whole input for spans on word boundaries. The looser threshold
            # makes sure borderline matches still reach the similar list.
            search_threshold = min(self.threshold, self.similar_threshold) - 0.1

            found_segments = fuzzy_substring_search_constrained(hw_compare, input_processed, threshold=search_threshold)

            for score, start_phon_idx, end_phon_idx in found_segments:
                # Character positions straight from input_processed
                char_start = input_processed[start_phon_idx][5]
                char_end = input_processed[end_phon_idx-1][6]

                res = MatchResult(char_start, char_end, score, hw)
                origin_val = text[char_start:char_end]

                if score >= self.threshold:
                    matches.append(res)

                # Everything above the similarity threshold is a suggestion
                if score >= self.similar_threshold:
                    similars.append((origin_val, hw, score))

        # One suggestion per dictionary word, best score first, then longest
        final_similars = []
        seen_hw = set()

        similars.sort(key=lambda x: (x[2], len(x[1])), reverse=True)

        for origin, hw, score in similars:
            if hw not in seen_hw:
                final_similars.append((origin, hw, score))
                seen_hw.add(hw)

        return matches, final_similars

    def _resolve_and_replace(self, text: str, matches: List[MatchResult]) -> Tuple[str, List[Tuple[str, float]], List[Tuple[str, float]]]:
        """Resolve overlapping matches and replace the text."""
        # Highest score first, then the longest span
        matches.sort(key=lambda x: (x.score, x.end - x.start), reverse=True)

        final_matches = []
        all_matched_info = []
        occupied_ranges = []

        seen_hw_score = set()
        for m in matches:
            if (m.hotword, m.score) not in seen_hw_score:
                all_matched_info.append((m.hotword, m.score))
                seen_hw_score.add((m.hotword, m.score))

            if m.score < self.threshold: continue

            is_overlap = False
            for r_start, r_end in occupied_ranges:
                if not (m.end <= r_start or m.start >= r_end):
                    is_overlap = True
                    break

            if not is_overlap:
                # Skip replacements that change nothing
                if text[m.start : m.end] != m.hotword:
                    final_matches.append(m)
                occupied_ranges.append((m.start, m.end))

        final_matches.sort(key=lambda x: x.start, reverse=True)
        result_list = list(text)
        for m in final_matches:
            result_list[m.start : m.end] = list(m.hotword)

        return "".join(result_list), [(text[m.start:m.end], m.hotword, m.score) for m in final_matches], all_matched_info

    def correct(self, text: str, k: int = 10) -> CorrectionResult:
        """
        Correct a text

        Args:
            text: input text
            k: how many related dictionary words to return as suggestions
        """
        if not text or not self.hotwords:
            return CorrectionResult(text=text, matchs=[], similars=[])

        # 1. Phonemes with positions
        input_phonemes = get_phoneme_info(text)
        if not input_phonemes:
            return CorrectionResult(text=text, matchs=[], similars=[])

        # 2. Search and match
        with self._lock:
            # Coarse filter
            fast_results = self.fast_rag.search(input_phonemes, top_k=100)
            logger.debug(f"Dictionary candidates: {len(fast_results)}")

            # Input as info tuples: (value, kind, word start, word end, unused, char start, char end)
            input_processed = [p.info for p in input_phonemes]

            # Fine matching
            matches, similars = self._find_matches(text, fast_results, input_processed)

        # 3. Resolve overlaps and replace
        new_text, final_hw_info, all_hw_info = self._resolve_and_replace(text, matches)

        return CorrectionResult(text=new_text, matchs=final_hw_info, similars=similars[:k])
