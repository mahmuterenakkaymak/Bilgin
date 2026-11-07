# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T66: M6 entegrasyonu — zincirin tamamı ``eval --compare`` yolundan, tmp yollarda.

Halkaların hiçbiri taklit: gerçek 40 altın soruyu modun kendi kaydı (``fake.for_golden``) gerçek bir
``LocalExecutor``'a yürütür, rag modu diske yazılmış gerçek ``FileStore`` indeksini ve gerçek join
graphını kullanır, üç modun raporu ile karşılaştırma raporu tmp klasöre gider. Ölçülen şey fazın
iddiası: rag aynı 40/40'ı belirgin biçimde küçük bir tepe bağlamla alıyor, o yüzden karar satırı
``RAG kalır`` diyor (R2-13).
"""

import json

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.cli import main as cli
from nl2sql.eval import runner
from nl2sql.index.docs import build_documents
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import load_search
from nl2sql.index.store import FileStore, content_hash
from nl2sql.schema_map import build, doc
from nl2sql.schema_map.rules import load_rules

MODES = list(config.MODES)
SCHEMA = doc.load_schema()
RULES = load_rules()
GOLDEN = runner.load_golden()
TOTAL = len(GOLDEN)
EMBEDDER = FakeEmbedder()
DOCS = build_documents(SCHEMA, RULES)
JOIN_MARK = " = "
NO_CONTEXT = ("arama indeksi yok", "join graph yok")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Gerçek dünya tmp klasörde: SQLite dosyası, diskteki indeks ve audit tek yerde."""
    root = tmp_path_factory.mktemp("m6")
    database = root / "test.db"
    build.build_db(config.SEED, database, root / "test.sql")
    index_dir = root / "index"
    FileStore(index_dir).save(
        DOCS,
        EMBEDDER.embed([item.text for item in DOCS]),
        {
            "content_hash": content_hash(SCHEMA, RULES),
            "embedder": EMBEDDER.id,
            "dim": EMBEDDER.dim,
        },
    )
    return database, index_dir, root / "audit.jsonl"


@pytest.fixture(scope="module")
def compared(world, tmp_path_factory):
    """Tek ``eval --compare``: üç modun raporu ve karşılaştırma aynı tmp klasörde."""
    database, index_dir, audit = world
    out_dir = tmp_path_factory.mktemp("m6-out") / "eval_out"
    code = cli.compare_modes(
        lambda mode: fake.for_golden(GOLDEN, mode=mode),
        db_path=database,
        audit_path=audit,
        out_dir=out_dir,
        index_dir=index_dir,
    )
    return code, out_dir


def read(out_dir, *parts: str) -> dict:
    return json.loads(out_dir.joinpath(*parts).read_text(encoding="utf-8"))


def test_the_rag_side_loads_the_index_that_was_written_to_disk(world):
    """Meta'daki embedder kimliği sorgu tarafını da taşır; imza eşitse indeks bayat sayılmaz (R2-9)."""
    _, index_dir, _ = world
    assert load_search(index_dir, SCHEMA, RULES).embedder.id == EMBEDDER.id


def test_every_mode_answers_every_golden_question(compared):
    code, out_dir = compared
    data = read(out_dir, "compare", "latest", "report.json")

    assert code == 0
    assert list(data["modes"]) == MODES
    assert data["questions"] == TOTAL
    for mode in MODES:
        assert data["modes"][mode]["score"] == {"passed": TOTAL, "total": TOTAL}
        outcomes = [q["outcome"] for q in read(out_dir, mode, "latest", "report.json")["questions"]]
        assert outcomes.count("pass") == TOTAL, f"{mode} modunda geçmeyen soru var"


def test_the_verdict_line_is_in_both_compare_files(compared):
    _, out_dir = compared
    data = read(out_dir, "compare", "latest", "report.json")
    markdown = (out_dir / "compare" / "latest" / "report.md").read_text(encoding="utf-8")

    assert data["verdict"]["line"].startswith("Karar:")
    assert data["verdict"]["line"] in markdown
    assert data["verdict"]["keep_rag"] is True


def test_rag_buys_the_same_score_with_a_smaller_peak_context(compared):
    _, out_dir = compared
    data = read(out_dir, "compare", "latest", "report.json")

    assert data["schema_tokens"] > 0, "şema tahmini yoksa full modun maliyeti ölçülmüyor"
    rag = data["modes"]["rag"]["context"]["max_prompt_tokens"]
    rules = data["modes"]["full_rules"]["context"]["max_prompt_tokens"]
    assert 0 < rag < rules


def test_the_rag_answers_came_through_the_index_and_the_graph(compared):
    """Araç cevapları gerçek indeks ve gerçek graph tarafından üretildi; bağlam eksikse bu düşer."""
    _, out_dir = compared
    steps = [
        step
        for question in read(out_dir, "rag", "latest", "report.json")["questions"]
        for step in question["steps"]
    ]

    assert {"search_schema", "get_table_details", "find_join_path"} <= {
        step["tool"] for step in steps
    }
    assert not [
        step for step in steps if any(mark in step["summary"] for mark in NO_CONTEXT)
    ], "modun bağlamı eksik kurulmuş"
    joins = [step for step in steps if step["tool"] == "find_join_path"]
    assert any(step["ok"] and JOIN_MARK in step["summary"] for step in joins), "gerçek join yolu çıkmadı"


def test_only_the_rag_report_is_bound_to_an_index(compared):
    """İmza rag'i içindek imzasına bağlar; diğer iki modun indeksle ölçülecek bir şeyi yok (R2-12)."""
    _, out_dir = compared

    for mode in MODES:
        fingerprint = read(out_dir, mode, "latest", "report.json")["config"]["fingerprint"]
        expected = content_hash(SCHEMA, RULES) if mode == "rag" else ""
        assert fingerprint["index_hash"] == expected
        assert fingerprint["max_tool_calls"] == config.MAX_TOOL_CALLS_BY_MODE[mode]
