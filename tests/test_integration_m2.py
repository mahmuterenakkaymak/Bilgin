# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""M2 entegrasyonu: kurulum -> LocalExecutor; model bütçesi ve saldırılar policy kapısında kalır.

Burada sahte hiçbir parça yok: gerçek build_db ile üretilmiş SQLite dosyası, gerçek policy,
gerçek çeviri ve gerçek backend. Golden SQL'lerin Python doğrularıyla karşılaştırması tek
parametrik teste taşındı (tests/test_golden_all.py, R3-1); burada modelin gördüğü bütçe ve
saldırı kümesinin reddedilip denetim satırına yazılması sınanır.
"""

import json
from pathlib import Path

import pytest

from bilgin import config
from bilgin.engine.executor import LocalExecutor
from bilgin.engine.result import Budget
from bilgin.schema_map import build

ENTRY_FIELDS = {"ts", "source", "sql", "elapsed_ms", "row_count", "outcome"}

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
def executor(db, tmp_path_factory):
    return LocalExecutor("sqlite", db, audit_path=tmp_path_factory.mktemp("m2-audit") / "audit.jsonl")


def entries(audit_path):
    text = Path(audit_path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


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
