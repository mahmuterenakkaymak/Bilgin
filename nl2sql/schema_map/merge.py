"""Excel map + live DB skeleton -> one canonical schema doc: the merge of R3-5.

Two producers, one schema. The database is what exists, so it owns existence, types, nullability and
foreign keys; the Excel map is what the business says about those columns, so it owns the meaning.
Neither side is complete, and neither side is trusted outside its own half.
"""

from __future__ import annotations

import copy

# Table-level fields the map decides; everything else on a table (name, kind) came with the skeleton.
TABLE_MEANING = ("description", "module", "keywords")
# Column-level fields the map decides. "fk" is deliberately absent: a reference the database does not
# declare is a claim, not a fact, so it belongs to the diff (R3-5) and never to a merged schema.
COLUMN_MEANING = ("description", "values")


def merge_map(excel: dict, db: dict) -> dict:
    """Merged canonical schema doc: DB order and DB structure, Excel meaning where the map has one.

    Tables and columns the map alone names are dropped here — they are the diff's business (T90) —
    and the inputs are never modified.
    """
    maps = _by_name(excel.get("tables") or [])
    tables = []
    for table in db.get("tables") or []:
        merged = copy.deepcopy(table)
        source = maps.get(_key(merged.get("name", "")))
        if source is not None:
            _merge_table(merged, source)
        tables.append(merged)
    return {"tables": tables}


def _merge_table(table: dict, excel_table: dict) -> None:
    table.setdefault("keywords", [])
    for field in TABLE_MEANING:
        value = excel_table.get(field)
        if value:
            table[field] = copy.deepcopy(value)
    columns = _by_name(excel_table.get("columns") or [])
    for column in table["columns"]:
        source = columns.get(_key(column.get("name", "")))
        if source is None:
            continue
        for field in COLUMN_MEANING:
            value = source.get(field)
            if value:
                column[field] = copy.deepcopy(value)


def _by_name(items: list) -> dict:
    """Items indexed by upper-cased ``name``: the schema's own name rule (doc.py, policy)."""
    return {_key(item.get("name", "")): item for item in items}


def _key(name: str) -> str:
    return str(name).strip().upper()
