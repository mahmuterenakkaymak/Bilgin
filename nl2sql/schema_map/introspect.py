# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Live database -> canonical schema doc: the skeleton the Excel map is merged and diffed against (PLAN R3-4)."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from nl2sql import config
# ASSUMPTION: the connection string has a single owner in this project, engine/_mssql, so the env var
# name, the forced read-only intent and the sentence naming the variable are imported, not repeated.
from nl2sql.engine._mssql import CONN_ENV, MISSING_CONN, NO_MODULE, _read_only
from nl2sql.engine.result import Budget

class IntrospectError(RuntimeError):
    """Introspection cannot run at all; the message names what the user has to fix."""


# build.py collapses every T-SQL type onto one SQLite affinity, so the inverse can only name that
# affinity's T-SQL type; a length the file does declare (one not built by build.py) is carried through.
# ASSUMPTION: SQLite stores neither a length nor the VARCHAR/NVARCHAR/DATE distinction, so a skeleton
# type is the affinity's T-SQL name; the tests compare it through build.SQLITE_TYPES instead of to the
# schema's exact "VARCHAR(20)" text.
# ASSUMPTION: build.py collapses DATETIME and DATETIME2 onto the one SQLite affinity DATETIME, so the
# inverse keeps DATETIME as DATETIME; naming it DATETIME2 would turn every real DATETIME column into one.
SQLITE_TO_TSQL = {
    "INTEGER": "INT",
    "REAL": "DECIMAL",
    "TEXT": "VARCHAR",
    "BOOLEAN": "BIT",
    "BLOB": "VARBINARY",
}


def normalize_type(declared: str) -> str:
    """Declared SQLite type -> the T-SQL type name schema.json uses (inverse of build.SQLITE_TYPES)."""
    base, _, rest = declared.strip().upper().partition("(")
    name = SQLITE_TO_TSQL.get(base, base)
    return f"{name}({rest[:-1]})" if rest.endswith(")") else name


def sqlite_skeleton(db_path: str | Path = config.DB_PATH) -> dict:
    """Structure only: a database knows names, types, nullability and fks, not meaning (R3-4).

    A table's stored identifier is its name, so a qualified build reads back "Sales.Orders" (R4-6).
    """
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


# The only place a SQL Server introspection statement is written (R3-4); the tests parse each one with
# sqlglot instead of running them. Rows come back in the column order selected below:
#   tables         (schema, table)
#   columns        (schema, table, column, data type, max length, precision, scale, "YES"/"NO")
#   foreign_keys   (schema, table, column, referenced schema, referenced table, referenced column)
# The skeleton names a table of its own schema "<schema>.<table>" and a dbo table bare, the way
# schema.json does (R4-6), so two same-named tables in different schemas are two different names.
MSSQL_QUERIES = {
    "tables": (
        "SELECT TABLE_SCHEMA, TABLE_NAME"
        " FROM INFORMATION_SCHEMA.TABLES"
        " WHERE TABLE_TYPE = 'BASE TABLE'"
        " ORDER BY TABLE_SCHEMA, TABLE_NAME"
    ),
    "columns": (
        "SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE,"
        " CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE, IS_NULLABLE"
        " FROM INFORMATION_SCHEMA.COLUMNS"
        " ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION"
    ),
    "foreign_keys": (
        "SELECT OBJECT_SCHEMA_NAME(fk.parent_object_id), OBJECT_NAME(fk.parent_object_id), pc.name,"
        " OBJECT_SCHEMA_NAME(fk.referenced_object_id), OBJECT_NAME(fk.referenced_object_id), rc.name"
        " FROM sys.foreign_keys AS fk"
        " JOIN sys.foreign_key_columns AS fkc ON fkc.constraint_object_id = fk.object_id"
        " JOIN sys.columns AS pc ON pc.object_id = fk.parent_object_id AND pc.column_id = fkc.parent_column_id"
        " JOIN sys.columns AS rc ON rc.object_id = fk.referenced_object_id AND rc.column_id = fkc.referenced_column_id"
        " ORDER BY OBJECT_SCHEMA_NAME(fk.parent_object_id), OBJECT_NAME(fk.parent_object_id), pc.name"
    ),
}


def rows_to_skeleton(table_rows, column_rows, fk_rows) -> dict:
    """Introspection rows -> canonical skeleton; pure, so the unit test hands it rows directly."""
    tables = {
        (schema, table): {
            "name": _qualified_name(schema, table),
            "description": "",
            "module": "",
            "kind": "unknown",
            "columns": [],
        }
        for schema, table in table_rows
    }
    for row in column_rows:
        table = tables.get((row[0], row[1]))
        # ASSUMPTION: INFORMATION_SCHEMA.COLUMNS also lists view columns, and views are not part of a
        # skeleton, so a column of a table the table query did not return is dropped.
        if table is None:
            continue
        table["columns"].append(
            {
                "name": row[2],
                "type": _mssql_type(row[3], row[4], row[5], row[6]),
                "description": "",
                "fk": None,
                "values": {},
                "nullable": str(row[7]).upper() == "YES",
            }
        )
    index = {key: {column["name"]: column for column in table["columns"]} for key, table in tables.items()}
    for schema, table, column_name, ref_schema, ref_table, ref_column in fk_rows:
        column = index.get((schema, table), {}).get(column_name)
        if column is not None:
            column["fk"] = f"{_qualified_name(ref_schema, ref_table)}.{ref_column}"
    return {"tables": list(tables.values())}


def _qualified_name(schema: str, table: str) -> str:
    """dbo is the database's own schema and stays bare, the way schema.json writes it (R4-6)."""
    return table if str(schema).upper() == "DBO" else f"{schema}.{table}"


def mssql_skeleton(conn_str: str | None = None) -> dict:
    """Live SQL Server -> skeleton, over a read-only session; pyodbc is imported only here (R3-4).

    A missing driver and a server that will not answer are both things the user can fix, so each
    becomes an IntrospectError carrying the driver's own sentence, the way engine/_mssql reports
    the same failures (Delight 3); the CLI prints that one line instead of a traceback.
    """
    dsn = (conn_str or os.environ.get(CONN_ENV, "")).strip()
    if not dsn:
        raise IntrospectError(MISSING_CONN)
    try:
        import pyodbc
    except ImportError as exc:
        raise IntrospectError(NO_MODULE) from exc

    try:
        conn = pyodbc.connect(_read_only(dsn))
        try:
            rows = {name: _fetch(conn, sql) for name, sql in MSSQL_QUERIES.items()}
        finally:
            conn.close()
    except pyodbc.Error as exc:
        raise IntrospectError(_driver_failure(exc)) from exc
    return rows_to_skeleton(rows["tables"], rows["columns"], rows["foreign_keys"])


def _driver_failure(exc: Exception) -> str:
    """The driver says what refused it; the sentence keeps that text and adds the variable to check."""
    head = f"SQL Server yoklanamadı; {CONN_ENV} ortam değişkenini ve sunucuyu denetleyin"
    text = " ".join(str(exc).split())
    return f"{head}: {text}" if text else f"{head}."


def _mssql_type(data_type: str, max_length, precision, scale) -> str:
    """INFORMATION_SCHEMA keeps the size in its own columns; schema.json writes it inside the name."""
    name = str(data_type).upper()
    if name in ("CHAR", "VARCHAR", "NCHAR", "NVARCHAR"):
        return f"{name}(MAX)" if max_length == -1 else f"{name}({max_length})"
    if name in ("DECIMAL", "NUMERIC"):
        return f"{name}({precision},{scale})"
    return name


def _fetch(conn, sql: str) -> list[tuple]:
    return [tuple(row) for row in conn.execute(sql)]


# ------------------------------------------------------------------ --sample (R3-4)
SAMPLE_SOURCE = "introspect"
TEXT_TYPES = frozenset({"CHAR", "VARCHAR", "NCHAR", "NVARCHAR"})


# ASSUMPTION: R3-4 hands db_path to the sampler next to the executor; the executor is what owns the
# connection (policy and audit inside), so the path is never opened here and execute stays the only door.
def sample_hints(db_path: str | Path, schema: dict, executor) -> dict:
    """Adds up to config.SAMPLE_HINT_N distinct values per short text column; returns the same schema.

    Every value comes from ``executor.execute``, so a sample query runs the same policy and leaves the
    same audit line as a model query. A column whose ``pii`` is set is never queried at all (R3-6), and
    a column whose query fails is left without a hint: a skeleton worth reading is worth more than a
    failed sample, so nothing here raises.
    """
    for table in schema["tables"]:
        for column in table["columns"]:
            if column.get("pii") or not _short_text(column["type"]):
                continue
            values = _distinct(executor, table["name"], column["name"])
            if values:
                column["sample"] = values
    return schema


def _short_text(type_name: str) -> bool:
    """Character type whose declared length fits the inline hint; a SQLite skeleton declares no length."""
    base, _, rest = str(type_name).strip().upper().partition("(")
    if base not in TEXT_TYPES:
        return False
    if not rest.endswith(")"):
        return True
    length = rest[:-1]
    return length.isdigit() and int(length) <= config.SAMPLE_HINT_MAX_LEN


def _distinct(executor, table: str, column: str) -> list:
    sql = (
        f"SELECT DISTINCT TOP {config.SAMPLE_HINT_N} [{column}] FROM [{table}]"
        f" WHERE [{column}] IS NOT NULL ORDER BY [{column}]"
    )
    result = executor.execute(sql, Budget(max_rows=config.SAMPLE_HINT_N), SAMPLE_SOURCE)
    return [] if result.error is not None else [row[0] for row in result.rows]
