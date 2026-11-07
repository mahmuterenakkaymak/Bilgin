# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""MONTH/YEAR/DAY, DATEPART ve LEFT SQLite'ta da SQL Server'in cevabini vermeli.

Kirilan yer ceviri adimi: sqlglot MONTH(TARIH)'i MONTH(DATE(TARIH)) olarak birakiyordu,
SQLite'ta o islev yok ("no such function"); DATEPART(month, TARIH) EXTRACT(month FROM ...)
oluyordu, ki SQLite bunu soz dizimi olarak bile kabul etmiyor; LEFT de SQLite'ta yok. Ucunde
de ayni model SQL'i SQL Server'da calisirken SQLite'ta hata veriyor, yani soru yedeklerine
gore farkli yargilaniyordu. Karsilastirma degerleri uretilen veriden ve Python takviminden
aliniyor; cevirenin kendi ciktilariyla karsilastirma yapilmiyor.
"""

import datetime as dt

import pytest

from nl2sql import config
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.policy import policy
from nl2sql.schema_map import build, doc, generator

# Karsilastirma butcesi: satir kesme yok, tum faturalar ve kartlar gorunmeli.
COMPARE = Budget(max_rows=config.COMPARE_MAX_ROWS)

LITERAL = "2026-09-05"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("tsqlfn") / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture(scope="module")
def executor(db, tmp_path_factory):
    return LocalExecutor(
        "sqlite", db, audit_path=tmp_path_factory.mktemp("tsqlfn-audit") / "audit.jsonl"
    )


@pytest.fixture(scope="module")
def invoices():
    return generator.generate(config.SEED)["TBLFATUIRS"]


@pytest.fixture(scope="module")
def stocks():
    return generator.generate(config.SEED)["TBLSTSABIT"]


def run(executor, sql):
    result = executor.execute(sql, COMPARE, "ask")
    assert result.error is None, f"sorgu calismadi: {result.error}"
    return result


def cell(executor, sql):
    result = run(executor, sql)
    assert len(result.rows) == 1, f"tek satir beklenmisti: {result.rows}"
    return result.rows[0][0]


def parts(iso: str) -> tuple[int, int, int]:
    date = dt.date.fromisoformat(iso)
    return date.month, date.year, date.day


# ----------------------------------------------------------------- MONTH / YEAR / DAY


def test_month_year_day_on_a_literal_give_the_calendar_parts(executor):
    sql = f"SELECT MONTH('{LITERAL}') AS AY, YEAR('{LITERAL}') AS YIL, DAY('{LITERAL}') AS GUN"
    assert run(executor, sql).rows == [(9, 2026, 5)]


def test_month_year_day_on_a_date_column_match_the_real_calendar(executor, invoices):
    sql = (
        "SELECT TARIH, MONTH(TARIH) AS AY, YEAR(TARIH) AS YIL, DAY(TARIH) AS GUN "
        "FROM TBLFATUIRS"
    )
    assert sorted(run(executor, sql).rows) == sorted(
        (row["TARIH"], *parts(row["TARIH"])) for row in invoices
    )


def test_month_and_year_in_a_where_clause_count_like_a_half_open_range(executor, invoices):
    """Gorevin kabul sorgusu: MONTH = 9 AND YEAR = 2026, yarim acik aralik sayisina esit."""
    expected = sum(1 for row in invoices if row["TARIH"][:7] == "2026-09")
    assert expected > 0, "uretilen veride Eylul 2026 faturasi yok; karsilastirma bos"
    filtered = "SELECT COUNT(*) AS ADET FROM TBLFATUIRS WHERE MONTH(TARIH) = 9 AND YEAR(TARIH) = 2026"
    ranged = (
        "SELECT COUNT(*) AS ADET FROM TBLFATUIRS "
        "WHERE TARIH >= '2026-09-01' AND TARIH < '2026-10-01'"
    )
    assert cell(executor, filtered) == expected
    assert cell(executor, ranged) == expected


def test_month_survives_being_grouped_and_compared(executor, invoices):
    """Sorgu bir aggregation'in icine girdiginde de ayni sayiyi vermeli (gercek soru bicimi)."""
    sql = (
        "SELECT YEAR(TARIH) AS YIL, MONTH(TARIH) AS AY, COUNT(*) AS ADET FROM TBLFATUIRS "
        "GROUP BY YEAR(TARIH), MONTH(TARIH) ORDER BY YIL, AY"
    )
    counts: dict[tuple[int, int], int] = {}
    for row in invoices:
        month, year, _ = parts(row["TARIH"])
        counts[(year, month)] = counts.get((year, month), 0) + 1
    assert run(executor, sql).rows == sorted((year, month, n) for (year, month), n in counts.items())


# ----------------------------------------------------------------- DATEPART


def test_datepart_on_a_literal_gives_the_same_numbers_as_month(executor):
    sql = (
        f"SELECT DATEPART(month, '{LITERAL}') AS AY, DATEPART(year, '{LITERAL}') AS YIL, "
        f"DATEPART(day, '{LITERAL}') AS GUN"
    )
    assert run(executor, sql).rows == [(9, 2026, 5)]


def test_datepart_on_a_date_column_agrees_with_month_year_day(executor, invoices):
    expected = sorted((row["TARIH"], *parts(row["TARIH"])) for row in invoices)
    datepart = run(
        executor,
        "SELECT TARIH, DATEPART(month, TARIH) AS AY, DATEPART(year, TARIH) AS YIL, "
        "DATEPART(day, TARIH) AS GUN FROM TBLFATUIRS",
    )
    assert sorted(datepart.rows) == expected


def test_datepart_groups_the_invoices_by_month(executor, invoices):
    sql = (
        "SELECT DATEPART(year, TARIH) AS YIL, DATEPART(month, TARIH) AS AY, COUNT(*) AS ADET "
        "FROM TBLFATUIRS GROUP BY DATEPART(year, TARIH), DATEPART(month, TARIH) "
        "ORDER BY YIL, AY"
    )
    counts: dict[tuple[int, int], int] = {}
    for row in invoices:
        month, year, _ = parts(row["TARIH"])
        counts[(year, month)] = counts.get((year, month), 0) + 1
    assert run(executor, sql).rows == sorted((year, month, n) for (year, month), n in counts.items())


def test_an_unsupported_datepart_unit_is_refused_instead_of_answering(executor):
    result = executor.execute("SELECT DATEPART(weekday, TARIH) AS G FROM TBLFATUIRS", COMPARE, "ask")
    assert result.error is not None and result.error.kind == "transpile"
    assert result.error.message.strip()
    assert result.rows == []


# ----------------------------------------------------------------- LEFT


def test_left_of_a_literal_keeps_the_first_characters(executor):
    assert cell(executor, "SELECT LEFT('STK0001', 3) AS K") == "STK"


def test_left_of_a_column_keeps_the_first_characters(executor, stocks):
    sql = "SELECT STOK_KODU, LEFT(STOK_KODU, 4) AS ILK FROM TBLSTSABIT"
    assert sorted(run(executor, sql).rows) == sorted(
        (row["STOK_KODU"], row["STOK_KODU"][:4]) for row in stocks
    )


def test_left_groups_the_stock_codes_by_their_prefix(executor, stocks):
    sql = (
        "SELECT LEFT(GRUP_KODU, 3) AS ONEK, COUNT(*) AS ADET FROM TBLSTSABIT "
        "GROUP BY LEFT(GRUP_KODU, 3) ORDER BY ONEK"
    )
    counts: dict[str, int] = {}
    for row in stocks:
        prefix = row["GRUP_KODU"][:3]
        counts[prefix] = counts.get(prefix, 0) + 1
    assert run(executor, sql).rows == sorted(counts.items())


# ----------------------------------------------------------------- policy sozlesmesi


def test_the_policy_still_hands_the_executor_tsql(executor, invoices):
    """Sozlesme: PolicyResult.sql T-SQL'dir ve TOP tasir; SQLite sentaksi yalniz ceviride dogar."""
    sql = "SELECT COUNT(*) AS ADET FROM TBLFATUIRS WHERE MONTH(TARIH) = 9 AND YEAR(TARIH) = 2026"
    verdict = policy.check(sql, doc.allowlist(doc.load_schema()))
    assert verdict.ok
    assert "TOP" in verdict.sql and "MONTH(" in verdict.sql.upper()
    assert "STRFTIME" not in verdict.sql.upper()
    assert cell(executor, sql) == sum(1 for row in invoices if row["TARIH"][:7] == "2026-09")
