# coding: utf-8
"""
Fast dictionary search

Speeds up the search with:
1. Numba JIT for the core DP algorithm (when Numba is installed)
2. An inverted index on leading phonemes to cut the candidates
3. A length filter that skips impossible matches
"""

import numpy as np
from typing import List, Dict, Tuple, Set, Union
from collections import defaultdict
import time
from . import logger

try:
    from numba import jit, njit
    import numba
    HAS_NUMBA = True
    logger.debug("Numba available; using JIT")
except ImportError:
    HAS_NUMBA = False
    logger.debug("Numba not available; using plain Python")


# =============================================================================
# Numba version
# =============================================================================

if HAS_NUMBA:
    @njit(cache=True)
    def _fuzzy_substring_distance_numba(main_codes: np.ndarray, sub_codes: np.ndarray) -> float:
        """
        Fuzzy substring distance, compiled with Numba

        Works on integer codes instead of strings for speed.
        """
        n = len(sub_codes)
        m = len(main_codes)

        if n == 0 or m == 0:
            return float(n)

        dp = np.zeros((n + 1, m + 1), dtype=np.float32)

        for i in range(1, n + 1):
            dp[i, 0] = float(i)

        for i in range(1, n + 1):
            for j in range(1, m + 1):
                # same = 0, different = 1
                if sub_codes[i-1] == main_codes[j-1]:
                    cost = 0.0
                else:
                    cost = 1.0

                dp[i, j] = min(
                    dp[i-1, j] + 1.0,       # deletion
                    dp[i, j-1] + 1.0,       # insertion
                    dp[i-1, j-1] + cost     # substitution/match
                )

        min_dist = dp[n, 1]
        for j in range(2, m + 1):
            if dp[n, j] < min_dist:
                min_dist = dp[n, j]

        return min_dist


# =============================================================================
# Phoneme encoder (string -> integer)
# =============================================================================

from .algo_phoneme import Phoneme

class PhonemeEncoder:
    """Encodes phoneme strings as integers for Numba"""

    def __init__(self):
        self.phoneme_to_code: Dict[str, int] = {}
        self.code_to_phoneme: Dict[int, str] = {}
        self.next_code = 1  # 0 is reserved

    def encode(self, phoneme: str) -> int:
        if phoneme not in self.phoneme_to_code:
            self.phoneme_to_code[phoneme] = self.next_code
            self.code_to_phoneme[self.next_code] = phoneme
            self.next_code += 1
        return self.phoneme_to_code[phoneme]

    def encode_sequence(self, phonemes: List[str]) -> np.ndarray:
        return np.array([self.encode(p) for p in phonemes], dtype=np.int32)


# =============================================================================
# Inverted index
# =============================================================================

class PhonemeIndex:
    """
    Inverted index on leading phonemes

    Dictionary words are bucketed by their first two phonemes; a search only scores
    words whose bucket phonemes occur in the input. Two phonemes rather than one
    tolerate a misheard first sound (klaude -> Claude).
    """

    def __init__(self):
        self.encoder = PhonemeEncoder()
        # {phoneme code: [(dictionary word, phoneme codes), ...]}
        self.index: Dict[int, List[Tuple[str, np.ndarray]]] = defaultdict(list)
        self.all_hotwords: List[Tuple[str, np.ndarray]] = []

    def add(self, hotword: str, phonemes: List[Phoneme]):
        """Add a dictionary word to the index."""
        if not phonemes:
            return

        phoneme_strs = [p.value for p in phonemes]
        codes = self.encoder.encode_sequence(phoneme_strs)

        # Index the first two phonemes
        limit = min(len(codes), 2)
        target_codes = {codes[i] for i in range(limit)}

        for code in target_codes:
            self.index[code].append((hotword, codes))

        self.all_hotwords.append((hotword, codes))

    def get_candidates(self, input_phonemes: List[Phoneme]) -> List[Tuple[str, np.ndarray]]:
        """
        Candidate dictionary words: those whose index phonemes occur in the input

        Args:
            input_phonemes: input phoneme sequence (List[Phoneme])
        """
        input_codes = set()

        for p in input_phonemes:
            code = self.encoder.phoneme_to_code.get(p.value)
            if code is not None:
                input_codes.add(code)

        candidates = []
        seen = set()
        for code in input_codes:
            for hw, codes in self.index.get(code, []):
                if hw in seen:
                    continue
                candidates.append((hw, codes))
                seen.add(hw)

        return candidates

    def encode_input(self, phonemes: List[Phoneme]) -> np.ndarray:
        """Encode an input sequence."""
        phoneme_strs = [p.value for p in phonemes]
        return self.encoder.encode_sequence(phoneme_strs)


# =============================================================================
# Fast search
# =============================================================================

class FastRAG:
    """
    Fast dictionary search

    1. Numba JIT for the core algorithm
    2. Inverted index on leading phonemes
    3. Length filter for impossible matches
    """

    def __init__(self, threshold: float = 0.6):
        self.threshold = threshold
        self.index = PhonemeIndex()
        self.hotword_count = 0

    def add_hotwords(self, hotwords: Dict[str, List[Phoneme]]):
        """
        Add dictionary words

        Args:
            hotwords: {dictionary word: phoneme sequence}
        """
        for hw, phonemes in hotwords.items():
            if phonemes:
                self.index.add(hw, phonemes)
                self.hotword_count += 1

    def search(self, input_phonemes: List[Phoneme], top_k: int = 10) -> List[Tuple[str, float]]:
        """
        Find related dictionary words
        """
        if not input_phonemes: return []

        logger.debug(f"[DEBUG] FastRAG.search: input_phonemes type={type(input_phonemes)}, len={len(input_phonemes)}")
        if input_phonemes:
            logger.debug(f"[DEBUG] FastRAG.search: input_phonemes[0] type={type(input_phonemes[0])}, value={input_phonemes[0]}")

        # 1. Encode the input and get candidates
        input_codes = self.index.encode_input(input_phonemes)
        candidates = self.index.get_candidates(input_phonemes)

        # 2. Score and filter
        results = self._score_candidates(input_codes, candidates)

        # 3. Sort and cut
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:top_k]

    def _score_candidates(self, input_codes: np.ndarray, candidates: List[Tuple[str, np.ndarray]]) -> List[Tuple[str, float]]:
        """Score the candidates and keep those above the threshold."""
        results = []
        input_len = len(input_codes)

        for hw, hw_codes in candidates:
            hw_len = len(hw_codes)

            # A word much longer than the input cannot match
            if hw_len > input_len + 3: continue

            if HAS_NUMBA:
                min_dist = _fuzzy_substring_distance_numba(input_codes, hw_codes)
            else:
                min_dist = self._python_distance(input_codes, hw_codes)

            # 1 - normalised distance
            score = 1.0 - (min_dist / hw_len)
            if score >= self.threshold:
                results.append((hw, round(score, 3)))
        return results

    def compute_score(self, input_phonemes: List[str], hotword_phonemes: List[str]) -> float:
        """
        Exact score of one dictionary word (for re-ranking)
        """
        input_codes = self.index.encode_input(input_phonemes)
        hw_codes = self.index.encode_input(hotword_phonemes)

        hw_len = len(hw_codes)
        if hw_len == 0:
            return 0.0

        if HAS_NUMBA:
            min_dist = _fuzzy_substring_distance_numba(input_codes, hw_codes)
        else:
            min_dist = self._python_distance(input_codes, hw_codes)

        return max(0.0, 1.0 - (min_dist / hw_len))


    def _python_distance(self, main_codes: np.ndarray, sub_codes: np.ndarray) -> float:
        """Plain Python version (when Numba is not available)."""
        n = len(sub_codes)
        m = len(main_codes)

        if n == 0 or m == 0:
            return float(n)

        dp = [[0.0] * (m + 1) for _ in range(n + 1)]

        for i in range(1, n + 1):
            dp[i][0] = float(i)

        for i in range(1, n + 1):
            for j in range(1, m + 1):
                cost = 0.0 if sub_codes[i-1] == main_codes[j-1] else 1.0
                dp[i][j] = min(
                    dp[i-1][j] + 1.0,
                    dp[i][j-1] + 1.0,
                    dp[i-1][j-1] + cost
                )

        return min(dp[n][j] for j in range(1, m + 1))
