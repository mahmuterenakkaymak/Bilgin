# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

import sqlite3

import pytest

from bilgin import config
from bilgin.engine import _sqlite
from bilgin.engine.result import Budget, Result

ROWS = 5
SLOW_SQL = (
    "WITH RECURSIVE s(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM s WHERE x < 5000000)"
    " SELECT COUNT(*) FROM s"
)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE TBLSTSABIT (LRREF INTEGER NOT NULL, MALZEME TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO TBLSTSABIT (LRREF, MALZEME) VALUES (?, ?)",
        [(i, f"ürün {i}") for i in range(1, ROWS + 1)],
    )
    conn.commit()
    conn.close()
    return path


def run(sql, db, max_rows=50, timeout_s=config.QUERY_TIMEOUT_S):
    return _sqlite.run(sql, Budget(max_rows=max_rows, timeout_s=timeout_s), db)


def malzeme(path, lrref):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT MALZEME FROM TBLSTSABIT WHERE LRREF = ?", (lrref,)).fetchone()[0]
    finally:
        conn.close()


# ----------------------------------------------------------------- contracts


def test_budget_and_result_start_from_the_planned_defaults():
    budget = Budget()
    assert budget.max_rows == config.MODEL_MAX_ROWS
    assert budget.timeout_s == config.QUERY_TIMEOUT_S
    empty = Result()
    assert (empty.columns, empty.rows, empty.row_count, empty.truncated, empty.error) == (
        [],
        [],
        0,
        False,
        None,
    )


# ----------------------------------------------------------------- successful reads


def test_select_returns_columns_rows_and_count(db):
    result = run("SELECT LRREF, MALZEME FROM TBLSTSABIT ORDER BY LRREF", db)
    assert result.error is None
    assert result.columns == ["LRREF", "MALZEME"]
    assert result.rows == [(i, f"ürün {i}") for i in range(1, ROWS + 1)]
    assert result.row_count == ROWS
    assert result.truncated is False
    assert result.elapsed_ms > 0


def test_empty_result_keeps_its_columns(db):
    result = run("SELECT LRREF, MALZEME FROM TBLSTSABIT WHERE LRREF > 100", db)
    assert result.error is None
    assert result.columns == ["LRREF", "MALZEME"]
    assert result.rows == []
    assert result.row_count == 0
    assert result.truncated is False


# ----------------------------------------------------------------- row budget


def test_budget_truncates_rows_but_keeps_the_full_count(db):
    result = run("SELECT LRREF FROM TBLSTSABIT ORDER BY LRREF", db, max_rows=2)
    assert result.error is None
    assert result.rows == [(1,), (2,)]
    assert result.truncated is True
    assert result.row_count == ROWS, "row_count kesim öncesi toplam olmalı"


def test_budget_exactly_the_size_of_the_result_is_not_truncated(db):
    result = run("SELECT LRREF FROM TBLSTSABIT ORDER BY LRREF", db, max_rows=ROWS)
    assert result.rows == [(i,) for i in range(1, ROWS + 1)]
    assert result.truncated is False
    assert result.row_count == ROWS


# ----------------------------------------------------------------- read-only


def test_update_through_the_read_only_connection_fails(db):
    result = run("UPDATE TBLSTSABIT SET MALZEME = 'silindi' WHERE LRREF = 1", db)
    assert result.error.kind == "sql"
    assert "readonly" in result.error.message.lower()
    assert result.rows == [] and result.row_count == 0
    assert malzeme(db, 1) == "ürün 1", "bağlantı yazmayı geçirmemeli"


def test_delete_through_the_read_only_connection_fails(db):
    assert run("DELETE FROM TBLSTSABIT", db).error.kind == "sql"
    assert run("SELECT COUNT(*) FROM TBLSTSABIT", db).rows == [(ROWS,)]


def test_read_only_connection_does_not_create_a_missing_file(tmp_path):
    missing = tmp_path / "yok.db"
    result = run("SELECT 1", missing)
    assert result.error.kind == "sql"
    assert not missing.exists(), "mode=ro eksik dosyayı oluşturmamalı"


# ----------------------------------------------------------------- failures


def test_bad_sql_becomes_a_sql_error_not_an_exception(db):
    result = run("SELECT OLMAYAN_KOLON FROM TBLSTSABIT", db)
    assert result.error.kind == "sql"
    assert result.error.message.strip()


def test_slow_query_is_stopped_as_a_timeout(db):
    result = run(SLOW_SQL, db, timeout_s=0.05)
    assert result.error.kind == "timeout"
    assert result.error.message.strip()
    assert result.rows == [] and result.row_count == 0
