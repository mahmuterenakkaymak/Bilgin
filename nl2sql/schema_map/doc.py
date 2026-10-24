"""Schema document: loader, policy allowlist and the text forms the model sees."""

from __future__ import annotations

import json
import math
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
        table.setdefault("kind", "data")
        table.setdefault("keywords", [])
        for column in table["columns"]:
            column.setdefault("description", "")
            column.setdefault("fk", None)
            column.setdefault("values", {})
            column.setdefault("nullable", True)
            column.setdefault("pii", None)
            column.setdefault("deny", False)
    return schema


def allowlist(schema: dict) -> set[str]:
    """Upper-cased table names the policy may allow."""
    return {table["name"].upper() for table in schema["tables"]}


def split_name(name: str) -> tuple[str | None, str]:
    """`"Sales.Orders"` -> `("Sales", "Orders")`; a bare name -> `(None, "TBLSTHAR")` (PLAN R4-5)."""
    schema, _, table = str(name).strip().rpartition(".")
    return schema or None, table


def split_fk(fk: str) -> tuple[str, str]:
    """`"Sales.Orders.CustomerID"` -> `("Sales.Orders", "CustomerID")`: the column is the last part (R4-5)."""
    table, _, column = str(fk).strip().rpartition(".")
    return table, column


def resolve_table(name: str, names: list[str]) -> str | list[str] | None:
    """Canonical full name of an asked table, None when nothing matches, the candidates when ambiguous.

    The exact (case-insensitive) full-name match comes first, so a schema that holds both `Orders`
    and `Sales.Orders` keeps answering to `Orders` (PLAN R4-5).
    """
    wanted = str(name).strip().casefold()
    full = list(names)
    for candidate in full:
        if candidate.casefold() == wanted:
            return candidate
    matches = [candidate for candidate in full if split_name(candidate)[1].casefold() == wanted]
    return matches[0] if len(matches) == 1 else (matches or None)


def compact_text(schema: dict) -> str:
    """One line per table: name, description, module."""
    return "\n".join(_table_header(table) for table in schema["tables"])


def name_list(schema: dict) -> str:
    """Table names grouped by module, one line per module: the `rag` prompt has no room for descriptions."""
    modules: dict[str, list[str]] = {}
    for table in schema["tables"]:
        modules.setdefault(table["module"], []).append(table["name"])
    return "\n".join(f"{module}: {', '.join(names)}" for module, names in modules.items())


def table_detail(schema: dict, tables: list[str]) -> str:
    """Columns, types, foreign keys and code values for the asked tables.

    Unknown or missing table names return a short error text instead of a partial answer,
    so the model gets one clear signal it can act on. A table may be asked by its full
    `Schema.Table` name or, when that is unique, by its bare name (PLAN R4-5).
    """
    index = {table["name"].upper(): table for table in schema["tables"]}
    # ASSUMPTION: R2-4's distractors stay out of this hint; once the schema has ~81 tables the list is
    # nothing the model can act on, and the tables worth falling back to are the real ones.
    known = ", ".join(sorted(name for name, table in index.items() if table.get("kind") != "distractor"))
    names = [table["name"] for table in schema["tables"]]
    wanted = []
    for name in tables:
        asked = str(name).strip()
        found = resolve_table(asked, names)
        if isinstance(found, list):
            return f"Belirsiz tablo adı: {asked} ({', '.join(found)}); şemasıyla yazın."
        if found is None:
            return f"Bilinmeyen tablo: {asked}. Bilinen tablolar: {known}."
        wanted.append(index[found.upper()])
    if not wanted:
        return f"Tablo adı verilmedi. Bilinen tablolar: {known}."
    return "\n\n".join(_table_block(table) for table in wanted)


def full_text(schema: dict) -> str:
    """Every table in full detail - the `full` mode prompt (R2-5); estimate the cost with estimate_tokens."""
    return table_detail(schema, [table["name"] for table in schema["tables"]])


def estimate_tokens(text: str) -> int:
    """Char-based token estimate for prompt budgets (PLAN R2-5)."""
    return math.ceil(len(text) / config.CHARS_PER_TOKEN)


def _table_block(table: dict) -> str:
    """Başlık ve okunabilir kolonlar: bir `deny` kolon hiçbir model metnine düşmez (PLAN R4-7)."""
    lines = [_table_header(table)]
    lines += [_column_line(column) for column in table["columns"] if not column["deny"]]
    return "\n".join(lines)


def _table_header(table: dict) -> str:
    # kind/keywords (R2-2) stay out of every model-facing text: a real ERP schema has no such flags.
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
