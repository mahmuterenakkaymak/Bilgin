"""R2-8: BM25 üç şeyi doğru yapmalı — nadir terim daha ağır basar, uzun doküman cezalandırılır,
eşitlik sırayı bozmaz.

Skorlar elle hesaplanmış sabitlerle karşılaştırılıyor; formülü tekrar yazan bir test formül
yanlışsa onu da yanlış yazardı. Katlama burada test edilmiyor, yalnızca `text.tokens` üzerinden
geçiyor: doküman ve sorgu aynı katlamadan geçmezse eşleşme hiç olmaz.
"""

import math

import pytest

from nl2sql.index import text
from nl2sql.index.bm25 import BM25

# Elle hesap: 3 doküman, ortalama uzunluk (3+2+1)/3 = 2.
CORPUS = [
    ["stok", "stok", "hareket"],  # 0
    ["stok", "fatura"],  # 1
    ["fatura"],  # 2
]


def test_score_matches_the_hand_computed_value():
    # "stok" 2 dokümanda geçiyor: idf = ln(1 + (3-2+0,5)/(2+0,5)) = ln(1,6).
    idf = math.log(1.6)
    # doküman 0: tf 2, uzunluk 3 -> 2*2,5 / (2 + 1,5*(0,25 + 0,75*1,5)) = 5 / 4,0625
    # doküman 1: tf 1, uzunluk 2 -> 1*2,5 / (1 + 1,5*(0,25 + 0,75*1)) = 2,5 / 2,5 = 1
    # doküman 2: "stok" yok -> 0
    assert BM25(CORPUS).scores(["stok"]) == pytest.approx([idf * 5 / 4.0625, idf, 0.0])


def test_repeated_query_term_counts_twice():
    bm25 = BM25(CORPUS)
    assert bm25.scores(["stok", "stok"]) == pytest.approx([2 * score for score in bm25.scores(["stok"])])


def test_term_in_every_doc_still_scores_but_scores_lowest():
    bm25 = BM25([["x", "y"], ["x", "z"]])
    # "x" iki dokümanda da var: idf ln(1 + 0,5/2,5) = ln(1,2). "y" tek dokümanda:
    # idf ln(1 + 1,5/1,5) = ln(2). tf ve doküman uzunluğu aynı (1 ve 2 = ortalama), yani
    # aradaki fark salt idf'den; yaygın terim yine de skor üretmeye devam ediyor.
    assert bm25.scores(["y"]) == pytest.approx([math.log(2.0), 0.0])
    assert bm25.scores(["x"]) == pytest.approx([math.log(1.2), math.log(1.2)])
    assert bm25.scores(["y"])[0] > bm25.scores(["x"])[0] > 0.0


def test_shorter_doc_wins_the_same_repeat_and_b_zero_removes_the_penalty():
    docs = [["ciro"] + ["dolgu"] * 9, ["ciro", "dolgu"]]
    bm25 = BM25(docs)
    # İki dokümanda da tek "ciro", idf aynı; 2 kelimelik doküman 10 kelimelik olanı geçer.
    assert bm25.scores(["ciro"])[1] > bm25.scores(["ciro"])[0] > 0.0
    assert [index for index, _ in bm25.rank(["ciro"], 2)] == [1, 0]
    # b = 0 uzunluk cezasını kapatır: norm iki dokümanda da k1, ağırlık 2,5/2,5 = 1.
    assert BM25(docs, b=0.0).scores(["ciro"]) == pytest.approx([math.log(1.2)] * 2)


def test_no_match_and_empty_query_score_nothing():
    bm25 = BM25(CORPUS)
    assert bm25.rank(["plasiyer"], 5) == []
    assert bm25.rank([], 5) == []
    assert bm25.scores(["plasiyer"]) == [0.0, 0.0, 0.0]


def test_ties_are_broken_by_index_and_top_cuts_the_tail():
    bm25 = BM25([["depo"], ["depo"], ["depo"]])
    # Üç dokümanda da tek kelime: idf ln(1 + 0,5/3,5), ağırlık 2,5/(1 + 1,5) = 1.
    score = math.log(1 + 0.5 / 3.5)
    assert [index for index, _ in bm25.rank(["depo"], 3)] == [0, 1, 2]
    assert [score for _, score in bm25.rank(["depo"], 3)] == pytest.approx([score] * 3)
    assert [index for index, _ in bm25.rank(["depo"], 2)] == [0, 1]
    assert bm25.rank(["depo"], 0) == []


def test_unknown_term_and_empty_corpus_never_raise():
    assert BM25(CORPUS).scores(["İLAÇ"]) == [0.0, 0.0, 0.0]
    assert BM25([]).scores(["stok"]) == []
    assert BM25([]).rank(["stok"], 3) == []
    assert BM25([[], []]).rank(["stok"], 2) == []


def test_folding_is_the_caller_side_and_must_match():
    docs = ["DEPO_KODU depo şubesi", "İLAÇ stok hareketleri", "FATURA başlığı"]
    bm25 = BM25([text.tokens(doc) for doc in docs])
    assert [index for index, _ in bm25.rank(text.tokens("İLAÇ"), 3)] == [1]
    assert [index for index, _ in bm25.rank(text.tokens("ilaç İSTANBUL"), 3)] == [1]
    # Büyük I ı'ya iniyor: "ILAÇ" ile "İLAÇ" aynı kelime değil, bu yüzden bulgu yok.
    assert bm25.rank(text.tokens("ILAÇ"), 3) == []


def test_underscored_names_are_found_through_their_parts():
    bm25 = BM25([text.tokens("HAREKET_İADE"), text.tokens("FATURA")])
    assert [index for index, _ in bm25.rank(text.tokens("İADE"), 2)] == [0]
    assert [index for index, _ in bm25.rank(text.tokens("HAREKET"), 2)] == [0]
    assert {index for index, _ in bm25.rank(text.tokens("FATURA"), 2)} == {1}
