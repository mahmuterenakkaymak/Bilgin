"""check() "TOP n enforced" diyorsa hiçbir mevcut sınır tavanı atlatamaz."""

import sqlite3

import pytest
from sqlglot import parse, transpile

from nl2sql import config
from nl2sql.policy import policy


def check(sql, top_n=config.TOP_N):
    return policy.check(sql, {"T"}, top_n)


def run(sql, values):
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("CREATE TABLE T (A INTEGER)")
        conn.executemany("INSERT INTO T (A) VALUES (?)", [(value,) for value in values])
        return conn.execute(transpile(sql, read="tsql", write="sqlite")[0]).fetchall()
    finally:
        conn.close()


# ----------------------------------------------------------------- existing caps


def test_a_top_above_the_cap_is_clamped():
    result = check("SELECT TOP 99999999 A FROM T")
    assert result.ok and "TOP 1000 " in result.sql and "99999999" not in result.sql


def test_a_top_below_the_cap_is_kept():
    result = check("SELECT TOP 5 A FROM T")
    assert result.ok and "TOP 5 " in result.sql and "1000" not in result.sql


def test_a_top_held_in_a_variable_falls_back_to_the_cap():
    result = check("SELECT TOP (@n) A FROM T")
    assert result.ok and "TOP 1000 " in result.sql and "@n" not in result.sql


def test_a_fetch_above_the_cap_is_clamped():
    sql = "SELECT A FROM T ORDER BY A OFFSET 0 ROWS FETCH NEXT 99999999 ROWS ONLY"
    result = check(sql)
    assert result.ok and "FETCH NEXT 1000 ROWS ONLY" in result.sql and "99999999" not in result.sql


def test_a_fetch_below_the_cap_is_kept():
    sql = "SELECT A FROM T ORDER BY A OFFSET 0 ROWS FETCH NEXT 3 ROWS ONLY"
    result = check(sql)
    assert result.ok and "FETCH NEXT 3 ROWS ONLY" in result.sql and "TOP" not in result.sql


def test_a_fetch_held_in_a_variable_falls_back_to_the_cap():
    sql = "SELECT A FROM T ORDER BY A OFFSET @o ROWS FETCH NEXT @n ROWS ONLY"
    result = check(sql)
    assert result.ok and "FETCH NEXT 1000 ROWS ONLY" in result.sql and "@n" not in result.sql


def test_a_percent_cap_keeps_its_meaning():
    result = check("SELECT TOP 50 PERCENT A FROM T")
    assert result.ok and result.sql == "SELECT TOP 50 PERCENT A FROM T"


# ----------------------------------------------------------------- offset alone


def test_offset_without_a_fetch_gets_one():
    result = check("SELECT A FROM T ORDER BY A OFFSET 10 ROWS")
    assert result.ok and result.sql.endswith("OFFSET 10 ROWS FETCH NEXT 1000 ROWS ONLY")


def test_an_offset_held_in_a_variable_is_capped_too():
    """Atlanan satır sayısı bilinmiyor, ama kaç satır döneceği artık belli."""
    result = check("SELECT A FROM T ORDER BY A OFFSET @o ROWS")
    assert result.ok and result.sql.endswith("OFFSET @o ROWS FETCH NEXT 1000 ROWS ONLY")


# ----------------------------------------------------------------- cap in practice


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT TOP 99999999 A FROM T ORDER BY A",
        "SELECT TOP (@n) A FROM T ORDER BY A",
        "SELECT A FROM T ORDER BY A OFFSET 2 ROWS",
        "SELECT A FROM T ORDER BY A OFFSET 0 ROWS FETCH NEXT 99999999 ROWS ONLY",
    ],
)
def test_the_capped_sql_returns_at_most_top_n_rows(sql):
    result = check(sql, 5)
    assert result.ok, result.reason
    assert len(run(result.sql, range(25))) == 5


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT TOP 99999999 A FROM T",
        "SELECT TOP (@n) A FROM T",
        "SELECT A FROM T ORDER BY A OFFSET 10 ROWS",
        "SELECT A FROM T ORDER BY A OFFSET @o ROWS FETCH NEXT @n ROWS ONLY",
    ],
)
def test_the_capped_sql_is_still_one_tsql_statement(sql):
    result = check(sql)
    assert result.ok and len(parse(result.sql, read="tsql")) == 1
    assert len(transpile(result.sql, read="tsql", write="sqlite")) == 1


def test_a_top_inside_a_subquery_does_not_stand_in_for_the_outer_cap():
    result = check("SELECT X.A FROM (SELECT TOP 99999999 A FROM T) AS X", 20)
    assert result.ok and result.sql.startswith("SELECT TOP 20 X.A FROM (")
