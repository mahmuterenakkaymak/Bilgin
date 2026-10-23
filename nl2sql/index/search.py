"""Karma arama: sözcük araması ile vektör benzerliğinin RRF altında birleştirilmesi (PLAN R2-8).

Üç yöntem yan yana duruyor, çünkü fazın ölçümü bu üçünü karşılaştırmak için var: RAG'ın kalması
hibridin gerçekten kazanmasına bağlı. Kaynaşım sıralamadan gelir, ham skordan değil: BM25'in
skoru sınırsız, kosinüsünki [-1, 1], bu yüzden ikisi doğrudan toplanamaz. RRF her yöntemin kendi
sırasını kullandığı için ölçekler uzlaştırılmaz.

BM25 koleksiyon başına kurulur; kural dokümanları tablo dokümanlarından uzun olduğu için tek
korpus idf'yi boğardı. Vektörler L2-normalize gelse de kosinüs bölme ile hesaplanır: boş metnin
sıfır vektörü ya da vektörü olmayan bir doküman böylece hiç öne çıkmaz.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from nl2sql import config
from nl2sql.index.bm25 import BM25
from nl2sql.index.docs import Doc, build_documents
from nl2sql.index.embed import Embedder, make_embedder
from nl2sql.index.store import FileStore, content_hash
from nl2sql.index.text import tokens

METHODS = ("hybrid", "bm25", "dense")


@dataclass
class Hit:
    """Tek bir arama sonucu; `rank` 1'den başlar, `score` yöntemin kendi ölçeğindedir."""

    doc_id: str
    title: str
    score: float
    rank: int
    text: str = ""


def rrf(rankings: Sequence[Sequence[str]], k: int = config.RRF_K) -> list[tuple[str, float]]:
    """Reciprocal rank fusion: her listenin kendi sırasıyla sum 1/(k + rank); eşitliği id kırar."""
    totals: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            totals[doc_id] = totals.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))


class HybridSearch:
    """Bir koleksiyon kümesi üzerinde hybrid/bm25/dense arama; `vectors` `docs` sırasıyladır."""

    def __init__(self, docs: list[Doc], vectors: list[list[float]], embedder: Embedder) -> None:
        self.embedder = embedder
        self._docs = {doc.id: doc for doc in docs}
        self._vectors = {doc.id: vector for doc, vector in zip(docs, vectors)}
        self._members: dict[str, list[Doc]] = {}
        self._bm25: dict[str, BM25] = {}
        for doc in docs:
            self._members.setdefault(doc.collection, []).append(doc)
        for collection, members in self._members.items():
            self._bm25[collection] = BM25([tokens(doc.text) for doc in members])

    def search(
        self,
        query: str,
        collection: str = "tables",
        k: int = config.SEARCH_K,
        method: str = "hybrid",
    ) -> list[Hit]:
        """Koleksiyonun ilk `k` sonucu; boş sorgu/koleksiyon boş liste döndürür."""
        if method not in METHODS:
            raise ValueError(
                f"Bilinmeyen arama yöntemi: '{method}'. Geçerli olanlar: {list(METHODS)}."
            )
        members = self._members.get(collection, [])
        if not members or k <= 0:
            return []
        if method == "bm25":
            ranked = self._rank_bm25(collection, query, k)
        elif method == "dense":
            ranked = self._rank_dense(query, members, k)
        else:
            ranked = self._rank_hybrid(collection, query, members, k)
        return [
            Hit(doc_id=doc_id, title=self._docs[doc_id].title, score=score, rank=rank)
            for rank, (doc_id, score) in enumerate(ranked, start=1)
        ]

    def _rank_bm25(self, collection: str, query: str, k: int) -> list[tuple[str, float]]:
        members = self._members[collection]
        return [(members[index].id, score) for index, score in self._bm25[collection].rank(tokens(query), k)]

    def _rank_dense(self, query: str, members: list[Doc], k: int) -> list[tuple[str, float]]:
        vector = self.embedder.embed([query])[0]
        scored = [
            (_cosine(vector, self._vectors.get(doc.id, ())), index)
            for index, doc in enumerate(members)
        ]
        hits = sorted(
            (pair for pair in scored if pair[0] > 0.0), key=lambda pair: (-pair[0], pair[1])
        )
        return [(members[index].id, score) for score, index in hits[:k]]

    def _rank_hybrid(
        self, collection: str, query: str, members: list[Doc], k: int
    ) -> list[tuple[str, float]]:
        # ASSUMPTION: her yöntem k'nın iki katı derinliğine kadar kaynaştırılır; bir yöntemde
        # k'nın hemen dışına düşen doküman diğerinin oyuyla hâlâ kazanabilir (RRF'nin varlık nedeni).
        window = 2 * k
        return rrf(
            [
                [doc_id for doc_id, _ in self._rank_bm25(collection, query, window)],
                [doc_id for doc_id, _ in self._rank_dense(query, members, window)],
            ]
        )[:k]


def build_search(schema: dict, rules: list[dict], embedder: Embedder) -> HybridSearch:
    """İndeksi bellekte kurar: dokümanlar + onların vektörleri (R2-9: diske dokunmaz)."""
    docs = build_documents(schema, rules)
    return HybridSearch(docs, embedder.embed([doc.text for doc in docs]), embedder)


def load_search(
    index_dir: str | Path, schema: dict, rules: list[dict]
) -> HybridSearch:
    """Diskteki indeksi yükler; bayat sahte değil gerçek bir hata. Sorgu embedder'ı meta'dan."""
    index = FileStore(index_dir).load_checked(content_hash(schema, rules))
    return HybridSearch(index.docs, index.vectors, make_embedder(index.meta.get("embedder", "")))


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Brute-force kosinüs benzerliği; eşit genişlik şart, farklı genişlik en iyisi 0'a iner."""
    dot = sum(a * b for a, b in zip(left, right))
    if dot == 0.0:
        return 0.0
    norm = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
    return dot / norm if norm else 0.0
