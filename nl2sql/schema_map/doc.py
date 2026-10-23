"""Schema document: loader, policy allowlist and the two text forms the model sees."""

from __future__ import annotations

import json
from pathlib import Path

from nl2sql import config

# ASSUMPTION: table/column descriptions are Turkish because the questions and the CLI are Turkish;
# the model has to map "ürün" -> STOK_ADI, so the text it reads is in the question's language.


def load_schema(path: str | Path = config.SCHEMA_PATH) -> dict:
    """Canonical schema doc; optional fields get their contract defaults."""
    with open(path, encoding="utf-8") as handle:
        schema = json.load(handle)
    for table in schema["tables"]:
        table.setdefault("description", "")
        table.setdefault("module", "")
        for column in table["columns"]:
            column.setdefault("description", "")
            column.setdefault("fk", None)
            column.setdefault("values", {})
            column.setdefault("nullable", True)
    return schema


def allowlist(schema: dict) -> set[str]:
    """Upper-cased table names the policy may allow."""
    return {table["name"].upper() for table in schema["tables"]}


def compact_text(schema: dict) -> str:
    """One line per table: name, description, module."""
    return "\n".join(_table_header(table) for table in schema["tables"])


def table_detail(schema: dict, tables: list[str]) -> str:
    """Columns, types, foreign keys and code values for the asked tables.

    Unknown or missing table names return a short error text instead of a partial answer,
    so the model gets one clear signal it can act on.
    """
    index = {table["name"].upper(): table for table in schema["tables"]}
    known = ", ".join(sorted(index))
    wanted = []
    for name in tables:
        table = index.get(str(name).strip().upper())
        if table is None:
            return f"Bilinmeyen tablo: {name}. Bilinen tablolar: {known}."
        wanted.append(table)
    if not wanted:
        return f"Tablo adı verilmedi. Bilinen tablolar: {known}."
    return "\n\n".join(
        "\n".join([_table_header(table)] + [_column_line(column) for column in table["columns"]])
        for table in wanted
    )


def _table_header(table: dict) -> str:
    module = f" [{table['module']}]" if table["module"] else ""
    return f"{table['name']} — {table['description']}{module}"


def _column_line(column: dict) -> str:
    line = f"  {column['name']} {column['type']}"
    if not column["nullable"]:
        line += " NOT NULL"
    if column["description"]:
        line += f" — {column['description']}"
    if column["fk"]:
        line += f" -> {column['fk']}"
    if column["values"]:
        codes = ", ".join(f"{code}={meaning}" for code, meaning in column["values"].items())
        line += f" [{codes}]"
    return line
