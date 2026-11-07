# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T104: R3-9 varyantları — +komşu ve +eşanlam tabanın altına düşmemeli.

Ölçümün kendisi gerçek: gerçek şema + gerçek kurallar + FakeEmbedder bellekte, 40 altın soru,
recall@5. Genişletme listeye yalnız eklediği için geri çağırmayı matematiksel olarak düşüremez;
asıl soru eş anlamlı genişletmesinin sözcük bacağının sırasını bozup bozmaması, yani hüküm
testin iddiasından değil ölçümden çıkıyor. Eşitliğin tesadüf (ya da düğmenin takılı olmaması)
olmadığını iki dar test ayırt ediyor: elle kurulmuş bir graph gerçek bir sorunun eksik tablosunu
bulur, eş anlamlı düğmesi de aramaya gerçekten ulaşır.
"""

import json

import pytest

from nl2sql import config
from nl2sql.cli import main as cli
from nl2sql.eval import retrieval, runner
from nl2sql.graph.graph import Edge, JoinGraph, build_graph
from nl2sql.graph.profile import load_profile
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import METHODS, build_search
from nl2sql.schema_map import doc
from nl2sql.schema_map.rules import load_rules

SCHEMA = doc.load_schema()
RULES = load_rules()
GOLDEN = runner.load_golden()
GRAPH = build_graph(SCHEMA, load_profile())
SEARCH = build_search(SCHEMA, RULES, FakeEmbedder())
K = 5
DATA = {table["name"] for table in SCHEMA["tables"] if table.get("kind") != "distractor"}

BASE = retrieval.run_retrieval(SEARCH, GOLDEN, K)


class Recorder:
    """Aramanın eş anlamlı düğmesine gerçekten ne geçtiğini kaydeden sarmalayıcı."""

    def __init__(self, inner) -> None:
        self.inner = inner
        self.rewrites: list[bool] = []

    @property
    def embedder(self):
        return self.inner.embedder

    def search(self, query, collection="tables", k=config.SEARCH_K, method="hybrid", rewrite=False):
        self.rewrites.append(rewrite)
        return self.inner.search(query, collection=collection, k=k, method=method, rewrite=rewrite)


def weak_case():
    """Tabanın kaçırdığı bir tablo + o tabloya asılabilecek, bulunmuş bir tablo."""
    for item in BASE["questions"]:
        missing = [table for table in item["missing"]["hybrid"] if table in DATA]
        found = [table for table in item["requires"] if table not in item["missing"]["hybrid"]]
        if missing and found:
            return item, found[0], missing[0]
    raise AssertionError("komşulukla kapatılabilecek tek bir eksik yoksa test hiçbir şey denemiyor")


# ------------------------------------------------------------------ hükmün kendisi


def test_neither_variant_lowers_recall_at_5():
    expanded = retrieval.run_retrieval(SEARCH, GOLDEN, K, expand=True, graph=GRAPH, schema=SCHEMA)
    rewritten = retrieval.run_retrieval(SEARCH, GOLDEN, K, rewrite=True)

    for method in METHODS:
        assert expanded["mean"][method] >= BASE["mean"][method]
        assert rewritten["mean"][method] >= BASE["mean"][method]


# ------------------------------------------------------------------ düğmeler takılı mı


def test_the_expansion_is_actually_measured():
    weak, anchor, missing = weak_case()
    graph = JoinGraph([Edge(anchor, "KODU", missing, "KODU", 1.0, "fk")], [anchor, missing])

    report = retrieval.run_retrieval(SEARCH, GOLDEN, K, expand=True, graph=graph, schema=SCHEMA)

    entry = next(item for item in report["questions"] if item["id"] == weak["id"])
    assert entry["hybrid"] > weak["hybrid"], "genişletme ölçüme hiç girmedi"
    assert missing not in entry["missing"]["hybrid"]


def test_expansion_without_a_graph_is_not_a_quiet_base_run():
    with pytest.raises(ValueError, match="graph"):
        retrieval.run_retrieval(SEARCH, GOLDEN, K, expand=True, schema=SCHEMA)


def test_the_rewrite_flag_reaches_the_search():
    recorder = Recorder(SEARCH)
    retrieval.run_retrieval(recorder, GOLDEN[:1], K, rewrite=True)
    assert set(recorder.rewrites) == {True}

    recorder = Recorder(SEARCH)
    retrieval.run_retrieval(recorder, GOLDEN[:1], K)
    assert set(recorder.rewrites) == {False}, "taban araması düğmeyi aramanın kendi haline bırakır"


# ------------------------------------------------------------------ rapor ve ekran


def test_the_report_carries_every_variant_with_mean_and_by_tag():
    report = retrieval.run_variants(SEARCH, GOLDEN, K, GRAPH, SCHEMA)

    assert list(report["variants"]) == ["base", "neighbours", "synonyms"]
    assert report["mean"] == BASE["mean"], "gövde taban ölçümünün ta kendisi olmalı"
    ids = {item["id"] for item in report["questions"]}
    for entry in report["variants"].values():
        assert set(entry["mean"]) == set(METHODS)
        assert set(entry["by_tag"]) == set(report["by_tag"]), "etiketler varyantla değişmez"
        assert set(entry["questions"]) == ids


def test_the_console_shows_the_variants_per_question_and_in_mean():
    lines = retrieval.console_lines(retrieval.run_variants(SEARCH, GOLDEN, K, GRAPH, SCHEMA))

    assert lines[0].startswith("Soru") and "eksik" in lines[0], "taban tablosu yerinde duruyor"
    header = next(line for line in lines if "taban" in line and "+komşu" in line)
    assert "+eşanlam" in header and header.index("taban") < header.index("+komşu")
    rows = lines[lines.index(header) + 1 :][: len(GOLDEN)]
    assert all(row.split()[0] == line["id"] for row, line in zip(rows, GOLDEN))
    means = next(line for line in lines if line.startswith("Varyant ortalamaları"))
    tail = lines[lines.index(means) + 1 :][:3]
    assert [row.split()[0] for row in tail] == ["taban", "+komşu", "+eşanlam"]
    for row in tail:
        assert len(row.split()) == 4, "varyant adı + üç metod"


def test_cli_prints_and_writes_the_three_variants(tmp_path, capsys):
    out_dir = tmp_path / "retrieval"

    assert cli.eval_retrieval("fake", out_dir=out_dir) == 0
    out = capsys.readouterr().out

    assert "taban" in out and "+komşu" in out and "+eşanlam" in out
    assert "Varyant ortalamaları" in out
    data = json.loads((out_dir / "latest" / "report.json").read_text(encoding="utf-8"))
    assert list(data["variants"]) == ["base", "neighbours", "synonyms"]
    assert data["variants"]["base"]["mean"] == data["mean"]
    markdown = (out_dir / "latest" / "report.md").read_text(encoding="utf-8")
    assert "| Soru | taban | +komşu | +eşanlam |" in markdown
    assert "| Varyant | hybrid | bm25 | dense |" in markdown
