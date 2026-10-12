"""Guard against copying third-party text (docs/modelo-datos.md R6).

Summaries must never share 16 or more consecutive words with the README or the original
descriptions. ``overlaps`` is the fast runtime check (hash set of 16-word windows);
``longest_common_run`` is the exact measure used by the acceptance tests.
"""

from __future__ import annotations

import re

WINDOW = 16
_WORD = re.compile(r"\w+", re.UNICODE)


def word_list(text: str) -> list[str]:
    return [w.lower() for w in _WORD.findall(text or "")]


def _windows(words: list[str], size: int) -> set[tuple[str, ...]]:
    return {tuple(words[i : i + size]) for i in range(len(words) - size + 1)}


def overlaps(candidate: str, source: str, size: int = WINDOW) -> bool:
    words = word_list(candidate)
    if len(words) < size:
        return False
    return bool(_windows(words, size) & _windows(word_list(source), size))


def longest_common_run(candidate: str, source: str) -> int:
    """Length of the longest run of consecutive identical words (dynamic programming)."""
    a, b = word_list(candidate), word_list(source)
    if not a or not b:
        return 0
    best = 0
    previous = [0] * (len(a) + 1)
    for word in b:
        current = [0] * (len(a) + 1)
        for i, other in enumerate(a, 1):
            if other == word:
                current[i] = previous[i - 1] + 1
                if current[i] > best:
                    best = current[i]
        previous = current
    return best
