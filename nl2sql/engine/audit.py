"""Audit trail: one JSON line per query the executor ran or refused.

The entry is built field by field from the Result, never from the Result itself, so rows
cannot slip into the log even by accident: the log is read by a human afterwards and it
travels with the run report, while the data behind those rows belongs to the database.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from nl2sql import config
from nl2sql.engine.result import Result


def record(sql: str, source: str, result: Result, path: str | Path = config.AUDIT_LOG) -> None:
    """Appends {"ts","source","sql","elapsed_ms","row_count","outcome"} as one line, plus "masked"."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        "source": source,
        "sql": sql,
        "elapsed_ms": result.elapsed_ms,
        "row_count": result.row_count,
        "outcome": "ok" if result.error is None else result.error.kind,
    }
    # ASSUMPTION: "masked" yalnız bir şey maskelendiyse yazılıyor, yani maskesiz girdi Run 1
    # sözleşmesinin altı alanıyla kalmaya devam ediyor; adlar burada, değerler hiçbir yerde.
    if result.masked_columns:
        entry["masked"] = list(result.masked_columns)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
