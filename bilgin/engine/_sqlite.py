# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Private SQLite backend.

By the time control reaches this module the policy has already approved the query and the
executor has transpiled it to SQLite; the module is private (leading underscore) precisely so
that nothing outside the executor can run SQL without that check. What is enforced here are
the two budgets - rows and seconds - and the read-only connection, so even a query that
somehow slipped past the policy could not write. Every failure comes back as an ExecError;
nothing escapes as an exception.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from bilgin import config
from bilgin.engine.result import Budget, ExecError, Result

TIMEOUT_MESSAGE = "Sorgu zaman sınırını aştı; daha dar bir sorgu yazın."

# Rows past max_rows are only counted, never kept, and read in chunks this size so a huge
# result costs memory for one chunk at a time.
COUNT_CHUNK = 1000

# The progress handler runs every this many VM instructions: often enough to cut a runaway
# query within milliseconds of its deadline, rarely enough to leave normal queries alone.
PROGRESS_TICK = 1000


def run(sql: str, budget: Budget, db_path: str | Path = config.DB_PATH) -> Result:
    """Run one already-transpiled SQLite SELECT under the row and time budgets."""
    started = time.perf_counter()
    deadline = _Deadline(budget.timeout_s)
    conn = None
    try:
        conn = _read_only(db_path)
        conn.set_progress_handler(deadline.tick, PROGRESS_TICK)
        cursor = conn.execute(sql)
        columns = [column[0] for column in cursor.description] if cursor.description else []
        rows = cursor.fetchmany(budget.max_rows + 1)
        truncated = len(rows) > budget.max_rows
        row_count = len(rows)
        if truncated:
            rows = rows[: budget.max_rows]
            # ASSUMPTION: row_count is the true total, not max_rows + 1 - the CLI notice shows
            # "toplam 312", so the remaining rows are counted even though they are not kept.
            row_count += _count_rest(cursor)
        return Result(
            columns=columns,
            rows=rows,
            row_count=row_count,
            truncated=truncated,
            elapsed_ms=_elapsed(started),
        )
    except sqlite3.Error as exc:
        kind = "timeout" if deadline.expired else "sql"
        message = TIMEOUT_MESSAGE if deadline.expired else _explain(exc)
        return Result(elapsed_ms=_elapsed(started), error=ExecError(kind, message))
    finally:
        if conn is not None:
            conn.close()


class _Deadline:
    """Progress-handler callback: returns non-zero, i.e. aborts the query, past the limit."""

    def __init__(self, timeout_s: float) -> None:
        self._limit = time.monotonic() + timeout_s
        self.expired = False

    def tick(self) -> bool:
        if time.monotonic() < self._limit:
            return False
        self.expired = True
        return True


def _read_only(db_path: str | Path) -> sqlite3.Connection:
    uri = Path(db_path).resolve().as_uri()
    return sqlite3.connect(f"{uri}?mode=ro", uri=True)


def _count_rest(cursor) -> int:
    total = 0
    while chunk := cursor.fetchmany(COUNT_CHUNK):
        total += len(chunk)
    return total


def _explain(exc: sqlite3.Error) -> str:
    text = " ".join(str(exc).split())
    return f"SQLite: {text}" if text else "SQLite sorguyu çalıştıramadı."


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 1)
