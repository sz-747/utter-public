# coding: utf-8
"""
Core matching algorithms

Fuzzy edit distances over phoneme info tuples (value, kind, word start, word end, ...).
"""
from typing import List, Tuple


def fuzzy_substring_distance(hw_info: List[Tuple], input_info: List[Tuple]) -> float:
    """
    Smallest edit distance of a sequence inside another (it may match any part of it)
    Dynamic programming with rolling rows.

    Args:
        hw_info: dictionary word phonemes (info tuples)
        input_info: input phonemes (info tuples)
    """
    n = len(hw_info)
    m = len(input_info)
    if n == 0:
        return 0.0
    if m == 0:
        return float(n)

    prev = [0.0] * (m + 1)
    curr = [0.0] * (m + 1)

    for i in range(1, n + 1):
        curr[0] = float(i)

        for j in range(1, m + 1):
            # Cost straight from the tuples (no Phoneme objects)
            cost = _get_tuple_cost(hw_info[i-1], input_info[j-1])

            curr[j] = min(
                prev[j] + 1.0,
                curr[j-1] + 1.0,
                prev[j-1] + cost
            )

        prev, curr = curr, prev

    return min(prev)


def _get_tuple_cost(t1: Tuple, t2: Tuple) -> float:
    """
    Cost of matching two phoneme info tuples: 0.0 (same) to 1.0 (no match)

    Args:
        t1, t2: phoneme info tuples (value, kind, word start, word end, ...)
    """
    if t1[1] != t2[1]:
        return 1.0

    if t1[0] == t2[0]:
        return 0.0

    # English: character-level similarity
    if t1[1] == 'en':
        lcs_len = _lcs_length(t1[0], t2[0])
        max_len = max(len(t1[0]), len(t2[0]))
        if max_len > 0:
            return 1.0 - (lcs_len / max_len)

    return 1.0


def fuzzy_substring_search_constrained(hw_info: List[Tuple], input_info: List[Tuple], threshold: float = 0.6) -> List[Tuple[float, int, int]]:
    """
    Best matching spans of a dictionary word in the input (boundary-constrained)

    Local similarity by dynamic programming, where:
    1. a match starts at a word start in the input (is_word_start)
    2. a match ends at a word end in the input (is_word_end)
    3. the length may differ within limits

    Args:
        hw_info: dictionary word phoneme info tuples
        input_info: input phoneme info tuples
        threshold: similarity threshold

    Returns:
        List[(score, start_idx, end_idx)], best first
    """
    n = len(hw_info)
    m = len(input_info)
    if n == 0 or m == 0:
        return []

    # dp[i][j]: smallest distance of the word's first i phonemes matching a span ending at input[j-1]
    dp = [[float('inf')] * (m + 1) for _ in range(n + 1)]

    # Path, to recover the start: (prev_i, prev_j)
    path = [[(0, 0)] * (m + 1) for _ in range(n + 1)]

    # First row: a match may start at any word start.
    # If input_info[j] starts a word, hw[0] may match at index j (state dp[1][j+1], from dp[0][j]).
    for j in range(m + 1):
        if j == 0:
            dp[0][j] = 0.0
            path[0][j] = (0, j)
        elif j < m and input_info[j][2]:  # is_word_start
            dp[0][j] = 0.0
            path[0][j] = (0, j)

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            cost = _get_tuple_cost(hw_info[i-1], input_info[j-1])

            # Match, delete a word phoneme, or insert an extra input phoneme
            dist_match = dp[i-1][j-1] + cost
            dist_del = dp[i-1][j] + 1.0
            dist_ins = dp[i][j-1] + 1.0

            min_dist = min(dist_match, dist_del, dist_ins)
            dp[i][j] = min_dist

            if min_dist == dist_match:
                path[i][j] = path[i-1][j-1]
            elif min_dist == dist_del:
                path[i][j] = path[i-1][j]
            else:
                path[i][j] = path[i][j-1]

    results = []

    for j in range(1, m + 1):
        # A match must end at a word end
        if not input_info[j-1][3]:  # is_word_end
            continue

        dist = dp[n][j]
        if dist >= n * 0.8: continue  # too far apart

        score = 1.0 - (dist / n)
        if score >= threshold:
            start_idx = path[n][j][1]
            end_idx = j  # the j-th input phoneme, index j-1

            # Phoneme indices; callers map them to characters
            results.append((score, start_idx, end_idx))

    results.sort(key=lambda x: x[0], reverse=True)

    # Keep the best start for each end position
    used_ends = {}
    for score, s, e in results:
        if e not in used_ends or score > used_ends[e][0]:
            used_ends[e] = (score, s, e)

    return sorted(used_ends.values(), key=lambda x: x[0], reverse=True)


def _lcs_length(s1: str, s2: str) -> int:
    """Length of the longest common subsequence."""
    m, n = len(s1), len(s2)
    if m == 0 or n == 0:
        return 0

    prev = [0] * (n + 1)
    curr = [0] * (n + 1)

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if s1[i-1] == s2[j-1]:
                curr[j] = prev[j-1] + 1
            else:
                curr[j] = max(prev[j], curr[j-1])
        prev, curr = curr, prev

    return prev[n]
