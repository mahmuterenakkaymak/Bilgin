# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Metni arama için normalize etme: Türkçe katlama, kelime parçaları, shingle'lar.

İndeksin hem doküman tarafı hem sorgu tarafı aynı katlamadan geçmek zorunda; aksi halde
kullanıcının "ILAC" yazdığı soru "İlaç" dokümanını bulamaz. Büyük I iki ayrı harfe iner
(Türkçe I -> ı, yabancı kökenli İ -> i), bu yüzden katlama str.lower()'dan önce yapılır.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

_WORD_RE = re.compile(r"\w+")


def fold(text: str) -> str:
    """Turkish-aware folding: İ->i, I->ı, then str.lower()."""
    return text.replace("İ", "i").replace("I", "ı").lower()


def tokens(text: str) -> list[str]:
    """Folded \\w+ words, digits kept; a `_`-joined name also yields its parts."""
    result: list[str] = []
    for word in _WORD_RE.findall(fold(text)):
        result.append(word)
        parts = word.split("_")
        if len(parts) > 1:
            result.extend(part for part in parts if part)
    return result


def shingles(tokens: Sequence[str], n: int) -> set[tuple[str, ...]]:
    """Every n-token window as a tuple; empty when the sequence is shorter than n."""
    words = list(tokens)
    if n <= 0 or len(words) < n:
        return set()
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}
