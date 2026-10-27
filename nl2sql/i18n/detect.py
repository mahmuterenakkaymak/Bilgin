"""Which language a question was typed in: Turkish letters and stopwords, scored rather than guessed (R8-6)."""

from __future__ import annotations

import re
import unicodedata

from nl2sql import config

TURKISH_LETTERS = "çğıöşüÇĞİÖŞÜ"  # letters an English sentence never writes
_TOKENS = re.compile(r"\w+")


def _fold(text: str) -> str:
    """Lower case with the Turkish accents flattened: 'İÇİN', 'için' and 'IÇIN' all fold to 'icin'."""
    flat = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in flat if not unicodedata.combining(c)).replace("ı", "i")


_TR_WORDS = frozenset(_fold(word) for word in config.DETECT_TR_WORDS)
_EN_WORDS = frozenset(_fold(word) for word in config.DETECT_EN_WORDS)


def detect_lang(text: str, fallback: str = "tr") -> str:
    """'en' for an English question, 'tr' for a Turkish one, `fallback` when the two scores tie.

    A Turkish letter counts double so one stray English word inside a Turkish sentence cannot flip
    it. Text with no signal at all - empty, a number, a bare product code - is not guessed either:
    the caller's own default comes back.
    """
    letters = sum(1 for ch in text if ch in TURKISH_LETTERS)
    tokens = _TOKENS.findall(_fold(text))
    score_tr = 2 * letters + sum(1 for token in tokens if token in _TR_WORDS)
    score_en = sum(1 for token in tokens if token in _EN_WORDS)
    if score_tr == score_en:
        return fallback
    return "tr" if score_tr > score_en else "en"
