"""M2 entegrasyonu: kurulum -> LocalExecutor -> Python doğruları; saldırılar policy kapısında kalır.

Burada sahte hiçbir parça yok: gerçek build_db ile üretilmiş SQLite dosyası, gerçek policy,
gerçek çeviri ve gerçek backend. Golden SQL'ler eval/reference.py ile, saldırı kümesi de
reddedilip denetim satırına yazılmış olmasıyla sınanır.
"""

import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest

from eval import reference
from nl2sql import config
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.schema_map import build, generator

ENTRY_FIELDS = {"ts", "source", "sql", "elapsed_ms", "row_count", "outcome"}

GOLDEN = [json.loads(line) for line in config.GOLDEN_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
IDS = [line["id"] for line in GOLDEN]
BY_ID = {line["id"]: line for line in GOLDEN}

MALICIOUS = [
    json.loads(line)
    for line in (Path(__file__).parent / "data" / "malicious.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]

# Eval karşılaştırma bütçesi: ne golden'ın ne doğrunun satırı kesilmesin (PLAN Decision 8).
COMPARE = Budget(max_rows=config.COMPARE_MAX_ROWS)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("m2") / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture(scope="module")
def dataset():
    return generator.generate(config.SEED)


@pytest.fixture(scope="module")
def executor(db, tmp_path_factory):
    return LocalExecutor("sqlite", db, audit_path=tmp_path_factory.mktemp("m2-audit") / "audit.jsonl")


def entries(audit_path):
    text = Path(audit_path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def cell(value):
    """Sayıları 2 haneye indirir; yığma ondalık farkı doğruyu SQL ile kapıştırmasın."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    stable = Decimal(repr(round(float(value), 6)))
    return float(stable.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def comparable(rows, ordered):
    """ordered=True sırayı da karşılaştırır (yalnız Q02); değilse çok küme olarak sıralanır."""
    values = [tuple(map(cell, row)) for row in rows]
    return values if ordered else sorted(values, key=repr)


# ----------------------------------------------------------------- golden == reference, executor üzerinden


@pytest.mark.parametrize("qid", IDS)
def test_golden_sql_through_the_executor_matches_the_reference(qid, executor, dataset):
    line = BY_ID[qid]
    result = executor.execute(line["sql"], COMPARE, qid)
    assert result.error is None, f"{qid} executor'da reddedildi: {result.error}"
    assert result.row_count == len(result.rows) and result.truncated is False, f"{qid} bütçeye sığmadı"
    assert result.columns and all(len(row) == len(result.columns) for row in result.rows)
    expected = comparable(reference.REFERENCES[qid](dataset), line["ordered"])
    assert comparable(result.rows, line["ordered"]) == expected, f"{qid} SQL sonucu Python doğrulundan farklı"


def test_every_golden_answer_is_nonempty_through_the_executor(executor, dataset):
    """Boş sonuç doğruya eşit olsa bile bir şey ölçmüyor; executor hattında da dolu olmalı."""
    for qid in IDS:
        assert executor.execute(BY_ID[qid]["sql"], COMPARE, qid).rows, f"{qid} boş döndü"


# ----------------------------------------------------------------- model bütçesi


def test_model_budget_shows_fifty_rows_but_keeps_the_total(executor):
    sql = "SELECT STOK_KODU, STHAR_TARIH FROM TBLSTHAR ORDER BY STOK_KODU, STHAR_TARIH"
    assert config.MODEL_MAX_ROWS == 50
    full = executor.execute(sql, COMPARE, "ask")
    assert full.error is None and full.row_count > config.MODEL_MAX_ROWS
    model = executor.execute(sql, source="ask")  # bütçesiz çağrı = modelin gördüğü bütçe
    assert model.error is None
    assert len(model.rows) == 50
    assert model.truncated is True
    assert model.row_count == full.row_count, "kesilen satırlar da sayılmalı"
    assert model.rows == full.rows[:50]


# ----------------------------------------------------------------- saldırı kümesi


@pytest.mark.parametrize("case", MALICIOUS, ids=[case["id"] for case in MALICIOUS])
def test_malicious_sql_is_refused_by_the_executor_and_audited(case, db, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    result = LocalExecutor("sqlite", db, audit_path=audit_path).execute(
        case["sql"], COMPARE, f"malicious:{case['id']}"
    )
    assert result.error.kind == "policy", f'{case["id"]} çalıştı: {case["sql"]!r}'
    assert result.error.message.strip()
    assert result.rows == [] and result.row_count == 0
    entry = entries(audit_path)[0]
    assert entry["outcome"] == "policy"
    assert entry["source"] == f"malicious:{case['id']}"
    assert entry["sql"] == case["sql"], "denetimde çevrilmiş değil istenen SQL yazar"


def test_the_whole_malicious_set_is_refused_and_the_database_is_untouched(db, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    ex = LocalExecutor("sqlite", db, audit_path=audit_path)
    before = build.checksum(db)
    for case in MALICIOUS:
        assert ex.execute(case["sql"], COMPARE, case["id"]).error.kind == "policy", case["id"]
    assert build.checksum(db) == before, "reddedilen bir sorgu veriye dokunmuş"
    logged = entries(audit_path)
    assert [entry["outcome"] for entry in logged] == ["policy"] * len(MALICIOUS)
    assert all(set(entry) == ENTRY_FIELDS and "rows" not in entry for entry in logged)
