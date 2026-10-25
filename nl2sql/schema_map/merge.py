"""Excel map + live DB skeleton -> one canonical schema doc: the merge of R3-5.

Two producers, one schema. The database is what exists, so it owns existence, types, nullability and
foreign keys; the Excel map is what the business says about those columns, so it owns the meaning.
Neither side is complete, and neither side is trusted outside its own half.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

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


def diff_map(excel: dict, db: dict) -> dict:
    """Every disagreement between the map and the database; the merge drops these, the diff reports them (R3-5).

    Names are matched the way the schema names them (upper-cased, trimmed), and a table both sides name
    is reported under the database's own name, so a case difference never reads as two separate tables.
    """
    excel_tables = _by_name(excel.get("tables") or [])
    db_tables = _by_name(db.get("tables") or [])
    report = {
        "excel_only_tables": [
            table.get("name", "")
            for table in excel.get("tables") or []
            if _key(table.get("name", "")) not in db_tables
        ],
        "db_only_tables": [
            table.get("name", "")
            for table in db.get("tables") or []
            if _key(table.get("name", "")) not in excel_tables
        ],
        "excel_only_columns": [],
        "db_only_columns": [],
        "type_mismatches": [],
        "fk_missing_in_db": [],
    }
    for table in db.get("tables") or []:
        other = excel_tables.get(_key(table.get("name", "")))
        if other is None:
            continue
        name = table.get("name", "")
        excel_columns = _by_name(other.get("columns") or [])
        db_columns = _by_name(table.get("columns") or [])
        for column in other.get("columns") or []:
            if _key(column.get("name", "")) not in db_columns:
                report["excel_only_columns"].append({"table": name, "column": column.get("name", "")})
        for column in table.get("columns") or []:
            excel_column = excel_columns.get(_key(column.get("name", "")))
            if excel_column is None:
                report["db_only_columns"].append({"table": name, "column": column.get("name", "")})
                continue
            if _type_key(excel_column.get("type")) != _type_key(column.get("type")):
                report["type_mismatches"].append({
                    "table": name,
                    "column": column.get("name", ""),
                    "excel": excel_column.get("type", ""),
                    "db": column.get("type", ""),
                })
            if excel_column.get("fk") and not column.get("fk"):
                report["fk_missing_in_db"].append({
                    "table": name,
                    "column": column.get("name", ""),
                    "fk": excel_column.get("fk"),
                })
    return report


def render_diff(report: dict) -> str:
    """DiffReport -> markdown: her bölüm kendi başlığı ve sayısıyla; boş bölüm yazılmaz."""
    lines = ["# Şema fark raporu", ""]
    for key, title, render in SECTIONS:
        items = report.get(key) or []
        if not items:
            continue
        lines.append(f"## {title} ({len(items)})")
        lines.extend(f"- {render(item)}" for item in items)
        lines.append("")
    if len(lines) == 2:
        lines.append("Fark yok.")
    return "\n".join(lines) + "\n"


def save_diff(report: dict, json_path: str | Path, md_path: str | Path) -> None:
    """DiffReport'u makinenin (json) ve insanın (md) okuyacağı iki dosyaya yazar."""
    _write_json(json_path, report)
    target = Path(md_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_diff(report), encoding="utf-8")


def _column_ref(item: dict) -> str:
    return f"{item.get('table', '')}.{item.get('column', '')}"


def _type_mismatch(item: dict) -> str:
    return f"{_column_ref(item)}: excel={item.get('excel', '')} db={item.get('db', '')}"


def _fk_ref(item: dict) -> str:
    return f"{_column_ref(item)} → {item.get('fk', '')}"


# The six sections of a DiffReport, in report order: key, Turkish title, one-line renderer. render_diff
# and the CLI's count lines both read this, so a section is named in exactly one place.
SECTIONS = (
    ("excel_only_tables", "Tablo yalnız Excel'de", str),
    ("db_only_tables", "Tablo yalnız veritabanında", str),
    ("excel_only_columns", "Kolon yalnız Excel'de", _column_ref),
    ("db_only_columns", "Kolon yalnız veritabanında", _column_ref),
    ("type_mismatches", "Tip uyuşmazlığı", _type_mismatch),
    ("fk_missing_in_db", "Veritabanında olmayan foreign key", _fk_ref),
)


def _type_key(type_name) -> str:
    return str(type_name or "").strip().upper()


def _write_json(path: str | Path, payload: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
