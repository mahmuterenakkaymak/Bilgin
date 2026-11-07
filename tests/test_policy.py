# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

import json
import sqlite3

import pytest
from sqlglot import exp, parse, transpile

from bilgin import config
from bilgin.policy import policy
from bilgin.schema_map import build, doc

ALLOWED = doc.allowlist(doc.load_schema())
GOLDEN = [json.loads(line) for line in config.GOLDEN_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
BY_ID = {line["id"]: line for line in GOLDEN}
IDS = [line["id"] for line in GOLDEN]


def check(sql, top_n=config.TOP_N):
    return policy.check(sql, ALLOWED, top_n)


def real_tables(sql):
    return {table.name.upper() for table in parse(sql, read="tsql")[0].find_all(exp.Table)}


def run(db, sql):
    conn = sqlite3.connect(db)
    try:
        return conn.execute(transpile(sql, read="tsql", write="sqlite")[0]).fetchall()
    finally:
        conn.close()


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("policy") / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


# ----------------------------------------------------------------- golden set passes


@pytest.mark.parametrize("qid", IDS)
def test_every_golden_sql_passes_the_policy(qid):
    result = check(BY_ID[qid]["sql"])
    assert result.ok, f"{qid}: {result.reason}"
    assert result.reason is None and result.sql
    assert len(parse(result.sql, read="tsql")) == 1


@pytest.mark.parametrize("qid", IDS)
def test_policy_reports_the_real_tables_it_saw(qid):
    result = check(BY_ID[qid]["sql"])
    assert result.tables == real_tables(BY_ID[qid]["sql"])
    assert result.tables <= ALLOWED


@pytest.mark.parametrize("qid", IDS)
def test_rewritten_sql_returns_the_same_rows(qid, db):
    """Policy SQL'i yeniden yazdığı için (TOP) sonucu bozmamalı."""
    original = sorted(map(repr, run(db, BY_ID[qid]["sql"])))
    rewritten = sorted(map(repr, run(db, check(BY_ID[qid]["sql"]).sql)))
    assert rewritten == original, qid


# ----------------------------------------------------------------- what is allowed


def test_plain_select_without_a_table_is_allowed():
    result = check("SELECT 1 AS CEVAP")
    assert result.ok and result.tables == set()


def test_cte_is_allowed_and_is_not_counted_as_a_table():
    result = check("WITH a AS (SELECT STOK_KODU FROM TBLSTHAR) SELECT * FROM a")
    assert result.ok, result.reason
    assert result.tables == {"TBLSTHAR"}


def test_nested_subqueries_are_all_checked_and_allowed():
    sql = (
        "SELECT s.STOK_KODU FROM TBLSTHAR s WHERE s.FISNO IN "
        "(SELECT f.FATIRS_NO FROM TBLFATUIRS f WHERE f.GENELTOPLAM > 0)"
    )
    result = check(sql)
    assert result.ok, result.reason
    assert result.tables == {"TBLSTHAR", "TBLFATUIRS"}


def test_bracket_quoting_case_and_table_hints_are_only_spelling():
    result = check("select top 3 [stok_kodu] from [TBLSTHAR] with (nolock) order by [stok_kodu]")
    assert result.ok, result.reason
    assert result.tables == {"TBLSTHAR"}


def test_scalar_functions_are_not_table_valued():
    result = check("SELECT COUNT(*) AS ADET, MAX(STHAR_GCMIK) AS EN_BUYUK FROM TBLSTHAR")
    assert result.ok, result.reason


# ----------------------------------------------------------------- one statement, read only

REJECTED = [
    ("SELECT 1; SELECT 2", "Tek seferde"),
    ("SELECT * FROM TBLSTHAR; DROP TABLE TBLCASABIT", "Tek seferde"),
    ("SELECT * FROM TBLSTHAR; -- yorum sonrası ikinci cümle\nSELECT 2", "Tek seferde"),
    ("UPDATE TBLSTHAR SET STOK_KODU = 'A'", "Yalnızca SELECT"),
    ("DELETE FROM TBLCASABIT", "Yalnızca SELECT"),
    ("INSERT INTO TBLCASABIT (CARI_KOD) VALUES ('X')", "Yalnızca SELECT"),
    ("DROP TABLE TBLCASABIT", "Yalnızca SELECT"),
    ("CREATE TABLE TBLX (A INT)", "Yalnızca SELECT"),
    ("EXEC some_proc", "Yalnızca SELECT"),
    ("WITH x AS (DELETE FROM TBLSTHAR OUTPUT deleted.*) SELECT * FROM x", "Veri değiştiren"),
    ("SELECT * INTO Tmp FROM TBLSTHAR", "SELECT INTO"),
    ("SELECT * INTO #t FROM TBLSTHAR", "SELECT INTO"),
    ("SELECT * FROM TBLSTHAR EXCEPT SELECT * FROM TBLSTHAR", "Yalnızca SELECT"),
    ("SELECT * FROM TBLSTHAR INTERSECT SELECT * FROM TBLCASABIT", "Yalnızca SELECT"),
    ("SELECT x.A FROM (SELECT STOK_KODU AS A FROM TBLSTHAR EXCEPT SELECT CARI_KOD FROM TBLCASABIT) x",
     "UNION dışında"),
]


@pytest.mark.parametrize("sql,expected", REJECTED)
def test_rejected_with_a_reason(sql, expected):
    result = check(sql)
    assert not result.ok and result.sql is None
    assert expected in result.reason, f"{sql!r} -> {result.reason!r}"


# ----------------------------------------------------------------- system objects


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM sys.objects",
        "SELECT * FROM INFORMATION_SCHEMA.TABLES",
        "SELECT STOK_KODU FROM TBLSTHAR UNION SELECT name FROM sys.columns",
        "SELECT * FROM TBLSTHAR s WHERE EXISTS (SELECT 1 FROM sys.databases d)",
        "SELECT * FROM sys.TBLSTHAR",
        "WITH TBLSTHAR AS (SELECT object_id AS STOK_KODU FROM sys.objects) SELECT * FROM TBLSTHAR",
    ],
)
def test_system_catalog_is_never_readable(sql):
    result = check(sql)
    assert not result.ok and "Sistem kataloğu" in result.reason


def test_a_cte_name_cannot_hide_a_forbidden_table():
    """Tuzak: CTE gerçek bir tablonun adını üstlense de gövdesindeki sys.objects yakalanır."""
    result = check(
        "WITH TBLSTGRUP AS (SELECT 1 AS A) SELECT * FROM TBLSTGRUP JOIN sys.objects o ON 1=1"
    )
    assert not result.ok and "Sistem kataloğu" in result.reason


@pytest.mark.parametrize("sql", ["SELECT * FROM xp_cmdshell", "SELECT dbo.sp_who()", "SELECT * FROM TBLSTHAR WHERE STOK_KODU = xp_lookup(1)"])
def test_system_procedures_are_rejected(sql):
    result = check(sql)
    assert not result.ok and "Sistem yordamları" in result.reason


# ----------------------------------------------------------------- rowset / table functions


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM OPENROWSET('SQLNCLI','server=x;uid=y;pwd=z;','SELECT 1') AS r",
        "SELECT * FROM OPENQUERY(SRV,'SELECT 1') AS q",
        "SELECT * FROM OPENDATASOURCE('SQLNCLI','data source=x')..dbo.TBLSTHAR",
        "SELECT * FROM OPENJSON('[]')",
        "SELECT * FROM dbo.fn_split('a',',')",
        "SELECT * FROM TBLSTHAR WHERE STOK_KODU IN (SELECT value FROM OPENJSON('[]'))",
    ],
)
def test_rowset_and_table_valued_functions_are_rejected(sql):
    result = check(sql)
    assert not result.ok and "Tablo işlevi" in result.reason


def test_cross_apply_of_a_table_function_is_rejected():
    result = check("SELECT * FROM TBLSTHAR s CROSS APPLY fn_lines(s.FISNO) x")
    assert not result.ok and "APPLY ile" in result.reason


# ----------------------------------------------------------------- allowlist and naming


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM TBLGECKMIS",
        "SELECT * FROM TBLSTHAR s JOIN TBLGECKMIS g ON g.STOK_KODU = s.STOK_KODU",
        "WITH x AS (SELECT 1 AS A) SELECT * FROM x JOIN TBLGECKMIS g ON 1=1",
        "SELECT * FROM #gizli",
        "SELECT * FROM TBLSTHAR WHERE FISNO IN (SELECT FATIRS_NO FROM TBLGECKMIS)",
    ],
)
def test_default_deny_on_tables_outside_the_allowlist(sql):
    result = check(sql)
    assert not result.ok and "İzin verilmeyen tablo" in result.reason


def test_allowlist_is_the_only_source_of_permission():
    result = policy.check("SELECT * FROM TBLSTHAR", set(), 10)
    assert not result.ok and "İzin verilmeyen tablo" in result.reason


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM AutoAI_DB.dbo.TBLSTHAR",
        "SELECT * FROM [dbo].[TBLSTHAR]",
        "SELECT * FROM SERVER.AutoAI_DB.dbo.TBLSTHAR",
        "SELECT * FROM TBLSTHAR s JOIN master.dbo.TBLCASABIT c ON 1=1",
    ],
)
def test_qualified_names_are_rejected(sql):
    result = check(sql)
    assert not result.ok and "veritabanı" in result.reason


# ----------------------------------------------------------------- row cap (TOP)


def test_top_is_injected_on_the_outermost_select():
    result = check("SELECT STOK_KODU FROM TBLSTHAR s WHERE EXISTS (SELECT 1 FROM TBLFATUIRS)", 250)
    assert result.ok and result.sql.startswith("SELECT TOP 250 ")


def test_top_goes_after_the_cte_not_inside_it():
    result = check("WITH x AS (SELECT STOK_KODU FROM TBLSTHAR) SELECT * FROM x", 100)
    assert result.ok and result.sql.startswith("WITH x AS (") and "SELECT TOP 100 * FROM x" in result.sql


def test_an_existing_top_is_kept():
    result = check(BY_ID["Q02"]["sql"])
    assert result.ok and "TOP 5" in result.sql and "TOP 1000" not in result.sql


def test_offset_fetch_counts_as_an_existing_row_cap():
    sql = "SELECT STOK_KODU FROM TBLSTHAR ORDER BY STOK_KODU OFFSET 0 ROWS FETCH NEXT 3 ROWS ONLY"
    result = check(sql)
    assert result.ok and "TOP" not in result.sql


def test_a_top_level_union_is_wrapped():
    sql = "SELECT STOK_KODU AS KOD FROM TBLSTHAR UNION SELECT CARI_KOD FROM TBLCASABIT"
    result = check(sql, 100)
    assert result.ok
    assert result.sql.startswith("SELECT TOP 100 * FROM (") and result.sql.endswith(") AS _q")


def test_order_by_of_a_union_moves_out_of_the_wrapper():
    """T-SQL türetilmiş tabloda ORDER BY'yı TOP olmadan reddeder; sıralama dışarıda kalır."""
    sql = "SELECT STOK_KODU AS KOD FROM TBLSTHAR UNION SELECT CARI_KOD FROM TBLCASABIT ORDER BY KOD"
    result = check(sql, 100)
    assert result.ok and result.sql.endswith(") AS _q ORDER BY KOD")
    assert ") AS _q ORDER BY" in result.sql and "ORDER BY" not in result.sql.split("AS _q")[0]


def test_rewritten_sql_still_transpiles_to_one_sqlite_statement():
    result = check("SELECT STOK_KODU FROM TBLSTHAR UNION SELECT CARI_KOD FROM TBLCASABIT ORDER BY 1")
    assert result.ok and len(transpile(result.sql, read="tsql", write="sqlite")) == 1


# ----------------------------------------------------------------- result shape


def test_unparsable_and_empty_input_are_rejected_not_raised():
    for sql in ["", "   ", ";", "SELECT * FROM ((((", "SELCT 1"]:
        result = check(sql)
        assert not result.ok and result.reason.strip() and result.sql is None


def test_rejection_carries_no_sql_and_approval_carries_no_reason():
    ok = check("SELECT 1 AS A")
    assert ok.ok and ok.reason is None and ok.sql
    bad = check("DROP TABLE TBLSTHAR")
    assert not bad.ok and bad.sql is None and bad.reason.strip()


def test_tables_defaults_to_an_empty_set():
    assert policy.PolicyResult(ok=False, reason="x").tables == set()
