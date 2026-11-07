# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T90: merge.diff_map — harita ile veritabanının çeliştiği her yer (PLAN R3-5).

İki üretici, bir şema: merge bu farkları atar, diff ise sayar. Testler elle kurulmuş şemalar
üzerinden diff'in kendisini ölçer; canlı SQLite yoklaması ve iki dosyanın yazılması CLI testidir.
"""

import copy
import json

from nl2sql.cli import main as cli
from nl2sql.schema_map import build, introspect, merge


def _column(name, type_="INT", fk=None):
    return {"name": name, "type": type_, "description": "", "fk": fk, "values": {}, "nullable": True}


def _table(name, columns):
    return {"name": name, "description": "", "module": "", "kind": "unknown", "columns": list(columns)}


def _base():
    return {
        "tables": [
            _table(
                "TBLA",
                [_column("ID", "INT"), _column("KOD", "VARCHAR(20)"), _column("AD", "VARCHAR(50)")],
            ),
            _table("TBLB", [_column("ID", "INT"), _column("TUTAR", "DECIMAL(18,2)")]),
            _table("TBLC", [_column("ID", "INT")]),
            _table("TBLD", [_column("ID", "INT")]),
        ]
    }


def _excel_of(base):
    """İki tabloyu silen, üç kolon ekleyen ve bir tipi değiştiren harita kopyası."""
    excel = copy.deepcopy(base)
    excel["tables"] = [table for table in excel["tables"] if table["name"] not in ("TBLB", "TBLC")]
    tbla = next(table for table in excel["tables"] if table["name"] == "TBLA")
    tbla["columns"] += [_column("X1"), _column("X2"), _column("X3")]
    next(column for column in tbla["columns"] if column["name"] == "KOD")["type"] = "NVARCHAR(30)"
    return excel


# ------------------------------------------------------------------ diff_map


def test_removed_tables_added_columns_and_a_type_change_are_reported_exactly():
    db = _base()
    report = merge.diff_map(_excel_of(db), db)

    assert set(report["db_only_tables"]) == {"TBLB", "TBLC"}
    assert report["excel_only_tables"] == []
    assert {(c["table"], c["column"]) for c in report["excel_only_columns"]} == {
        ("TBLA", "X1"),
        ("TBLA", "X2"),
        ("TBLA", "X3"),
    }
    assert report["db_only_columns"] == []
    assert {(m["table"], m["column"], m["excel"], m["db"]) for m in report["type_mismatches"]} == {
        ("TBLA", "KOD", "NVARCHAR(30)", "VARCHAR(20)")
    }
    assert report["fk_missing_in_db"] == []


def test_two_identical_schemas_have_no_fark():
    report = merge.diff_map(_base(), _base())
    assert all(not report[key] for key in report)


def test_fk_in_excel_missing_in_db_is_listed():
    db = {"tables": [_table("TBLA", [_column("DEPO_ID", "INT", fk=None)])]}
    excel = {"tables": [_table("TBLA", [_column("DEPO_ID", "INT", fk="TBLDEPO.ID")])]}
    report = merge.diff_map(excel, db)
    assert report["fk_missing_in_db"] == [{"table": "TBLA", "column": "DEPO_ID", "fk": "TBLDEPO.ID"}]


def test_a_reference_the_database_declares_is_not_a_fark():
    both = {"tables": [_table("TBLA", [_column("DEPO_ID", "INT", fk="TBLDEPO.ID")])]}
    assert merge.diff_map(both, both)["fk_missing_in_db"] == []


# ------------------------------------------------------------------ render_diff


def test_render_diff_lists_each_section_with_its_count():
    md = merge.render_diff(merge.diff_map(_excel_of(_base()), _base()))
    assert "Tablo yalnız veritabanında (2)" in md
    assert "TBLB" in md and "TBLC" in md
    assert "Kolon yalnız Excel'de (3)" in md
    assert "Tip uyuşmazlığı (1)" in md
    assert "TBLA.KOD: excel=NVARCHAR(30) db=VARCHAR(20)" in md


def test_render_diff_of_an_empty_report_says_fark_yok():
    assert merge.render_diff(merge.diff_map(_base(), _base())).strip().endswith("Fark yok.")


# ------------------------------------------------------------------ CLI


def test_cli_diff_map_introspects_the_db_and_writes_both_files(tmp_path, capsys):
    db = tmp_path / "test.db"
    build.build_db(db_path=db, sql_path=tmp_path / "build.sql")
    excel = tmp_path / "harita.json"
    excel.write_text(
        json.dumps({"tables": [_table("TBLYOK", [_column("ID", "INT")])]}), encoding="utf-8"
    )

    json_out = tmp_path / "diff.json"
    md_out = tmp_path / "diff.md"
    assert cli.diff_map(excel, db_path=db, json_out=json_out, md_out=md_out) == 0

    assert json_out.is_file() and md_out.is_file()
    assert "TBLYOK" in json.loads(json_out.read_text(encoding="utf-8"))["excel_only_tables"]
    out = capsys.readouterr().out
    assert "Tablo yalnız Excel'de: 1" in out
    assert str(json_out) in out and str(md_out) in out


def test_cli_diff_map_says_fark_yok_when_the_two_agree(tmp_path, capsys):
    db = tmp_path / "test.db"
    build.build_db(db_path=db, sql_path=tmp_path / "build.sql")
    skeleton = tmp_path / "iskelet.json"
    skeleton.write_text(json.dumps(introspect.sqlite_skeleton(db)), encoding="utf-8")

    json_out = tmp_path / "diff.json"
    md_out = tmp_path / "diff.md"
    assert cli.diff_map(skeleton, db_schema=skeleton, json_out=json_out, md_out=md_out) == 0

    assert "Fark yok." in capsys.readouterr().out
    assert json_out.is_file() and md_out.is_file()


def test_cli_diff_map_without_a_readable_excel_exits_2(tmp_path, capsys):
    assert cli.diff_map(tmp_path / "yok.json", db_schema=tmp_path / "iskelet.json") == 2
    assert "Şema dosyası okunamadı" in capsys.readouterr().out


def test_main_routes_diff_map(monkeypatch):
    seen = {}

    def capture(excel_path, **kwargs):
        seen["excel"] = excel_path
        seen.update(kwargs)
        return 0

    monkeypatch.setattr(cli, "diff_map", capture)
    assert cli.main(["diff-map", "--excel", "s.json", "--db-schema", "iskelet.json"]) == 0
    assert seen["excel"] == "s.json" and seen["db_schema"] == "iskelet.json"

    seen.clear()
    assert cli.main(["diff-map", "--excel", "s.json", "--db"]) == 0
    assert seen["db_schema"] is None
