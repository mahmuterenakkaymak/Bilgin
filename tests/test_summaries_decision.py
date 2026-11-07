# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R5-20 kararı: özet bacağı aramada kalıyor mu — ölçümün kendisi test altında.

Kural ölçümden önce sabitlendi (PLAN R5-20): `config.TABLE_SUMMARIES` iki kümenin *ikisinde de*
özetli hybrid recall@5 özetisizden az değilse True. Test sayıları eval/SUMMARIES.md'den okumaz,
bellekte yeniden ölçer; böylece sabit ile ölçümün aynı noktada durduğu her koşumda sınanır. İki
yönü de tutuyor: karar yanlışsa sabit, belge yanlışsa sayılar kırılır. Üçüncü iddia sabitin
gerçekten aramaya geçtiği — `search_schema` cevabı hangi bacakten geliyorsa o bacağın tablosunu taşır.
"""

from nl2sql import config
from nl2sql.agent import modes, tools
from nl2sql.datasets import load_dataset
from nl2sql.eval import retrieval
from nl2sql.graph.graph import build_graph
from nl2sql.graph.profile import load_profile
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import Hit, build_search

DATASETS = ("synthetic_erp", "wwi")
DECISION = config.ROOT / "eval" / "SUMMARIES.md"
SCHEMA = {
    "tables": [
        {"name": "TBLTABAN", "description": "taban bacağın tablosu", "columns": []},
        {"name": "TBLOZET", "description": "özet bacağın tablosu", "columns": []},
    ]
}


def hybrid_recall(name: str) -> tuple[float, float]:
    """Kümenin altın sorularında bellekte ölçülmüş hybrid recall@5: (özetisiz, özetli)."""
    ds = load_dataset(name)
    schema = ds.schema()
    graph = build_graph(schema, load_profile(ds.profile_path))
    search = build_search(schema, ds.rules(), FakeEmbedder(), graph)
    return tuple(
        retrieval.run_retrieval(search, ds.golden(), config.SEARCH_K, summaries=on)["mean"]["hybrid"]
        for on in (False, True)
    )


# Ölçüm pahalı, iki test de aynı sayıları okuyor; modül düzeyinde bir kez koşulur (test_tools_rag gibi).
RECALLS = {name: hybrid_recall(name) for name in DATASETS}


def _hit(name: str) -> Hit:
    return Hit(doc_id=f"table:{name}", title=name, score=1.0, rank=1)


class _TwoLegs:
    """İki bacak ayrı tablo döndürür: cevapta hangisi varsa okunan bacak odur; `search_tables` çağrıları birikir."""

    def __init__(self) -> None:
        self.summaries: list[bool] = []

    def search(self, query, collection: str = "tables", k: int = config.SEARCH_K, **_):
        return [_hit("TBLTABAN")]

    def search_tables(self, query, k: int = config.SEARCH_K, summaries: bool = False):
        self.summaries.append(summaries)
        return [_hit("TBLOZET")]


def _context(search) -> modes.ToolContext:
    return modes.ToolContext(
        executor=None, schema=SCHEMA, rules=[], search=search, graph=None, mode="rag"
    )


# ------------------------------------------------------------------ karar


def test_table_summaries_is_the_rule_measured_now():
    expected = all(summaries >= plain for plain, summaries in RECALLS.values())

    assert config.TABLE_SUMMARIES is expected, RECALLS


def test_the_decision_doc_carries_both_datasets_and_their_hybrid_numbers():
    text = DECISION.read_text(encoding="utf-8")

    for name, (plain, summaries) in RECALLS.items():
        assert name in text, f"{name} belgede yok"
        for value in (plain, summaries):
            assert f"{value:.2f}" in text, f"{name} {value:.2f} belgede yok"


# ------------------------------------------------------------------ sabitin aramaya geçmesi


def test_search_schema_answers_come_from_search_tables_with_the_constant(monkeypatch):
    for value in (True, False):
        monkeypatch.setattr(config, "TABLE_SUMMARIES", value)
        search = _TwoLegs()

        answer = tools.dispatch("search_schema", {"query": "stok hareketleri"}, _context(search))

        assert search.summaries == ([value] if value else []), "sabit kapalıyken özet bacağı okunmaz"
        assert ("TBLOZET" if value else "TBLTABAN") in answer
