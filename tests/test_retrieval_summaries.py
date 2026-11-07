# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R5-20: tablo özeti aramaya katılınca liste hâlâ tablo listesi olmalı.

Özetler tablo dokümanlarının yanına yazılan ikinci bir ses; kaynaşım o sesi tablonun kendi
kimliğine (`summary:<AD>` -> `table:<AD>`) çeviriyor. Dört iddia var: kapalıyken arama bugün ne
döndürüyorsa onu döndürür (geriye dönük bir değişiklik yok), açıkken sonuçta özet vuruşu yoktur
ve `k` yerinde durur, özet bacağı gerçekten okunur (elle kurulmuş bir özet kendi tablosunu
yukarı taşır), ve `eval-retrieval --summaries on` dördüncü varyantı her soru için yazar.
"""

import json

import pytest

from nl2sql import config
from nl2sql.cli import main as cli
from nl2sql.datasets import load_dataset
from nl2sql.graph.graph import build_graph
from nl2sql.graph.profile import load_profile
from nl2sql.index.docs import Doc
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import METHODS, HybridSearch, build_search

DATASETS = ("wwi", "wwi")
QUERIES = (
    "stok hareketleri satış iade",
    "döviz kuru",
    "cari hesap ekstre",
    "sipariş teslim",
    "ürün stok miktarı",
)


def search_for(name: str) -> HybridSearch:
    """Kümenin gerçek üç girdisiyle bellekte kurulan indeks: özetler de içinde (R5-20)."""
    ds = load_dataset(name)
    schema = ds.schema()
    graph = build_graph(schema, load_profile(ds.profile_path))
    return build_search(schema, ds.rules(), FakeEmbedder(), graph)


def ids(hits) -> list[str]:
    return [hit.doc_id for hit in hits]


# ------------------------------------------------------------------ aramanın kendisi


@pytest.mark.parametrize("name", DATASETS)
def test_summaries_off_is_exactly_the_plain_table_search(name):
    search = search_for(name)

    for query in QUERIES:
        assert search.search_tables(query) == search.search(query, "tables", config.SEARCH_K)


@pytest.mark.parametrize("name", DATASETS)
def test_summaries_on_returns_only_tables_and_respects_k(name):
    search = search_for(name)

    for query in QUERIES:
        for k in (1, 3, config.SEARCH_K):
            hits = search.search_tables(query, k=k, summaries=True)
            assert len(hits) == k
            assert len({hit.doc_id for hit in hits}) == k, "aynı tablo iki kez girmez"
            assert all(hit.doc_id == f"table:{hit.title}" for hit in hits), "özet vuruşu sızamaz"
            assert [hit.rank for hit in hits] == list(range(1, k + 1))
            assert all(hit.score > 0 for hit in hits)


def test_a_summary_moves_its_own_table_up():
    """Elle kurulmuş dört doküman: TABLO_B'nin özeti sorguyu TABLO_A kadar iyi buluyor, tablo dokümanı değil."""
    docs = [
        Doc(id="table:TABLO_A", collection="tables", title="TABLO_A", text="alfa alfa"),
        Doc(id="table:TABLO_B", collection="tables", title="TABLO_B", text="alfa"),
        Doc(id="summary:TABLO_B", collection="summaries", title="TABLO_B", text="alfa alfa"),
    ]
    embedder = FakeEmbedder()
    search = HybridSearch(docs, embedder.embed([doc.text for doc in docs]), embedder)

    assert ids(search.search_tables("alfa", k=2)) == ["table:TABLO_A", "table:TABLO_B"]
    assert ids(search.search_tables("alfa", k=2, summaries=True)) == ["table:TABLO_B", "table:TABLO_A"]


# ------------------------------------------------------------------ eval-retrieval


@pytest.mark.parametrize("name", DATASETS)
def test_eval_retrieval_with_summaries_writes_the_variant_for_every_question(
    name, tmp_path, capsys
):
    out_dir = tmp_path / name

    assert cli.eval_retrieval("fake", dataset=name, out_dir=out_dir, summaries=True) == 0
    out = capsys.readouterr().out

    data = json.loads((out_dir / "latest" / "report.json").read_text(encoding="utf-8"))
    assert data["summaries"] is True
    assert list(data["variants"]) == ["base", "neighbours", "synonyms", "summaries"]
    entry = data["variants"]["summaries"]
    assert set(entry["questions"]) == {item["id"] for item in data["questions"]}
    assert set(entry["mean"]) == set(METHODS)
    assert set(entry["by_tag"]) == set(data["by_tag"]), "etiketler varyantla değişmez"
    assert "+özet" in out
    markdown = (out_dir / "latest" / "report.md").read_text(encoding="utf-8")
    assert "| Soru | taban | +komşu | +eşanlam | +özet |" in markdown


@pytest.mark.parametrize("name", DATASETS)
def test_eval_retrieval_without_summaries_has_no_summaries_variant(name, tmp_path, capsys):
    out_dir = tmp_path / name

    assert cli.eval_retrieval("fake", dataset=name, out_dir=out_dir) == 0
    out = capsys.readouterr().out

    data = json.loads((out_dir / "latest" / "report.json").read_text(encoding="utf-8"))
    assert data["summaries"] is False
    assert list(data["variants"]) == ["base", "neighbours", "synonyms"]
    assert "+özet" not in out
    assert "+özet" not in (out_dir / "latest" / "report.md").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("argv", "want"),
    [
        (["--summaries", "on"], {"embed": "fake", "k": config.SEARCH_K, "summaries": True}),
        (["--summaries", "off"], {"embed": "fake", "k": config.SEARCH_K, "summaries": False}),
        ([], {"embed": "fake", "k": config.SEARCH_K}),
    ],
)
def test_cli_routes_the_summaries_flag(argv, want, monkeypatch):
    seen = {}

    def record(**kwargs):
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "eval_retrieval", record)

    assert cli.main(["eval-retrieval", "--embed", "fake", *argv]) == 0
    assert seen == want
