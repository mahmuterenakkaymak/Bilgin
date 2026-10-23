"""Live database -> canonical schema doc: the skeleton the Excel map is merged and diffed against (PLAN R3-4)."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from nl2sql import config

# build.py collapses every T-SQL type onto one SQLite affinity, so the inverse can only name that
# affinity's T-SQL type; a length the file does declare (one not built by build.py) is carried through.
# ASSUMPTION: SQLite stores neither a length nor the VARCHAR/NVARCHAR/DATE distinction, so a skeleton
# type is the affinity's T-SQL name; the tests compare it through build.SQLITE_TYPES instead of to the
# schema's exact "VARCHAR(20)" text.
SQLITE_TO_TSQL = {"INTEGER": "INT", "REAL": "DECIMAL", "TEXT": "VARCHAR"}


def normalize_type(declared: str) -> str:
    """Declared SQLite type -> the T-SQL type name schema.json uses (inverse of build.SQLITE_TYPES)."""
    base, _, rest = declared.strip().upper().partition("(")
    name = SQLITE_TO_TSQL.get(base, base)
    return f"{name}({rest[:-1]})" if rest.endswith(")") else name


def sqlite_skeleton(db_path: str | Path = config.DB_PATH) -> dict:
    """Structure only: a database knows names, types, nullability and fks, not meaning (R3-4)."""
    conn = sqlite3.connect(f"{Path(db_path).resolve().as_uri()}?mode=ro", uri=True)
    try:
        names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
            )
        ]
        return {"tables": [_table(conn, name) for name in names]}
    finally:
        conn.close()


def _table(conn: sqlite3.Connection, name: str) -> dict:
    columns = [
        {
            "name": row[1],
            "type": normalize_type(row[2]),
            "description": "",
            "fk": None,
            "values": {},
            "nullable": not row[3],
        }
        for row in conn.execute(f"PRAGMA table_info({_quote(name)})")
    ]
    _read_fks(conn, name, columns)
    return {"name": name, "description": "", "module": "", "kind": "unknown", "columns": columns}


def _read_fks(conn: sqlite3.Connection, name: str, columns: list[dict]) -> None:
    """PRAGMA foreign_key_list gives one row per (constraint, column) pair; fk is "TABLE.COL"."""
    index = {column["name"]: column for column in columns}
    for row in conn.execute(f"PRAGMA foreign_key_list({_quote(name)})"):
        parent, column_name, referenced = row[2], row[3], row[4]
        # ASSUMPTION: a NULL "to" means the parent column is implicit (its primary key); the parent
        # key is not looked up here, so such a column stays without an fk.
        column = index.get(column_name)
        if column is not None and referenced:
            column["fk"] = f"{parent}.{referenced}"


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'
