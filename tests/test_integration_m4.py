"""T46: M4 entegrasyonu — kurulu dünyada 40 golden SQL policy'den geçer ve Python doğrularına eşittir.

Zincirin hiçbir halkası sahte değil: gerçek generator, gerçek build_db, gerçek LocalExecutor (policy
-> çeviri -> SQLite), doğrular eval/reference.py. Aynı dünya üzerinden Run 1 pin'i, şemadaki her
tablonun kurulması, her kuralın en az bir soru tarafından iddia edilmesi ve R2-15 etiket hedefleri de
burada sınanır; halkalardan biri kopsun, milletin tamamı kırmızıya döner.
"""

import re
import sqlite3
from decimal import ROUND_HALF_UP, Decimal

import pytest

from eval import reference
from nl2sql import config
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.eval.runner import load_golden
from nl2sql.policy import policy
from nl2sql.schema_map import build, doc, generator, rules
from test_run1_world import RUN1_FINGERPRINT, fingerprint

IDS = [f"Q{i:02d}" for i in range(1, 41)]
GOLDEN = load_golden()
BY_ID = {line["id"]: line for line in GOLDEN}
TABLES = doc.allowlist(doc.load_schema())
RULES = {rule["id"]: rule for rule in rules.load_rules()}

# R2-15 hedefleri: Q01-Q40 bu etiketleri en az bu kadar taşır.
TAG_MINIMUMS = {"needs_rule": 8, "multi_join": 8, "distractor": 8, "needs_values": 8, "archive": 5}

# Eval karşılaştırma bütçesi: ne golden'ın ne doğrunun satırı kesilmesin (PLAN Decision 8).
COMPARE = Budget(max_rows=config.COMPARE_MAX_ROWS)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("m4") / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture(scope="module")
def executor(db, tmp_path_factory):
    return LocalExecutor("sqlite", db, audit_path=tmp_path_factory.mktemp("m4-audit") / "audit.jsonl")


@pytest.fixture(scope="module")
def dataset():
    return generator.generate(config.SEED)


def cell(value):
    """Sayıları 2 haneye indirir; yığma ondalık farkı doğruyu SQL ile kapıştırmasın."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    stable = Decimal(repr(round(float(value), 6)))
    return float(stable.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def comparable(rows, ordered):
    """ordered=True sırayı da karşılaştırır; değilse çok küme olarak sıralanır."""
    values = [tuple(map(cell, row)) for row in rows]
    return values if ordered else sorted(values, key=repr)


def collapse(sql):
    return re.sub(r"\s+", " ", sql).strip()


def claims(rule_id):
    return [line for line in GOLDEN if rule_id in line["rules"]]


# ----------------------------------------------------------------- aynı dünya, aynı sorular


def test_the_forty_questions_are_written_and_measured():
    assert [line["id"] for line in GOLDEN] == IDS, "golden Q01-Q40 olmalı"
    assert sorted(reference.REFERENCES) == IDS, "her sorunun saf Python doğrusu olmalı"


def test_the_world_still_replays_the_pinned_run1_fingerprint(dataset):
    """Doğrular bu dünyadan ölçülüyor; Run 1 tarafı kıpırdarsa 40 cevabın tamamı geçersizdir."""
    assert fingerprint(dataset) == RUN1_FINGERPRINT


def test_every_schema_table_is_built(db):
    conn = sqlite3.connect(db)
    try:
        created = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            if not row[0].startswith("sqlite_")
        }
    finally:
        conn.close()
    assert created == {table["name"] for table in doc.load_schema()["tables"]}


# ----------------------------------------------------------------- golden -> policy -> executor -> doğru


@pytest.mark.parametrize("qid", IDS)
def test_golden_sql_passes_the_policy(qid):
    verdict = policy.check(BY_ID[qid]["sql"], TABLES)
    assert verdict.ok, f"{qid}: {verdict.reason}"


@pytest.mark.parametrize("qid", IDS)
def test_golden_answer_equals_the_reference(qid, executor, dataset):
    line = BY_ID[qid]
    result = executor.execute(line["sql"], COMPARE, qid)
    assert result.error is None, f"{qid} executor'da reddedildi: {result.error}"
    assert result.rows, f"{qid} boş döndü; soru hiçbir şey ölçmüyor"
    assert result.row_count == len(result.rows) and result.truncated is False, f"{qid} bütçeye sığmadı"
    expected = comparable(reference.REFERENCES[qid](dataset), line["ordered"])
    assert comparable(result.rows, line["ordered"]) == expected, f"{qid} SQL sonucu Python doğrulundan farklı"


# ----------------------------------------------------------------- kurallar iddia ettikleri SQL'lere uyar


def test_every_rule_is_claimed_by_at_least_one_question():
    unclaimed = sorted(set(RULES) - {rule_id for line in GOLDEN for rule_id in line["rules"]})
    assert not unclaimed, f"hiçbir soru bu kuralları iddia etmiyor: {unclaimed}"


@pytest.mark.parametrize("rule_id", sorted(RULES))
def test_the_markers_of_a_rule_match_every_sql_that_claims_it(rule_id):
    for line in claims(rule_id):
        for marker in RULES[rule_id]["markers"]:
            found = re.search(marker, collapse(line["sql"]), re.IGNORECASE)
            assert found, f"{line['id']} {rule_id} kuralını iddia edip işaretçisini taşımıyor: {marker}"


# ----------------------------------------------------------------- R2-15 etiket hedefleri


@pytest.mark.parametrize("tag", sorted(TAG_MINIMUMS))
def test_the_tag_meets_its_run2_target(tag):
    found = sum(1 for line in GOLDEN if tag in line["tags"])
    assert found >= TAG_MINIMUMS[tag], f"{tag} etiketi {found} soruda var, hedef {TAG_MINIMUMS[tag]}"
