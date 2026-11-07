# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Masked display values for PII columns (PLAN R3-6).

The executor masks every value that traces back to a column carrying `pii`, so the model,
the CLI and the eval only ever see the forms below. Each class keeps the smallest part that
still lets a reader recognise which row they are looking at - the tail of an account number,
the city of an address - and drops everything else; none of it is reversible.

`trace` answers the other half of the same rule: which source columns an output column came
from, so the executor knows which mask a column gets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError
from sqlglot.lineage import lineage
from sqlglot.optimizer.qualify import qualify

from bilgin.schema_map import doc

CLASSES = (
    "tckn",
    "vkn",
    "iban",
    "phone",
    "email",
    "address",
    "salary",
    "person_name",
)

_WORDS = re.compile(r"[^\W\d_]+")


def mask(cls: str, value) -> str | None:
    """Masked text for one PII class: None stays None, a blank stays blank, a non-str is read as text."""
    if value is None:
        return None
    if cls not in CLASSES:
        raise ValueError(f"bilinmeyen pii sınıfı: {cls}")
    text = value if isinstance(value, str) else str(value)
    if not text.strip():
        return ""
    return _MASKERS[cls](text)


def _tail(text: str, n: int, digits_only: bool = False) -> str:
    """Last n characters of the value with its formatting (spaces) removed."""
    keep = str.isdigit if digits_only else lambda ch: not ch.isspace()
    return "".join(ch for ch in text if keep(ch))[-n:]


def _id_number(text: str) -> str:
    return "*******" + _tail(text, 4, digits_only=True)


def _iban(text: str) -> str:
    return "TR** **** **** **** " + _tail(text, 4)


def _phone(text: str) -> str:
    return "*** ** " + _tail(text, 3, digits_only=True)


def _salary(text: str) -> str:
    return "***"


def _address(text: str) -> str:
    return text.split(",")[0].strip()


def _email(text: str) -> str:
    local, at, domain = text.strip().rpartition("@")
    if not at:
        return "***"
    return f"{local[:1]}***@{domain}"


def _person_name(text: str) -> str:
    return " ".join(f"{word[0].upper()}." for word in _WORDS.findall(text))


_MASKERS = {
    "tckn": _id_number,
    "vkn": _id_number,
    "iban": _iban,
    "phone": _phone,
    "email": _email,
    "address": _address,
    "salary": _salary,
    "person_name": _person_name,
}


def column_map(schema: dict) -> dict[tuple[str, str], str]:
    """{(FULL_TABLE, COLUMN): class} for every column the schema marks with a `pii` class.

    FULL_TABLE is the upper full name, so a table outside the default schema is keyed exactly the
    way the policy allowlist names it: `SALES.CUSTOMERS` (PLAN R4-7).

    The classes are carried as the schema wrote them: a mark the maskers do not know is the
    caller's signal to hide the value entirely, never a reason to show it.
    """
    return {
        (table["name"].upper(), column["name"].upper()): column["pii"]
        for table in schema["tables"]
        for column in table["columns"]
        if column.get("pii")
    }


def deny_set(schema: dict) -> set[tuple[str, str]]:
    """{(FULL_TABLE, COLUMN)} for every column the schema marks `deny` (PLAN R4-7).

    The same key form as `column_map`, because the policy reads the two side by side: a `pii` mark
    hides a value, a `deny` mark hides the column itself, so it never reaches the mask at all.
    """
    return {
        (table["name"].upper(), column["name"].upper())
        for table in schema["tables"]
        for column in table["columns"]
        if column.get("deny")
    }


def count_keys(schema: dict) -> dict[str, str]:
    """{FULL_TABLE: COLUMN}: the first NOT NULL column with no `pii`/`deny` mark, per table.

    The read-only login DENYs every marked column, and SQL Server then refuses `COUNT(*)` on that table
    (found on the restored WideWorldImporters, 2026-10-25); `COUNT(key)` counts the same rows.
    """
    keys = {}
    for table in schema["tables"]:
        for column in table["columns"]:
            if not column.get("nullable", True) and not column.get("pii") and not column.get("deny"):
                keys[table["name"].upper()] = column["name"]
                break
    return keys


# ----------------------------------------------------------------- lineage


@dataclass(frozen=True)
class Trace:
    """One output column of a traced SELECT: its name and the source columns its values came from."""

    name: str
    sources: list[tuple[str, str]] | None
    aggregate: str | None = None


def trace(sql: str, schema: dict) -> list[Trace]:
    """Per output column, in select order: the [(FULL_TABLE, COLUMN)] pairs its values come from.

    Aliases, CTE renames, derived tables and subqueries are resolved, so a column reaches the
    real schema columns behind it - a qualified table by its full `SALES.CUSTOMERS` name (R4-7).
    `sources` is None when the lineage cannot be followed - and then the caller masks the whole
    column, because an untraced column is never shown raw.
    `aggregate` names the aggregate function wrapped around the column; only "count" (COUNT and
    COUNT(DISTINCT x)) is on the R3-6 whitelist, and it keeps its sources so the caller can see
    what was counted.

    An empty list means the SQL could not be traced at all, which the caller reads the same way.
    """
    columns = _column_types(schema)
    lineage_schema = _lineage_schema(columns)
    try:
        tree = parse_one(sql, read="tsql")
        if not isinstance(tree, exp.Query):
            return []
        # qualify first: it expands SELECT * and rewrites every reference to table.column, so
        # the lineage answer lines up with the output columns one by one.
        tree = qualify(tree, dialect="tsql", schema=lineage_schema, validate_qualify_columns=False, identify=False)
        nodes = lineage(None, tree, schema=lineage_schema, dialect="tsql")
    except SqlglotError:
        return []
    branches = _branches(tree)
    if len(nodes) != len(branches[0]):
        # Two output columns sharing a name collapse into one lineage key, so the caller's column
        # list can no longer be matched by position: nothing in this query is trusted.
        return []
    return [
        Trace(name.upper(), _sources(node, columns), _aggregate(branches, position))
        for position, (name, node) in enumerate(nodes.items())
    ]


def _column_types(schema: dict) -> dict:
    """{FULL_TABLE: {COLUMN: type}}: the schema doc keyed by the full names the PII map uses."""
    return {
        table["name"].upper(): {column["name"].upper(): column.get("type") or "" for column in table["columns"]}
        for table in schema["tables"]
    }


def _lineage_schema(columns: dict) -> dict:
    """The column map as sqlglot wants it: a qualified table nests under its schema (R4-7).

    ASSUMPTION: sqlglot's lineage schema has a single nesting level, so a doc that mixes bare and
    qualified names cannot be handed over at all; trace then returns [] and the caller masks all.
    """
    lineage_schema: dict = {}
    for name, types in columns.items():
        schema_part, table = doc.split_name(name)
        if schema_part:
            lineage_schema.setdefault(schema_part, {})[table] = types
        else:
            lineage_schema[table] = types
    return lineage_schema


def _branches(query) -> list[list]:
    """Positional select lists of the UNION branches; a plain SELECT is a single list."""
    if isinstance(query, exp.SetOperation):
        return _branches(query.this) + _branches(query.expression)
    return [query.selects]


def _aggregate(branches, position) -> str | None:
    """The aggregate wrapping that output column in every branch; None when the branches differ.

    Only the column's own aggregate counts: a COUNT buried in a CASE that also returns a salary
    would otherwise whitelist the whole column.
    """
    kinds = set()
    for branch in branches:
        expr = branch[position].unalias() if position < len(branch) else None
        kinds.add(expr.key if isinstance(expr, exp.AggFunc) else None)
    return kinds.pop() if len(kinds) == 1 else None


def _sources(node, columns) -> list[tuple[str, str]] | None:
    """The pairs a lineage graph bottoms out at; None as soon as any part of it cannot be read."""
    found: set[tuple[str, str]] = set()
    for step in node.walk():
        if isinstance(step.source, exp.Placeholder) or isinstance(step.expression, exp.Placeholder):
            return None  # sqlglot stopped: an unknown alias or a column two tables both have
        if step.downstream:
            continue
        if isinstance(step.source, exp.Table):
            pairs = [(_table_name(step.source), step.name.rpartition(".")[2])]
        else:
            pairs = [(_column_table(column), column.name) for column in step.expression.find_all(exp.Column)]
        for table, column in pairs:
            if column.upper() not in columns.get(table.upper(), {}):
                return None  # a table or column the schema doc does not know carries no pii flag to read
            found.add((table.upper(), column.upper()))
    return sorted(found)


def _table_name(table) -> str:
    """The declared table behind an alias, schema included: `Sales.Customers AS C` reads as such."""
    name = table.this.name if isinstance(table.this, exp.Identifier) else table.name
    return f"{table.db}.{name}" if table.db else name


def _column_table(column) -> str:
    """The table a column reference names, schema included when the reference carries one."""
    return f"{column.db}.{column.table}" if column.db else column.table
