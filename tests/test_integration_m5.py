# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T57: M5 entegrasyonu — diske yazılmış gerçek indeks, gerçek 40 altın soruyla aranır.

Zincirin halkalarının hiçbiri taklit değil: gerçek schema.json + rules.json -> dokümanlar ->
FakeEmbedder -> FileStore -> load_search -> run_retrieval. Sahte olan tek şey ağı olmayan embedder;
ölçütün kendisi (recall@k) altın satırdaki gerçek tablo listesi üzerinden hesaplanıyor. Aynı zincir
üzerinde iki sözleşme daha burada birleşiyor: içerik imzası kıpırdarsa indeks yüklenmez (bayatlık
sessiz tolere edilmez) ve altın sorunun dili aranabilir metne sızmaz.
"""

import json

import pytest

from bilgin import config
from bilgin.eval.retrieval import run_retrieval
from bilgin.eval.runner import load_golden
from bilgin.graph.graph import build_graph
from bilgin.graph.profile import load_profile
from bilgin.index.docs import build_documents, leaks
from bilgin.index.embed import FakeEmbedder
from bilgin.index.search import METHODS, load_search
from bilgin.index.store import FileStore, StaleIndexError, content_hash
from bilgin.schema_map.doc import load_schema
from bilgin.schema_map.rules import load_rules
from test_graph_path import _golden_joins, _sides

IDS = [f"Q{i:02d}" for i in range(1, 41)]
SCHEMA = load_schema()
RULES = load_rules()
GOLDEN = load_golden()
BY_ID = {line["id"]: line for line in GOLDEN}
MULTI_JOIN = [line for line in GOLDEN if "multi_join" in line["tags"]]
EMBEDDER = FakeEmbedder()
DOCS = build_documents(SCHEMA, RULES)


@pytest.fixture(scope="module")
def index_dir(tmp_path_factory):
    """`build-index`'in ürettiği üç dosya: gerçek şema, gerçek kurallar, gerçek bir dizin."""
    directory = tmp_path_factory.mktemp("m5")
    FileStore(directory).save(
        DOCS,
        EMBEDDER.embed([doc.text for doc in DOCS]),
        {
            "content_hash": content_hash(SCHEMA, RULES),
            "embedder": EMBEDDER.id,
            "dim": EMBEDDER.dim,
        },
    )
    return directory


# ------------------------------------------------------- diskteki indeks -> ölçümün kendisi


def test_the_stored_index_is_measured_over_every_golden_question(index_dir):
    report = run_retrieval(load_search(index_dir, SCHEMA, RULES), GOLDEN, k=config.SEARCH_K)

    assert report["k"] == config.SEARCH_K and report["embedder"] == EMBEDDER.id
    assert [item["id"] for item in report["questions"]] == IDS, "40 sorunun her biri satır olmalı"
    for item in report["questions"]:
        assert item["requires"] == BY_ID[item["id"]]["requires_tables"]
        for method in METHODS:
            assert 0.0 <= item[method] <= 1.0, f"{item['id']} {method} geri çağırması aralıkta değil"
            assert set(item["missing"][method]) <= set(item["requires"])
    assert set(report["mean"]) == set(METHODS)
    assert all(0.0 <= value <= 1.0 for value in report["mean"].values())
    assert report["by_tag"], "etiket ortalamaları yoksa R2-15 hedefleri hiçbir şey ölçmüyor"


def test_an_edited_rule_definition_makes_the_stored_index_stale(index_dir, tmp_path):
    """Tanım değişince aynı dosyalar başka içeriğin indeksi sayılır; yüklemek yerine patlar (R2-9)."""
    data = json.loads(config.RULES_PATH.read_text(encoding="utf-8"))
    data["rules"][0]["definition"] += " (elle değiştirilmiş tanım)"
    edited = tmp_path / "rules.json"
    edited.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(StaleIndexError, match="build-index"):
        load_search(index_dir, SCHEMA, load_rules(edited))


# ------------------------------------------------------- altın soru aranabilir metne sızmaz


def test_no_golden_question_leaks_into_the_searchable_text():
    assert leaks(DOCS, GOLDEN) == []


# ------------------------------------------------------- join graphı golden joinleri taşıyor


def test_the_graph_holds_every_join_a_multi_join_golden_uses():
    assert MULTI_JOIN, "multi_join etiketi yoksa bu test hiçbir şey denemiyor"
    edges = {_sides(edge) for edge in build_graph(SCHEMA, load_profile()).edges}
    missing = [
        f"{line['id']}: " + " = ".join(".".join(side) for side in sorted(condition))
        for line in MULTI_JOIN
        for condition in _golden_joins(line["sql"]) - edges
    ]
    assert missing == [], "golden SQL'in join'i graph'ın kenarlarında yok"
