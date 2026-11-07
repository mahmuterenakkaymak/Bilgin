# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Karma arama: sözcük araması ile vektör benzerliğinin RRF altında birleştirilmesi (PLAN R2-8).

Üç yöntem yan yana duruyor, çünkü fazın ölçümü bu üçünü karşılaştırmak için var: RAG'ın kalması
hibridin gerçekten kazanmasına bağlı. Kaynaşım sıralamadan gelir, ham skordan değil: BM25'in
skoru sınırsız, kosinüsünki [-1, 1], bu yüzden ikisi doğrudan toplanamaz. RRF her yöntemin kendi
sırasını kullandığı için ölçekler uzlaştırılmaz.

BM25 koleksiyon başına kurulur; kural dokümanları tablo dokümanlarından uzun olduğu için tek
korpus idf'yi boğardı. Vektörler L2-normalize gelse de kosinüs bölme ile hesaplanır: boş metnin
sıfır vektörü ya da vektörü olmayan bir doküman böylece hiç öne çıkmaz.

İki bacak aynı sorguyu görmek zorunda değil (R3-9): sözcük bacağı iş teriminin eş anlamlılarıyla
genişletilir, vektör bacağı ham sorguda kalır - eklenen kelimeler vektörü kullanıcının demek
istediğinden uzağa taşırdı.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from bilgin import config
from bilgin.index.bm25 import BM25
from bilgin.index.docs import Doc, build_documents
from bilgin.index.embed import Embedder, make_embedder
from bilgin.index.store import FileStore, content_hash
from bilgin.index.summaries import table_summaries
from bilgin.index.text import fold, tokens

METHODS = ("hybrid", "bm25", "dense")


@dataclass
class Hit:
    """Tek bir arama sonucu; `rank` 1'den başlar, `score` yöntemin kendi ölçeğindedir.

    `meta` sıralamaya girmeyen bilgiyi taşır - komşu olarak eklenen vuruşun işareti gibi.
    """

    doc_id: str
    title: str
    score: float
    rank: int
    text: str = ""
    meta: dict = field(default_factory=dict)


def rrf(rankings: Sequence[Sequence[str]], k: int = config.RRF_K) -> list[tuple[str, float]]:
    """Reciprocal rank fusion: her listenin kendi sırasıyla sum 1/(k + rank); eşitliği id kırar."""
    totals: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            totals[doc_id] = totals.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(totals.items(), key=lambda pair: (-pair[1], pair[0]))


# Kısa bir terimin geçtiği her kelime onu söylüyor demek değil: "Kuruyemiş" ürün grubuyla
# sorulan soru "Dövizi TL'ye çevirmek" kuralını yakalıyordu. Kelime kökü yakalamak için gereken
# uzunluk - "ciro" "cirosu"nu bulsun, "kur" "kuruyemiş"i bulmasın.
MIN_SUBSTRING = 4


def _said(phrase: str, asked: str, words: Sequence[str]) -> bool:
    """İş terimi sorguda söylenmiş mi: uzun ifade alt dizi, kısa ifade tam bir sözcük.

    Ölçü ifadenin tamamı: "kur farkı" iki sözcüğe bölünüp "kur" aranan bir şey değildir.
    """
    folded = fold(phrase)
    if len(folded) >= MIN_SUBSTRING:
        return folded in asked
    return folded in words


def synonym_query(query: str, rules: Iterable[dict]) -> str:
    """R3-9: sorgunun yakaladığı her kuralın eş anlamlıları sorgunun sonuna eklenir.

    Kural ifadesi katlanmış sorguda alt dizi olarak aranır, böylece "ciro" ile sorulan bir soru
    "cirosu"nu da yakalar; dört katlanmış harften kısa ifadeler tam bir sözcük olmak zorundadır
    (`_said`). Sorguda zaten geçen eş anlamlı yeniden eklenmez: BM25 tekrar eden sorgu
    kelimesini iki kez sayar, yani terimin kendi ağırlığını şişirirdi.

    İki dil tek liste gibi sayılır (R8-13): İngilizce sorulan bir soru `synonyms_en` üzerinden
    tutuşur, eklenen kelimeler arasında Türkçe karşılıkları da gördüğü için doküman tarafına ulaşır.
    """
    asked = fold(query)
    words = tokens(query)
    extra: list[str] = []
    for rule in rules:
        synonyms = [
            word
            for word in [*(rule.get("synonyms") or []), *(rule.get("synonyms_en") or [])]
            if word
        ]
        phrases = [rule.get("term") or "", *synonyms]
        if any(_said(phrase, asked, words) for phrase in phrases if phrase):
            extra.extend(word for word in synonyms if not _said(word, asked, words))
    return f"{query} {' '.join(extra)}" if extra else query


class HybridSearch:
    """Bir koleksiyon kümesi üzerinde hybrid/bm25/dense arama; `vectors` `docs` sırasıyladır.

    `rules` eş anlamlı genişletmesi için gerekir: kural dokümanları olmasa da sorgunun hangi iş
    terimlerini söylediğini söyleyen taraf onlar.
    """

    def __init__(
        self,
        docs: list[Doc],
        vectors: list[list[float]],
        embedder: Embedder,
        rules: Sequence[dict] = (),
    ) -> None:
        self.embedder = embedder
        self.rules = list(rules)
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
        rewrite: bool = config.SYNONYM_REWRITE,
    ) -> list[Hit]:
        """Koleksiyonun ilk `k` sonucu; boş sorgu/koleksiyon boş liste döndürür.

        `rewrite` açıkken (R3-9) yalnız sözcük bacağı eş anlamlılarla genişletilir.
        """
        if method not in METHODS:
            raise ValueError(
                f"Bilinmeyen arama yöntemi: '{method}'. Geçerli olanlar: {list(METHODS)}."
            )
        members = self._members.get(collection, [])
        if not members or k <= 0:
            return []
        if method == "bm25":
            ranked = self._rank_bm25(collection, query, k, rewrite)
        elif method == "dense":
            ranked = self._rank_dense(query, members, k)
        else:
            ranked = self._rank_hybrid(collection, query, members, k, rewrite)
        return [
            Hit(doc_id=doc_id, title=self._docs[doc_id].title, score=score, rank=rank)
            for rank, (doc_id, score) in enumerate(ranked, start=1)
        ]

    def search_tables(
        self, query: str, k: int = config.SEARCH_K, summaries: bool = False
    ) -> list[Hit]:
        """Tablo araması; `summaries` açıkken tablo sırası tablo özetlerinin sırasıyla kaynaşır (R5-20).

        Özetler ayrı bir koleksiyondur: bir tablonun tek cümlelik tanıtımı, kolon kolon sayan tablo
        dokümanının yanındaki ikinci ses. Kaynaşım özetin kimliğini tablonun kimliğine çevirir
        (`summary:<AD>` -> `table:<AD>`), yani iki bacak da aynı tablo listesini sayıyor; vuruşların
        hepsi tablodur.
        """
        hits = self.search(query, collection="tables", k=k)
        if not summaries:
            return hits
        # ASSUMPTION: özet bacağı aramanın kendi yöntemiyle değil varsayılanıyla (hybrid) kaynaşır;
        # bm25/dense için ayrı düğme yok, çünkü ölçülen iddia özetin hibride ne kattığı.
        fused = rrf(
            [
                [hit.doc_id for hit in hits],
                [f"table:{hit.title}" for hit in self.search(query, collection="summaries", k=k)],
            ]
        )
        return [
            Hit(doc_id=doc_id, title=self._docs[doc_id].title, score=score, rank=rank)
            for rank, (doc_id, score) in enumerate(fused[:k], start=1)
        ]

    def _rank_bm25(
        self, collection: str, query: str, k: int, rewrite: bool
    ) -> list[tuple[str, float]]:
        members = self._members[collection]
        asked = synonym_query(query, self.rules) if rewrite else query
        return [(members[index].id, score) for index, score in self._bm25[collection].rank(tokens(asked), k)]

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
        self, collection: str, query: str, members: list[Doc], k: int, rewrite: bool
    ) -> list[tuple[str, float]]:
        # ASSUMPTION: her yöntem k'nın iki katı derinliğine kadar kaynaştırılır; bir yöntemde
        # k'nın hemen dışına düşen doküman diğerinin oyuyla hâlâ kazanabilir (RRF'nin varlık nedeni).
        window = 2 * k
        return rrf(
            [
                [doc_id for doc_id, _ in self._rank_bm25(collection, query, window, rewrite)],
                [doc_id for doc_id, _ in self._rank_dense(query, members, window)],
            ]
        )[:k]


def expanded_hits(
    search: HybridSearch,
    query: str,
    graph,
    schema: dict,
    k: int,
    expand: bool = config.NEIGHBOUR_EXPANSION,
    max_extra: int = config.NEIGHBOUR_MAX,
    summaries: bool = False,
) -> list[Hit]:
    """R3-9: ilk k vuruşun join graphındaki 1 adımlık komşuları listenin sonuna eklenir.

    Komşu aramanın değil şemanın söylediği bir bağlantıdır: model fatura tablosunu bulduğunda
    cari hesabı da görmeli, yoksa ikinci bir aramayı onu tahmin etmekle harcıyor. Yalnız veri
    tabloları eklenir - bir dolgunun komşusu olmak onu ilginç kılmaz - ve her vuruş en fazla
    `max_extra` komşu getirir. `expand` kapalıyken sonuç tam olarak aramanın kendi listesidir.

    `summaries` (R5-20) taban sırayı `search_tables`dan alır: tablo sırası tablo özetlerinin
    sırasıyla kaynaşır. Kapalıyken aramanın kendi tablo araması okunur.
    """
    hits = (
        search.search_tables(query, k=k, summaries=True)
        if summaries
        else search.search(query, collection="tables", k=k)
    )
    if not expand or graph is None or max_extra <= 0:
        return hits
    known = {hit.title for hit in hits}
    data = {
        table["name"]
        for table in schema.get("tables", [])
        if table.get("kind") != "distractor"
    }
    names: list[str] = []
    for hit in hits:
        taken = 0
        for name in sorted(set(_neighbours(graph, hit.title))):
            if taken == max_extra:
                break
            if name in known or name not in data:
                continue
            known.add(name)
            names.append(name)
            taken += 1
    return [
        *hits,
        *(
            Hit(doc_id=f"table:{name}", title=name, score=0.0, rank=rank, meta={"komşu": True})
            for rank, name in enumerate(names, start=len(hits) + 1)
        ),
    ]


def _neighbours(graph, name: str) -> Iterable[str]:
    """Bir tabloya kenarla bağlı tablolar; graphın tanımadığı bir ad komşusuzdur."""
    for edge in graph.adjacency.get(name, []):
        yield edge.right_table if edge.left_table == name else edge.left_table


def build_search(schema: dict, rules: list[dict], embedder: Embedder, graph=None) -> HybridSearch:
    """İndeksi bellekte kurar: dokümanlar + onların vektörleri (R2-9: diske dokunmaz).

    `graph` verilirse tablo dokümanlarının yanına özetler de yazılır (R5-20): `summaries`
    araması o koleksiyonu okur, yani diskteki indeksle aynı üç girdiden türer.
    """
    docs = build_documents(schema, rules)
    if graph is not None:
        docs = [*docs, *table_summaries(schema, rules, graph)]
    return HybridSearch(docs, embedder.embed([doc.text for doc in docs]), embedder, rules)


def load_search(
    index_dir: str | Path, schema: dict, rules: list[dict], dataset: str | None = None
) -> HybridSearch:
    """Diskteki indeksi yükler; bayat sahte değil gerçek bir hata. Sorgu embedder'ı meta'dan.

    `dataset` verilirse indeks o kümenin değilse yüklenmez (R4-8) - mesajı hangi komutun
    doğru indeksi kuracağını söylüyor.
    """
    index = FileStore(index_dir).load_checked(content_hash(schema, rules), dataset)
    return HybridSearch(
        index.docs, index.vectors, make_embedder(index.meta.get("embedder", "")), rules
    )


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    """Brute-force kosinüs benzerliği; eşit genişlik şart, farklı genişlik en iyisi 0'a iner."""
    dot = sum(a * b for a, b in zip(left, right))
    if dot == 0.0:
        return 0.0
    norm = math.sqrt(sum(a * a for a in left) * sum(b * b for b in right))
    return dot / norm if norm else 0.0
