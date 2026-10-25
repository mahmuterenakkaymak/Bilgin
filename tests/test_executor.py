"""Executor: policy içeri girer, çeviri sonra, backend en son; her deneme kuyruğa yazılır.

Asıl güvenceler burada sınanır: public bir yöntem policy'yi atlayamaz, red Result.error
içinde "policy" olarak döner ve denetim satırı satır verisi taşımaz. MSSQL tarafı sahte
pyodbc ile çalıştırılır; gerçek sunucu bu testlerin konusu değildir.
"""

import importlib
import json
import pkgutil
import sqlite3
import sys
import types

import pytest
from sqlglot.errors import SqlglotError

from nl2sql import config
from nl2sql.engine import executor as executor_module
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget

ROWS = 5
ALLOWED = {"STOK_KART"}
SELECT = "SELECT LRREF, MALZEME FROM STOK_KART ORDER BY LRREF"
ENTRY_FIELDS = {"ts", "source", "sql", "elapsed_ms", "row_count", "outcome"}


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "test.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE STOK_KART (LRREF INTEGER NOT NULL, MALZEME TEXT NOT NULL)")
    conn.executemany(
        "INSERT INTO STOK_KART (LRREF, MALZEME) VALUES (?, ?)",
        [(i, f"ürün {i}") for i in range(1, ROWS + 1)],
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def audit_path(tmp_path):
    return tmp_path / "logs" / "audit.jsonl"


def make(db, audit_path, backend="sqlite", allowlist=ALLOWED):
    return LocalExecutor(backend, db, allowlist, audit_path)


def entries(audit_path):
    text = audit_path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def malzeme(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT MALZEME FROM STOK_KART ORDER BY LRREF").fetchall()
    finally:
        conn.close()


# ----------------------------------------------------------------- no way around the policy


def test_execute_is_the_only_public_method():
    public = {
        name
        for name, value in vars(LocalExecutor).items()
        if not name.startswith("_") and callable(value)
    }
    assert public == {"execute"}


def test_no_public_engine_module_can_run_sql():
    import nl2sql.engine

    for info in pkgutil.iter_modules(nl2sql.engine.__path__):
        module = importlib.import_module(f"nl2sql.engine.{info.name}")
        if hasattr(module, "run"):
            assert info.name.startswith("_"), f"{info.name} policy'siz çalıştırılabiliyor"


def test_query_never_reaches_the_database_when_the_policy_refuses_it(db, audit_path):
    result = make(db, audit_path).execute(
        "SELECT LRREF FROM STOK_KART; DELETE FROM STOK_KART", source="ask"
    )
    assert result.error.kind == "policy"
    assert result.rows == [] and result.row_count == 0
    assert malzeme(db) == [(f"ürün {i}",) for i in range(1, ROWS + 1)], "tablo yerinde durmalı"


def test_allowlist_belongs_to_the_executor_not_to_the_database(db, audit_path):
    result = make(db, audit_path, allowlist={"FATURA"}).execute(SELECT)
    assert result.error.kind == "policy"
    assert "STOK_KART" in result.error.message


# ----------------------------------------------------------------- approved reads


def test_select_runs_through_policy_transpile_and_backend(db, audit_path):
    result = make(db, audit_path).execute(SELECT, source="Q01")
    assert result.error is None
    assert result.columns == ["LRREF", "MALZEME"]
    assert result.rows == [(i, f"ürün {i}") for i in range(1, ROWS + 1)]
    assert result.row_count == ROWS
    assert result.truncated is False
    assert result.elapsed_ms > 0


def test_tsql_top_survives_the_transpile(db, audit_path):
    result = make(db, audit_path).execute("SELECT TOP 2 LRREF FROM STOK_KART ORDER BY LRREF")
    assert result.error is None
    assert result.rows == [(1,), (2,)]


def test_row_budget_truncates_but_keeps_the_count(db, audit_path):
    result = make(db, audit_path).execute(SELECT, Budget(max_rows=2))
    assert result.rows == [(1, "ürün 1"), (2, "ürün 2")]
    assert result.truncated is True
    assert result.row_count == ROWS


def test_database_error_comes_back_as_a_result_not_an_exception(db, audit_path):
    result = make(db, audit_path).execute("SELECT OLMAYAN FROM STOK_KART")
    assert result.error.kind == "sql"
    assert result.error.message.strip()


# ----------------------------------------------------------------- transpile


def test_transpile_failure_is_reported_as_transpile(db, audit_path, monkeypatch):
    def boom(*args, **kwargs):
        raise SqlglotError("no support for that")

    monkeypatch.setattr(executor_module, "transpile", boom)
    result = make(db, audit_path).execute(SELECT)
    assert result.error.kind == "transpile"
    assert result.error.message.strip()
    assert entries(audit_path)[0]["outcome"] == "transpile"


def test_transpile_must_yield_exactly_one_statement(db, audit_path, monkeypatch):
    monkeypatch.setattr(executor_module, "transpile", lambda *a, **k: [])
    assert make(db, audit_path).execute(SELECT).error.kind == "transpile"


# ----------------------------------------------------------------- mssql backend


class FakePyodbcError(Exception):
    pass


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self.description = None
        self._rows = []

    def execute(self, sql):
        self.conn.statements.append(sql)
        if self.conn.fail:
            raise self.conn.fail
        if sql.upper().startswith("SET "):
            return self
        self.description = [("LRREF",), ("MALZEME",)]
        self._rows = [(i, f"ürün {i}") for i in range(1, ROWS + 1)]
        return self

    def fetchmany(self, size):
        rows, self._rows = self._rows[:size], self._rows[size:]
        return rows


class FakeConnection:
    def __init__(self, fail=None):
        self.timeout = None
        self.statements = []
        self.closed = False
        self.fail = fail

    def cursor(self):
        return FakeCursor(self)

    def close(self):
        self.closed = True


class FakePyodbc(types.ModuleType):
    Error = FakePyodbcError

    def __init__(self, fail=None):
        super().__init__("pyodbc")
        self.fail = fail
        self.connections = []

    def connect(self, dsn):
        conn = FakeConnection(self.fail)
        conn.dsn = dsn
        self.connections.append(conn)
        return conn


def install_pyodbc(monkeypatch, fail=None):
    fake = FakePyodbc(fail)
    monkeypatch.setitem(sys.modules, "pyodbc", fake)
    monkeypatch.setenv("NL2SQL_MSSQL_CONN", "Server=.;Database=ERP;ApplicationIntent=ReadWrite;")
    return fake


def test_mssql_session_is_read_only_and_limited(db, audit_path, monkeypatch):
    fake = install_pyodbc(monkeypatch)
    result = make(db, audit_path, backend="mssql").execute(SELECT, Budget(max_rows=2), "Q01")
    assert result.error is None
    conn = fake.connections[0]
    assert conn.dsn.count("ApplicationIntent") == 1
    assert "ApplicationIntent=ReadOnly" in conn.dsn
    assert conn.timeout == config.QUERY_TIMEOUT_S
    assert conn.statements[0].upper().startswith("SET LOCK_TIMEOUT")
    assert conn.closed
    assert result.rows == [(1, "ürün 1"), (2, "ürün 2")]
    assert result.row_count == ROWS and result.truncated is True


def test_mssql_without_a_connection_string_names_the_env_var(db, audit_path, monkeypatch):
    monkeypatch.delenv("NL2SQL_MSSQL_CONN", raising=False)
    result = make(db, audit_path, backend="mssql").execute(SELECT)
    assert result.error.kind == "sql"
    assert "NL2SQL_MSSQL_CONN" in result.error.message


def test_backend_comes_from_the_environment_by_default(db, audit_path, monkeypatch):
    monkeypatch.setenv("NL2SQL_BACKEND", "mssql")
    monkeypatch.delenv("NL2SQL_MSSQL_CONN", raising=False)
    result = LocalExecutor(db_path=db, allowlist=ALLOWED, audit_path=audit_path).execute(SELECT)
    assert "NL2SQL_MSSQL_CONN" in result.error.message


def test_unknown_backend_is_refused_at_construction(db, audit_path):
    with pytest.raises(ValueError):
        make(db, audit_path, backend="oracle")


def test_mssql_server_error_is_a_sql_error_and_closes_the_connection(db, audit_path, monkeypatch):
    fake = install_pyodbc(monkeypatch, FakePyodbcError("42S02: Invalid object name 'FATURA'."))
    result = make(db, audit_path, backend="mssql").execute(SELECT)
    assert result.error.kind == "sql"
    assert "Invalid object name" in result.error.message
    assert fake.connections[0].closed


def test_mssql_timeout_is_reported_as_a_timeout(db, audit_path, monkeypatch):
    install_pyodbc(monkeypatch, FakePyodbcError("HYT00: Query timeout expired"))
    assert make(db, audit_path, backend="mssql").execute(SELECT).error.kind == "timeout"


# ----------------------------------------------------------------- audit


def test_every_attempt_is_audited_in_order(db, audit_path):
    ex = make(db, audit_path)
    ex.execute(SELECT, source="Q01")
    ex.execute("SELECT name FROM sys.objects", source="ask")
    logged = entries(audit_path)
    assert [entry["outcome"] for entry in logged] == ["ok", "policy"]
    assert [entry["source"] for entry in logged] == ["Q01", "ask"]
    assert [entry["row_count"] for entry in logged] == [ROWS, 0]
    assert logged[0]["sql"] == SELECT and logged[0]["elapsed_ms"] > 0
    assert all(set(entry) == ENTRY_FIELDS for entry in logged), "girdi sözleşmenin alanlarını taşır"
    assert all(entry["ts"] for entry in logged)


def test_audit_line_carries_no_row_data(db, audit_path):
    make(db, audit_path).execute(SELECT, source="Q01")
    text = audit_path.read_text(encoding="utf-8")
    assert "ürün" not in text
    assert "rows" not in text


def test_rejected_query_is_audited_with_the_text_that_was_asked(db, audit_path):
    sql = "EXEC xp_cmdshell 'dir'"
    make(db, audit_path).execute(sql, source="Q04")
    entry = entries(audit_path)[0]
    assert entry["outcome"] == "policy"
    assert entry["sql"] == sql, "denetimde çevrilmiş değil istenen SQL yazar"
    assert entry["source"] == "Q04"
