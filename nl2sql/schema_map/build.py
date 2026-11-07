# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Dataset -> physical build targets: the SQLite file the executor queries and the T-SQL script for MSSQL."""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

from nl2sql import config
from nl2sql.schema_map import doc

# One INSERT statement carries this many rows, so the script stays readable and under any
# per-statement parameter limit.
INSERT_BATCH_ROWS = 50

# schema.json holds T-SQL types (it documents the real target); SQLite needs its own affinity.
SQLITE_TYPES = {
    "INT": "INTEGER",
    "DATE": "TEXT",
    "DECIMAL": "REAL",
    "VARCHAR": "TEXT",
    "NVARCHAR": "TEXT",
    # SQLite'ta bunlar yalnız bildirilen ad, yakınlık yeter: sayıya dönmeyen ISO tarih metin
    # kalır, BIT 0/1, VARBINARY bytes olarak döner (PLAN R4-6).
    "BIT": "BOOLEAN",
    "DATETIME2": "DATETIME",
    # DATETIME stays DATETIME when read back (introspect.normalize_type keeps it), so it needs its own entry.
    "DATETIME": "DATETIME",
    "VARBINARY": "BLOB",
}


def write_sqlite(dataset: dict, schema: dict, path: str | Path = config.DB_PATH) -> None:
    """Create a fresh SQLite file from the dataset; columns and their order come from schema.json."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    conn = sqlite3.connect(path)
    try:
        for table in schema["tables"]:
            conn.execute(f"CREATE TABLE {_quote(table['name'])} ({_sqlite_columns(table)})")
            rows = dataset.get(table["name"], [])
            if not rows:
                continue
            names = [column["name"] for column in table["columns"]]
            conn.executemany(
                "INSERT INTO {} ({}) VALUES ({})".format(
                    _quote(table["name"]),
                    ", ".join(_quote(name) for name in names),
                    ", ".join("?" * len(names)),
                ),
                [tuple(row[name] for name in names) for row in rows],
            )
        conn.commit()
    finally:
        conn.close()


def write_mssql_script(dataset: dict, schema: dict, path: str | Path = config.MSSQL_SCRIPT) -> None:
    """T-SQL build script: CREATE SCHEMA per schema, CREATE TABLE per table, then the rows as batched INSERTs, GO-separated."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    statements = [_CREATE_HEADER, *_create_schemas(schema)]
    for table in schema["tables"]:
        statements.append(f"CREATE TABLE {_tsql_name(table['name'])} ({_tsql_columns(table)});")
        statements.extend(_insert_statements(table, dataset.get(table["name"], [])))
    path.write_text("\nGO\n\n".join(statements) + "\n", encoding="utf-8")


def checksum(path: str | Path = config.DB_PATH) -> str:
    """sha256 over the whole database: tables by name, rows by every column.

    Two builds of the same seed match; any changed cell changes the digest.
    """
    digest = hashlib.sha256()
    conn = sqlite3.connect(path)
    try:
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        for name in tables:
            columns = [row[1] for row in conn.execute(f"PRAGMA table_info({_quote(name)})")]
            digest.update(f"{name}\n".encode("utf-8"))
            for row in conn.execute(
                "SELECT * FROM {} ORDER BY {}".format(
                    _quote(name), ", ".join(_quote(column) for column in columns)
                )
            ):
                digest.update(f"{row!r}\n".encode("utf-8"))
    finally:
        conn.close()
    return digest.hexdigest()



_CREATE_HEADER = (
    "-- Bu dosya `python -m nl2sql build-db` ile üretilir; elle düzenlemeyin.\n"
    "-- Boş bir veritabanında çalıştırılır (tabloları oluşturur)."
)


def _create_schemas(schema: dict) -> list[str]:
    """Her şema bir kez, tablolarından önce; dbo veritabanıyla birlikte zaten vardır (PLAN R4-6)."""
    statements, written = [], set()
    for table in schema["tables"]:
        name, _ = doc.split_name(table["name"])
        if name and name.upper() not in written and name.upper() != "DBO":
            written.add(name.upper())
            statements.append(f"CREATE SCHEMA [{name}];")
    return statements


def _tsql_name(name: str) -> str:
    """Nitelikli ad köşeli parantezle yazılır: [Sales].[Orders]; çıplak ad bugünkü gibi düzdür."""
    name_schema, table = doc.split_name(name)
    return f"[{name_schema}].[{table}]" if name_schema else name


def _insert_statements(table: dict, rows: list[dict]) -> list[str]:
    columns = table["columns"]
    names = ", ".join(column["name"] for column in columns)
    head = f"INSERT INTO {_tsql_name(table['name'])} ({names}) VALUES"
    batches = []
    for start in range(0, len(rows), INSERT_BATCH_ROWS):
        values = ",\n".join(
            "(" + ", ".join(_tsql_value(row[column["name"]], column["type"]) for column in columns) + ")"
            for row in rows[start : start + INSERT_BATCH_ROWS]
        )
        batches.append(f"{head}\n{values};")
    return batches


def _tsql_value(value, sql_type: str) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, (bytes, bytearray)):
        return f"0x{bytes(value).hex()}"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("'", "''")
    return f"N'{text}'" if sql_type.upper().startswith("NVARCHAR") else f"'{text}'"


def _sqlite_columns(table: dict) -> str:
    return ", ".join(
        f"{column['name']} {SQLITE_TYPES[column['type'].split('(')[0].upper()]}{_not_null(column)}"
        for column in table["columns"]
    )


def _tsql_columns(table: dict) -> str:
    return ", ".join(f"{column['name']} {column['type']}{_not_null(column)}" for column in table["columns"])


def _not_null(column: dict) -> str:
    return "" if column["nullable"] else " NOT NULL"


def _quote(name: str) -> str:
    return f'"{name}"'
