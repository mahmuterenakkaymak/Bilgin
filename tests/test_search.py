"""R2-8: kaynaşımın aritmetiği ve gerçek şema üzerinde üç yöntemin davranışı.

RRF elle hesaplanabilmeli: kaynaşımın sıralamayı neden böyle kurduğu testte görünmezse, bir
sabitin (RRF_K) yanlış olması aylarca fark edilmeden "arama fena değil" diye geçebilir. Asıl
iddia ise ölçüm değil bulunabilirlik: altın sorunun dili ilgili tabloyu ilk beşe taşımalı.
"""

import pytest

from nl2sql import config
from nl2sql.index.docs import build_documents
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import Hit, build_search, load_search, rrf
from nl2sql.index.store import FileStore, content_hash
from nl2sql.schema_map.doc import load_schema
from nl2sql.schema_map.rules import load_rules

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
