# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T89: merge_map — the DB decides what exists, the Excel map decides what it means (PLAN R3-5).

Hand-built schemas only: this is the merge rule in isolation. The real producers (excel.convert,
introspect) meeting here is the M8 integration task.
"""

import copy

from nl2sql.schema_map import merge


def _column(name, type_="INT", description="", fk=None, values=None, nullable=True):
    return {
        "name": name,
        "type": type_,
        "description": description,
        "fk": fk,
        "values": values or {},
        "nullable": nullable,
    }


def _table(name, columns, **fields):
    table = {"name": name, "description": "", "module": "", "kind": "unknown", "columns": list(columns)}
    table.update(fields)
    return table


def _db():
    """A skeleton: structure without meaning, exactly what introspect returns."""
    return {
        "tables": [
            _table("STOK_HAREKET", [_column("HAREKET_YONU", "VARCHAR(1)"), _column("DEPO_ID", "INT", fk="DEPO.ID")]),
            _table("DEPO", [_column("ID", "INT", nullable=False)]),
        ]
    }


def _excel():
    """A map: meaning, in its own order, with things the database does not have."""
    return {
        "tables": [
            _table(
                "DEPO",
                [_column("ID", "VARCHAR(20)", description="Depo kodu", nullable=True)],
                description="Depolar.",
                module="Stok",
                keywords=["depo", "ambar"],
            ),
            _table(
                "STOK_HAREKET",
                [
                    _column("HAREKET_YONU", "NVARCHAR(1)", description="Giriş/çıkış kodu", values={"G": "Giriş", "C": "Çıkış"}),
                    _column("DEPO_ID", "INT", fk="DEPO.KOD"),
                    _column("KOLON_EXCEL", "INT", description="Yalnızca Excel'de"),
                ],
                description="Stok hareketleri.",
                module="Stok",
            ),
            _table("SHEET_TABLO", [_column("ID", "INT")], description="Yalnızca Excel'de."),
        ]
    }


def _merged():
    return merge.merge_map(_excel(), _db())


def _find(schema, name):
    return next(table for table in schema["tables"] if table["name"] == name)


def _col(table, name):
    return next(column for column in table["columns"] if column["name"] == name)


def test_db_decides_which_tables_exist():
    merged = _merged()
    assert [table["name"] for table in merged["tables"]] == ["STOK_HAREKET", "DEPO"]
    assert all(table["name"] != "SHEET_TABLO" for table in merged["tables"])


def test_db_order_is_the_merged_order():
    assert [table["name"] for table in _merged()["tables"]] == [
        table["name"] for table in _db()["tables"]
    ]


def test_db_decides_which_columns_exist():
    sthhar = _find(_merged(), "STOK_HAREKET")
    assert [column["name"] for column in sthhar["columns"]] == ["HAREKET_YONU", "DEPO_ID"]


def test_db_decides_types_and_nullability():
    merged = _merged()
    assert _col(_find(merged, "DEPO"), "ID")["type"] == "INT"
    assert _col(_find(merged, "DEPO"), "ID")["nullable"] is False
    assert _col(_find(merged, "STOK_HAREKET"), "HAREKET_YONU")["type"] == "VARCHAR(1)"


def test_db_decides_fks():
    merged = _merged()
    assert _col(_find(merged, "STOK_HAREKET"), "DEPO_ID")["fk"] == "DEPO.ID"


def test_excel_fk_missing_in_db_is_not_merged():
    db = _db()
    db["tables"][0]["columns"][1]["fk"] = None
    merged = merge.merge_map(_excel(), db)
    assert _col(_find(merged, "STOK_HAREKET"), "DEPO_ID")["fk"] is None


def test_excel_decides_table_meaning():
    merged = _merged()
    sthhar = _find(merged, "STOK_HAREKET")
    assert sthhar["description"] == "Stok hareketleri."
    assert sthhar["module"] == "Stok"
    assert sthhar["keywords"] == []
    depo = _find(merged, "DEPO")
    assert depo["description"] == "Depolar."
    assert depo["module"] == "Stok"
    assert depo["keywords"] == ["depo", "ambar"]


def test_excel_decides_column_meaning():
    gckod = _col(_find(_merged(), "STOK_HAREKET"), "HAREKET_YONU")
    assert gckod["description"] == "Giriş/çıkış kodu"
    assert gckod["values"] == {"G": "Giriş", "C": "Çıkış"}


def test_column_without_a_map_row_keeps_the_skeleton_meaning():
    column = _col(_find(_merged(), "STOK_HAREKET"), "DEPO_ID")
    assert column["description"] == ""
    assert column["values"] == {}


def test_skeleton_only_fields_survive():
    db = _db()
    db["tables"][0]["kind"] = "data"
    db["tables"][0]["columns"][0]["sample"] = ["G", "C"]
    merged = merge.merge_map(_excel(), db)
    sthhar = _find(merged, "STOK_HAREKET")
    assert sthhar["kind"] == "data"
    assert _col(sthhar, "HAREKET_YONU")["sample"] == ["G", "C"]


def test_names_are_matched_the_way_the_schema_names_them():
    excel = {
        "tables": [
            _table(
                "stok_hareket ",
                [_column(" hareket_yonu", description="Küçük harfli eşleme")],
                description="Eşleşti.",
            )
        ]
    }
    merged = merge.merge_map(excel, _db())
    sthhar = _find(merged, "STOK_HAREKET")
    assert sthhar["description"] == "Eşleşti."
    assert _col(sthhar, "HAREKET_YONU")["description"] == "Küçük harfli eşleme"


def test_inputs_are_not_modified():
    excel, db = _excel(), _db()
    before = (copy.deepcopy(excel), copy.deepcopy(db))
    merge.merge_map(excel, db)
    assert (excel, db) == before


def test_merged_values_are_copies():
    excel = _excel()
    merged = merge.merge_map(excel, _db())
    _col(_find(merged, "STOK_HAREKET"), "HAREKET_YONU")["values"]["X"] = "Test"
    _find(merged, "DEPO")["keywords"].append("test")
    assert _excel()["tables"][1]["columns"][0]["values"] == {"G": "Giriş", "C": "Çıkış"}
    assert _excel()["tables"][0]["keywords"] == ["depo", "ambar"]


def test_a_map_without_tables_keeps_the_skeleton():
    assert merge.merge_map({}, _db())["tables"] == copy.deepcopy(_db()["tables"])


def test_a_skeleton_without_tables_merges_to_nothing():
    assert merge.merge_map(_excel(), {}) == {"tables": []}
