"""T187: belirsiz soru kümesi (PLAN R5-12, Contracts "ambiguous line").

Burada ölçüm yok, kümenin sözleşmesi var: her okuma policy'den geçer ve kurulu dünyada çalışır,
bir sorunun iki okuması **aynı cevabı vermez** — verirse soru belirsiz değildir ve netleştirme
boşuna sorulur. Ayrıca hiçbir belirsiz soru golden'da da yoktur (aynı soru iki kez ölçülürdü) ve
hiçbirinin metni aranabilir metne sızmaz (R2-16 kuralı altın küme için zaten doğrulanmıştı).
"""

import itertools

import pytest

from nl2sql import config
from nl2sql.datasets import load_dataset
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.eval import compare
from nl2sql.eval.runner import load_golden
from nl2sql.index.docs import build_documents, leaks
from nl2sql.policy import policy
from nl2sql.schema_map import build, doc
from nl2sql.schema_map.rules import load_rules

DATASET = load_dataset("synthetic_erp")
LINES = DATASET.ambiguous()
IDS = [line["id"] for line in LINES]
TABLES = doc.allowlist(doc.load_schema())

# Okumalar karşılaştırılacağı için satır kesilmez (PLAN Decision 8).
COMPARE = Budget(max_rows=config.COMPARE_MAX_ROWS)


def build_db(tmp):
    """Tohum 42'nin SQLite dünyası ve o dünyaya bakan tek kapı."""
    path = tmp / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return LocalExecutor("sqlite", path, audit_path=tmp / "audit.jsonl")


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    return build_db(tmp_path_factory.mktemp("ambiguous-set"))


@pytest.fixture(scope="module")
def results(executor):
    """Her okumanın kurulu dünyadaki sonucu; policy ve ayrışma testi aynı çalışmayı paylaşır."""
    runs = {}
    for line in LINES:
        runs[line["id"]] = [
            executor.execute(reading["sql"], COMPARE, line["id"]) for reading in line["readings"]
        ]
    return runs


def test_the_set_is_wired_into_the_dataset():
    assert DATASET.ambiguous_path == DATASET.root / "ambiguous.jsonl"
    assert DATASET.ambiguous_path.is_file()
    assert len(LINES) >= 6, "PLAN R5-12 en az 6 belirsiz soru istiyor"


def test_ids_are_sequential_and_unique():
    assert IDS == [f"A{n:02d}" for n in range(1, len(LINES) + 1)]
    assert len(set(IDS)) == len(IDS)


def test_a01_is_the_visual_flow_question():
    assert LINES[0]["question"] == "Eylül 2026'da satışlarımız ne kadar?"


@pytest.mark.parametrize("line", LINES, ids=IDS)
def test_every_line_asks_for_a_clarification_with_distinct_readings(line):
    assert set(["id", "question", "expect", "term", "readings"]) <= set(line)
    assert line["expect"] == "clarify"
    assert line["term"] and line["question"]
    readings = line["readings"]
    assert 2 <= len(readings) <= config.CLARIFY_MAX_OPTIONS
    labels = [reading["label"] for reading in readings]
    assert all(label.strip() for label in labels)
    assert len(set(labels)) == len(labels), f"{line['id']}: okuma etiketleri aynı"
    assert all(reading["sql"].strip() for reading in readings)


@pytest.mark.parametrize("line", LINES, ids=IDS)
def test_every_reading_passes_the_policy_and_runs(line, results):
    for reading, result in zip(line["readings"], results[line["id"]]):
        verdict = policy.check(reading["sql"], TABLES)
        assert verdict.ok, f"{line['id']} [{reading['label']}]: {verdict.reason}"
        assert result.error is None, f"{line['id']} [{reading['label']}]: {result.error}"
        assert result.rows, f"{line['id']} [{reading['label']}] boş döndü; okuma hiçbir şey ölçmüyor"


@pytest.mark.parametrize("line", LINES, ids=IDS)
def test_every_pair_of_readings_gives_a_different_answer(line, results):
    runs = results[line["id"]]
    for (first, second) in itertools.combinations(range(len(runs)), 2):
        left, right = line["readings"][first], line["readings"][second]
        verdict = compare.compare(runs[first], runs[second])
        assert not verdict.match, f"{line['id']}: '{left['label']}' ile '{right['label']}' aynı cevap"


def test_no_ambiguous_question_is_also_a_golden_question():
    golden = {line["question"] for line in load_golden()}
    overlap = [line["id"] for line in LINES if line["question"] in golden]
    assert overlap == []


def test_no_ambiguous_question_leaks_into_the_searchable_text():
    docs = build_documents(doc.load_schema(), load_rules())
    assert leaks(docs, LINES) == []


def test_a_dataset_without_the_file_has_no_ambiguous_set():
    wwi = load_dataset("wwi")
    assert wwi.ambiguous_path is None
    assert wwi.ambiguous() == []
