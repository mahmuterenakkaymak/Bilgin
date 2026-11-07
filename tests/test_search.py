# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R2-8: kaynaşımın aritmetiği ve gerçek şema üzerinde üç yöntemin davranışı.

RRF elle hesaplanabilmeli: kaynaşımın sıralamayı neden böyle kurduğu testte görünmezse, bir
sabitin (RRF_K) yanlış olması aylarca fark edilmeden "arama fena değil" diye geçebilir. Asıl
iddia ise ölçüm değil bulunabilirlik: altın sorunun dili ilgili tabloyu ilk beşe taşımalı.
"""

import pytest

from bilgin import config
from bilgin.index.docs import build_documents
from bilgin.index.embed import FakeEmbedder
from bilgin.index.search import Hit, build_search, load_search, rrf
from bilgin.index.store import FileStore, content_hash
from bilgin.schema_map.doc import load_schema
from bilgin.schema_map.rules import load_rules

SCHEMA = load_schema()
RULES = load_rules()
EMBEDDER = FakeEmbedder()
SEARCH = build_search(SCHEMA, RULES, EMBEDDER)


def ids(hits):
    return [hit.doc_id for hit in hits]


def test_rrf_hand_values():
    fused = rrf([["a", "b"], ["a", "c"]])
    assert [doc_id for doc_id, _ in fused] == ["a", "b", "c"]
    assert [score for _, score in fused] == pytest.approx([2 / 61, 1 / 62, 1 / 62])


def test_rrf_uses_the_given_k():
    assert rrf([["a"]], k=0) == [("a", 1.0)]
    assert rrf([["a"]], k=10)[0][0] == "a"
    assert rrf([["a"]], k=10)[0][1] == pytest.approx(1 / 11)


def test_rrf_ties_break_by_doc_id():
    assert [doc_id for doc_id, _ in rrf([["b"], ["a"]])] == ["a", "b"]
    assert [doc_id for doc_id, _ in rrf([["b", "a"], ["c"]])] == ["b", "c", "a"]


def test_rrf_keeps_a_doc_that_is_in_one_list_only():
    fused = rrf([["a", "b"], ["c"]])
    assert [doc_id for doc_id, _ in fused] == ["a", "c", "b"]
    assert fused[2][1] == pytest.approx(1 / 62)


def test_hit_text_defaults_to_empty():
    assert Hit(doc_id="table:X", title="X", score=1.0, rank=1).text == ""


def test_stock_movements_reach_the_movement_table():
    hits = SEARCH.search("stok hareketleri satış iade")
    assert len(hits) == config.SEARCH_K
    assert "table:TBLSTHAR" in ids(hits)
    assert [hit.rank for hit in hits] == list(range(1, config.SEARCH_K + 1))


def test_exchange_rate_prefers_the_rate_table():
    assert ids(SEARCH.search("döviz kuru"))[0] == "table:TBLDOVKUR"


def test_istanbul_branches_prefer_the_branch_table():
    assert ids(SEARCH.search("İSTANBUL şubeleri"))[0] == "table:TBLCARISUBE"


def test_rules_collection_returns_the_return_ratio_rule():
    assert ids(SEARCH.search("iade oranı", collection="rules"))[0] == "rule:iade_orani"


def test_collection_filter_holds_for_every_method():
    for method in ("hybrid", "bm25", "dense"):
        assert all(doc_id.startswith("rule:") for doc_id in ids(
            SEARCH.search("iade oranı", collection="rules", method=method)
        ))
        assert all(doc_id.startswith("table:") for doc_id in ids(
            SEARCH.search("iade oranı", collection="tables", method=method)
        ))


def test_examples_collection_is_empty():
    assert SEARCH.search("stok", collection="examples") == []


def test_k_is_respected():
    for k in (1, 2, config.SEARCH_K):
        assert len(SEARCH.search("döviz kuru", k=k)) == k
    assert SEARCH.search("döviz kuru", k=0) == []


def test_scores_are_positive_and_never_increase():
    for method in ("hybrid", "bm25", "dense"):
        scores = [hit.score for hit in SEARCH.search("döviz kuru", method=method)]
        assert scores and all(score > 0 for score in scores)
        assert scores == sorted(scores, reverse=True)


def test_methods_disagree_on_a_real_query():
    found = {
        method: ids(SEARCH.search("döviz kuru", method=method))
        for method in ("hybrid", "bm25", "dense")
    }
    assert found["hybrid"] != found["bm25"]
    assert found["hybrid"] != found["dense"]
    assert found["bm25"] != found["dense"]


def test_unknown_method_raises():
    with pytest.raises(ValueError):
        SEARCH.search("döviz kuru", method="vector")


def test_load_search_uses_the_stored_embedder(tmp_path):
    docs = build_documents(SCHEMA, RULES)
    directory = tmp_path / "index"
    FileStore(directory).save(
        docs,
        EMBEDDER.embed([doc.text for doc in docs]),
        {"content_hash": content_hash(SCHEMA, RULES), "embedder": EMBEDDER.id},
    )

    loaded = load_search(directory, SCHEMA, RULES)

    assert loaded.embedder.id == EMBEDDER.id
    assert ids(loaded.search("döviz kuru")) == ids(SEARCH.search("döviz kuru"))
