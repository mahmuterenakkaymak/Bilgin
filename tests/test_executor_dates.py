# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Tarih islevleri SQLite tarafinda SQL Server'in verdigi sayiyi ve metni vermeli.

Kirilan yer ceviri adimiydi: policy T-SQL'i yeniden uretiyor, sqlglot DATEDIFF argumanlarini
CAST(x AS DATETIME2) ile sarmaliyor, o katman SQLite'a CAST(x AS TIMESTAMP) olarak iniyor ve
TIMESTAMP sayisal yaklinik tasidigi icin '2026-02-01' sayi 2026'ya donusuyordu; JULIANDAY tarih
goremeyince DATEDIFF 31 yerine 0 donuyordu. CONVERT'da tersi oluyordu: SQLite CAST(x AS TEXT(7))
icindeki uzunlugu yok saydigi icin 'YYYY-MM' kesimi hic yapilmiyordu.

Beklenen degerler SQL Server'in tanimindan ve uretilen veriden aliniyor; cevirenin kendi
ciktilariyla karsilastirma yapilmiyor, yoksa kirik davranis dogru dogrulamis olurdu.
"""

import datetime as dt

import pytest

from nl2sql import config
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.policy import policy
from nl2sql.schema_map import build, doc, generator

# Karsilastirma butcesi: burada satir kesmek yok, her faturanin tarihi gorunmeli.
COMPARE = Budget(max_rows=config.COMPARE_MAX_ROWS)

DAY0 = "2026-06-01"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("dates") / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture(scope="module")
def executor(db, tmp_path_factory):
    return LocalExecutor(
        "sqlite", db, audit_path=tmp_path_factory.mktemp("dates-audit") / "audit.jsonl"
    )


@pytest.fixture(scope="module")
def invoices():
    return generator.generate(config.SEED)["TBLFATUIRS"]


def run(executor, sql):
    result = executor.execute(sql, COMPARE, "ask")
    assert result.error is None, f"sorgu calismadi: {result.error}"
    return result


def cell(executor, sql):
    """Tek gozdegeri; kirik ceviri 0 ya da tam tarih dondururse test tam oradan kirilir."""
    result = run(executor, sql)
    assert len(result.rows) == 1, f"tek satir beklenmisti: {result.rows}"
    return result.rows[0][0]


# ----------------------------------------------------------------- DATEDIFF sabitlerle


def test_datediff_day_counts_the_days_between_two_literals(executor):
    assert cell(executor, "SELECT DATEDIFF(day, '2026-01-01', '2026-02-01') AS GUN") == 31


def test_datediff_day_is_signed_like_sql_server(executor):
    assert cell(executor, "SELECT DATEDIFF(day, '2026-02-01', '2026-01-01') AS GUN") == -31


def test_datediff_month_counts_calendar_boundaries_not_thirty_day_blocks(executor):
    assert cell(executor, "SELECT DATEDIFF(month, '2026-01-01', '2026-02-01') AS AY") == 1
    # 31 gunluk Ocak + 28 gunluk Subat: 30'luk blok sayilsa 1 cikardi, sinir sayimi 2 verir.
    assert cell(executor, "SELECT DATEDIFF(month, '2026-01-31', '2026-03-01') AS AY") == 2


def test_datediff_year_counts_calendar_years_not_three_hundred_sixty_five(executor):
    assert cell(executor, "SELECT DATEDIFF(year, '2025-01-01', '2026-02-01') AS YIL") == 1
    # Iki tarih arasinda tek gun var; SQL Server yil sinirini sorar, cevap 1'dir.
    assert cell(executor, "SELECT DATEDIFF(year, '2025-12-31', '2026-01-01') AS YIL") == 1


def test_datediff_accepts_the_three_named_units_in_any_case(executor):
    assert cell(executor, "SELECT DATEDIFF(DAY, '2026-01-01', '2026-01-02') AS GUN") == 1
    assert cell(executor, "SELECT DATEDIFF(Month, '2026-01-01', '2026-03-01') AS AY") == 2
    assert cell(executor, "SELECT DATEDIFF(YEAR, '2026-01-01', '2026-12-31') AS YIL") == 0


# ----------------------------------------------------------------- DATEDIFF kolonla


def month_index(iso: str) -> int:
    date = dt.date.fromisoformat(iso)
    return date.year * 12 + date.month


def test_datediff_on_a_date_column_matches_the_real_calendar(executor, invoices):
    sql = f"SELECT TARIH, DATEDIFF(day, '{DAY0}', TARIH) AS GUN FROM TBLFATUIRS"
    start = dt.date.fromisoformat(DAY0)
    expected = sorted(
        (row["TARIH"], (dt.date.fromisoformat(row["TARIH"]) - start).days) for row in invoices
    )
    assert sorted(run(executor, sql).rows) == expected


def test_datediff_month_on_a_date_column_matches_the_real_calendar(executor, invoices):
    sql = f"SELECT TARIH, DATEDIFF(month, '{DAY0}', TARIH) AS AY FROM TBLFATUIRS"
    expected = sorted(
        (row["TARIH"], month_index(row["TARIH"]) - month_index(DAY0)) for row in invoices
    )
    assert sorted(run(executor, sql).rows) == expected


def test_datediff_survives_being_grouped_and_compared(executor, invoices):
    """Sorgu bir aggregation'in icine girdiginde de ayni sayiyi vermeli (gercek soru bicimi)."""
    sql = (
        f"SELECT DATEDIFF(month, '{DAY0}', TARIH) AS AY, COUNT(*) AS ADET "
        f"FROM TBLFATUIRS GROUP BY DATEDIFF(month, '{DAY0}', TARIH) ORDER BY AY"
    )
    counts: dict[int, int] = {}
    for row in invoices:
        key = month_index(row["TARIH"]) - month_index(DAY0)
        counts[key] = counts.get(key, 0) + 1
    assert run(executor, sql).rows == sorted(counts.items())


# ----------------------------------------------------------------- CONVERT(varchar(n), date, 120)


def test_convert_varchar7_yields_year_month(executor, invoices):
    sql = "SELECT TARIH, CONVERT(varchar(7), TARIH, 120) AS AYDAN FROM TBLFATUIRS"
    assert sorted(run(executor, sql).rows) == sorted(
        (row["TARIH"], row["TARIH"][:7]) for row in invoices
    )


def test_convert_varchar10_yields_the_full_date(executor, invoices):
    sql = "SELECT TARIH, CONVERT(varchar(10), TARIH, 120) AS GUN FROM TBLFATUIRS"
    assert sorted(run(executor, sql).rows) == sorted(
        (row["TARIH"], row["TARIH"]) for row in invoices
    )


def test_convert_year_month_groups_the_invoices_by_month(executor, invoices):
    sql = (
        "SELECT CONVERT(varchar(7), TARIH, 120) AS AYDAN, COUNT(*) AS ADET "
        "FROM TBLFATUIRS GROUP BY CONVERT(varchar(7), TARIH, 120) ORDER BY AYDAN"
    )
    counts: dict[str, int] = {}
    for row in invoices:
        counts[row["TARIH"][:7]] = counts.get(row["TARIH"][:7], 0) + 1
    assert run(executor, sql).rows == sorted(counts.items())


def test_convert_without_style_120_still_runs(executor):
    assert cell(executor, "SELECT CONVERT(varchar(8), 20260101) AS S") == "20260101"


# ----------------------------------------------------------------- kirik birim sessiz kalmasın


def test_an_unsupported_datediff_unit_is_refused_instead_of_answering(executor):
    result = executor.execute(
        "SELECT DATEDIFF(hour, '2026-01-01', '2026-01-02') AS SAAT", COMPARE, "ask"
    )
    assert result.error is not None and result.error.kind == "transpile"
    assert result.error.message.strip()
    assert result.rows == []


# ----------------------------------------------------------------- policy sozlesmesi


def test_the_policy_still_hands_the_executor_tsql_with_top(executor):
    """Sozlesme: PolicyResult.sql T-SQL'dir ve TOP tasir; SQLite sentaksi yalniz ceviride dogar."""
    sql = "SELECT DATEDIFF(day, '2026-01-01', '2026-02-01') AS GUN"
    verdict = policy.check(sql, doc.allowlist(doc.load_schema()))
    assert verdict.ok
    assert "TOP" in verdict.sql and "DATEDIFF" in verdict.sql.upper()
    assert "JULIANDAY" not in verdict.sql.upper()
    assert cell(executor, sql) == 31
