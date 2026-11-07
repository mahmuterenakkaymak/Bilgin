# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Okapi BM25: bir kelimenin dokümanda kaç kez geçtiği değil, korpus içinde ne kadar nadir olduğu.

Sözcük arama tarafının tek işi bu. idf'nin klasik Robertson sürümü yerine daima pozitif olan
sürümü kullanılıyor: bir terim dokümanların yarısından fazlasında geçince klasik idf negatife
düşer, "skoru pozitif olanları bırak" kuralı da o dokümanı tamamen silerdi. Böylece nadir terim
yalnızca daha yüksek puan alır, yaygın terim hiç yok olmaz.

Girdi token listeleridir, metin değil: katlama `text.tokens`'ın işi ve indeksleme ile sorgu
tarafı aynı katlamadan geçmek zorunda. İki taraf farklı katlanırsa hiçbir doküman bulunamaz.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Sequence

from bilgin import config


class BM25:
    """Token listelerinden kurulan sıralama skoru; `docs` kadar skoru sırayla döndürür."""

    def __init__(
        self,
        token_lists: Iterable[Sequence[str]],
        k1: float = config.BM25_K1,
        b: float = config.BM25_B,
    ) -> None:
        self.k1 = k1
        self.b = b
        self.counts = [Counter(tokens) for tokens in token_lists]
        self.lengths = [sum(count.values()) for count in self.counts]
        self.docs = len(self.counts)
        self.avg_len = sum(self.lengths) / self.docs if self.docs else 0.0
        freq = Counter(term for count in self.counts for term in count)
        self.idf = {
            term: math.log(1.0 + (self.docs - n + 0.5) / (n + 0.5))
            for term, n in freq.items()
        }

    def scores(self, query_tokens: Sequence[str]) -> list[float]:
        """Doküman sırasını koruyan skor listesi; sorgudaki tekrar eden kelime iki kez sayılır."""
        result = [0.0] * self.docs
        for token in query_tokens:
            idf = self.idf.get(token)
            if idf is None:
                continue
            for index, count in enumerate(self.counts):
                tf = count.get(token, 0)
                if tf:
                    result[index] += idf * self._tf_weight(tf, self.lengths[index])
        return result

    def rank(self, query_tokens: Sequence[str], top: int) -> list[tuple[int, float]]:
        """Skoru pozitif olanlar büyükten küçüğe; eşitliği doküman sırası kırar."""
        pairs = [(index, score) for index, score in enumerate(self.scores(query_tokens)) if score > 0.0]
        pairs.sort(key=lambda pair: (-pair[1], pair[0]))
        return pairs[:top] if top > 0 else []

    def _tf_weight(self, tf: int, length: int) -> float:
        """Doyma (k1) ve doküman uzunluğu cezası (b): aynı tekrar, uzun dokümanda daha az değer."""
        ratio = length / self.avg_len if self.avg_len else 0.0
        norm = self.k1 * (1.0 - self.b + self.b * ratio)
        return tf * (self.k1 + 1.0) / (tf + norm)
