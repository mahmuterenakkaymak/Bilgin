# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R5-5'in ikinci yarısı: katlanan join uyarısı (PLAN Contracts Warning satırı).

Oran gerçek veriden alınır: TBLFATUIRS sürücüyken TBLSTHAR'a cari üzerinden bağlanmak
satırları ~9 katına çıkarıyor, hareket fiş numarası üzerinden bağlanmak ~2 katında bırakıyor.
İkisi de test edildiği için eşik (config.FANOUT_FACTOR) da ölçülmüş oluyor, "join varsa uyarı"
değil. Sayımlar executor'dan geçtiği için denetim kaydı da burada okunuyor.
"""

import json

import pytest

from bilgin import config
from bilgin.engine import checks
from bilgin.engine.executor import LocalExecutor
from bilgin.engine.result import Budget
from bilgin.schema_map import build, doc

SCHEMA = doc.load_schema()
FULL = Budget(max_rows=100000)

AUGUST = "f.TARIH >= '2026-08-01' AND f.TARIH < '2026-09-01'"
JULY = "f.TARIH >= '2026-07-01' AND f.TARIH < '2026-08-01'"
SUMMER = "f.TARIH >= '2030-01-01' AND f.TARIH < '2030-02-01'"

# ASSUMPTION: görev FISNO joinini sayıyor; bu veri setinde bir faturanın ortalama iki hareket
# satırı var, yani oran 2,0 ve eşiğin (3,0) altında kalıyor. Uyarıyı gerçekten tetikleyen
# şekil, ERP'de aynı hatanın katlanarak büyüdüğü cari üzerinden kurulan join.
FAN_SQL = (
    "SELECT SUM(f.GENELTOPLAM) AS TOPLAM FROM TBLFATUIRS f "
    "JOIN TBLSTHAR s ON s.CARI_KODU = f.CARI_KODU WHERE " + AUGUST
)
NO_JOIN_SQL = "SELECT SUM(f.GENELTOPLAM) AS TOPLAM FROM TBLFATUIRS f WHERE " + AUGUST
PLAIN_JOIN_SQL = (
    "SELECT f.FATIRS_NO FROM TBLFATUIRS f "
    "JOIN TBLSTHAR s ON s.CARI_KODU = f.CARI_KODU WHERE " + AUGUST
)
FISNO_SQL = (
    "SELECT SUM(f.GENELTOPLAM) AS TOPLAM FROM TBLFATUIRS f "
    "JOIN TBLSTHAR s ON s.FISNO = f.FATIRS_NO WHERE " + AUGUST
)
NO_INVOICE_SQL = FAN_SQL.replace(AUGUST, SUMMER)
UNION_SQL = (
    "SELECT SUM(f.GENELTOPLAM) AS TOPLAM FROM TBLFATUIRS f "
    "JOIN TBLSTHAR s ON s.CARI_KODU = f.CARI_KODU WHERE " + AUGUST + " UNION ALL "
    "SELECT SUM(f.GENELTOPLAM) AS TOPLAM FROM TBLFATUIRS f "
    "JOIN TBLSTHAR s ON s.CARI_KODU = f.CARI_KODU WHERE " + JULY
)
CTE_SQL = (
    "WITH HAREKET AS (SELECT CARI_KODU FROM TBLSTHAR) "
    "SELECT SUM(f.GENELTOPLAM) AS TOPLAM FROM TBLFATUIRS f "
    "JOIN HAREKET h ON h.CARI_KODU = f.CARI_KODU WHERE " + AUGUST
)

JOINED_COUNT_SQL = (
    "SELECT COUNT(*) FROM TBLFATUIRS f JOIN TBLSTHAR s ON s.CARI_KODU = f.CARI_KODU WHERE " + AUGUST
)
DRIVING_COUNT_SQL = "SELECT COUNT(*) FROM TBLFATUIRS f WHERE " + AUGUST


def build_db(tmp):
    path = tmp / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return build_db(tmp_path_factory.mktemp("checks-fanout"))


@pytest.fixture
def executor(db, tmp_path):
    return LocalExecutor("sqlite", db, doc.allowlist(SCHEMA), tmp_path / "audit.jsonl", SCHEMA)


def test_a_fanning_join_warns_with_both_counts(executor):
    result = executor.execute(FAN_SQL, FULL)
    assert result.error is None and result.row_count == 1
    joined = executor.execute(JOINED_COUNT_SQL, FULL).rows[0][0]
    driving = executor.execute(DRIVING_COUNT_SQL, FULL).rows[0][0]
    assert joined / driving > config.FANOUT_FACTOR

    ratio = f"{joined / driving:.1f}".replace(".", ",")
    assert checks.post_checks(FAN_SQL, result, executor) == [
        checks.Warning(
            "fan_out",
            f"Join sonrası {joined} satır, sürücü tablo TBLFATUIRS {driving} satır ({ratio}x): "
            "toplamlar çoğalmış olabilir.",
        )
    ]


def test_the_same_sum_without_the_join_stays_quiet(executor):
    result = executor.execute(NO_JOIN_SQL, FULL)
    assert result.error is None and result.row_count == 1
    assert checks.post_checks(NO_JOIN_SQL, result, executor) == []


def test_a_join_without_an_aggregate_stays_quiet(executor):
    result = executor.execute(PLAIN_JOIN_SQL, FULL)
    assert result.error is None and result.row_count > 1
    assert checks.post_checks(PLAIN_JOIN_SQL, result, executor) == []


def test_a_join_that_only_doubles_its_rows_stays_under_the_threshold(executor):
    result = executor.execute(FISNO_SQL, FULL)
    assert result.error is None and result.row_count == 1
    assert checks.post_checks(FISNO_SQL, result, executor) == []


@pytest.mark.parametrize("sql", [UNION_SQL, CTE_SQL], ids=["union", "cte"])
def test_a_union_and_a_cte_are_not_measured_and_raise_nothing(executor, sql):
    result = executor.execute(sql, FULL)
    assert result.error is None and result.row_count
    assert checks.post_checks(sql, result, executor) == []


def test_a_driving_count_of_zero_is_never_divided(executor):
    result = executor.execute(NO_INVOICE_SQL, FULL)
    assert result.error is None and result.rows == [(None,)]
    assert [warning.code for warning in checks.post_checks(NO_INVOICE_SQL, result, executor)] == [
        "all_null"
    ]


def test_the_two_counts_are_audited_and_carry_no_rows(executor, tmp_path):
    result = executor.execute(FAN_SQL, FULL)
    checks.post_checks(FAN_SQL, result, executor)

    lines = [
        json.loads(line)
        for line in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    counts = [line for line in lines if line["source"] == checks.CHECK_SOURCE]
    assert len(counts) == 2
    assert all(
        "COUNT(*)" in line["sql"] and line["outcome"] == "ok" and "rows" not in line
        for line in counts
    )
    assert [line["row_count"] for line in counts] == [1, 1]
