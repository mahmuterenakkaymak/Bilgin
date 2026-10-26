"""Private MSSQL backend.

Same contract as `_sqlite`: the SQL reaching this module has already passed the policy, and
the module is private (leading underscore) so that no caller can use it as a way around that
check. Two things are enforced here instead. The connection string exists only in the
NL2SQL_MSSQL_CONN environment variable - never in code, config or a committed file - and
ApplicationIntent=ReadOnly is forced onto it, so SQL Server itself opens the session read
only and refuses writes even if a query somehow gets through.
"""

from __future__ import annotations

import math
import os
import time

from nl2sql.engine._sqlite import COUNT_CHUNK
from nl2sql.engine.result import Budget, ExecError, Result

CONN_ENV = "NL2SQL_MSSQL_CONN"
MISSING_CONN = (
    "MSSQL bağlantı dizesi tanımlı değil; NL2SQL_MSSQL_CONN ortam değişkenine salt okunur "
    "bağlantı dizesini yazın (ApplicationIntent=ReadOnly kendiliğinden eklenir)."
)
NO_MODULE = "pyodbc kurulu değil; MSSQL yedeği için `uv sync` çalıştırın."
TIMEOUT_MESSAGE = "Sorgu zaman sınırını aştı; daha dar bir sorgu yazın."


def run(sql: str, budget: Budget, conn_str: str | None = None) -> Result:
    """Run one already-approved T-SQL SELECT under the row and time budgets."""
    started = time.perf_counter()
    dsn = (conn_str or os.environ.get(CONN_ENV, "")).strip()
    if not dsn:
        return _failure(started, MISSING_CONN)
    try:
        import pyodbc
    except ImportError:
        return _failure(started, NO_MODULE)
    conn = None
    try:
        conn = pyodbc.connect(_read_only(dsn))
        conn.timeout = max(1, math.ceil(budget.timeout_s))  # pyodbc wants whole seconds (first real run, 2026-10-25)
        cursor = conn.cursor()
        cursor.execute(f"SET LOCK_TIMEOUT {int(budget.timeout_s * 1000)}")
        cursor.execute(sql)
        columns = [column[0] for column in cursor.description] if cursor.description else []
        rows = [tuple(row) for row in cursor.fetchmany(budget.max_rows + 1)]
        truncated = len(rows) > budget.max_rows
        row_count = len(rows)
        if truncated:
            rows = rows[: budget.max_rows]
            row_count += _count_rest(cursor)
        return Result(
            columns=columns,
            rows=rows,
            row_count=row_count,
            truncated=truncated,
            elapsed_ms=_elapsed(started),
        )
    except pyodbc.Error as exc:
        # The driver quotes the connection string back, and this message reaches the screen, the
        # step list and the stored turn - so the secret goes here, where it is born.
        from nl2sql.engine.connections import scrub  # connections imports this module: lazy here

        text = scrub(" ".join(str(exc).split()))
        if "timeout" in text.lower():
            return _failure(started, TIMEOUT_MESSAGE, kind="timeout")
        return _failure(started, f"SQL Server: {text}" if text else "SQL Server sorguyu çalıştıramadı.")
    finally:
        if conn is not None:
            conn.close()


def _read_only(dsn: str) -> str:
    """ApplicationIntent her durumda ReadOnly olur; verilen dizedeki aynı anahtarın yerini alır."""
    parts = [part for part in dsn.rstrip(";").split(";") if part.strip()]
    kept = [part for part in parts if part.split("=", 1)[0].strip().lower() != "applicationintent"]
    kept.append("ApplicationIntent=ReadOnly")
    return ";".join(kept) + ";"


def _count_rest(cursor) -> int:
    total = 0
    while chunk := cursor.fetchmany(COUNT_CHUNK):
        total += len(chunk)
    return total


def _failure(started: float, message: str, kind: str = "sql") -> Result:
    return Result(elapsed_ms=_elapsed(started), error=ExecError(kind, message))


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
