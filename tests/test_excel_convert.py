# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T82: satırların koddan şemaya dönüşümü (PLAN R3-2) - tüm satırlar, LLM satırları hiç görmez.

Eşleme elle kurulmaz: gerçek okuyucu (T79) + gerçek sözlük eşlemesi (T80) convert'e verilir,
böylece test zincirin kendisini yoklar. Sorunlu satırlar sheet + 1-tabanlı satır numarasıyla
raporda arandığı için satır numaraları burada açıkça yazılıdır.
"""

import openpyxl
import pytest

from bilgin import config
from bilgin.schema_map.excel import convert, fallback_mapping, read_workbook

HEADERS = ["TABLO", "KOLON", "TİP", "AÇIKLAMA", "REFERANS", "DEĞER", "NULL", "MODÜL"]


def row(table="", column="", tip="", aciklama="", referans="", deger="", bos="", modul=""):
    return [table, column, tip, aciklama, referans, deger, bos, modul]


def workbook(tmp_path, sheets: dict[str, list[list]], title: bool = False) -> tuple[str, dict]:
    """Geçici kitap + ondan üretilmiş eşleme; title=True başlığı 3. satıra taşır (üstte başlık ve boş satır)."""
    book = openpyxl.Workbook()
    book.remove(book.active)
    for name, rows in sheets.items():
        sheet = book.create_sheet(name)
        if title:
            sheet.append(["MÜŞTERİ ŞEMA HARİTASI"])
            sheet.append([])
        sheet.append(HEADERS)
        for item in rows:
            sheet.append(item)
    path = tmp_path / "harita.xlsx"
    book.save(path)
    preview = read_workbook(str(path))
    return str(path), fallback_mapping(preview)


def convert_map(tmp_path, sheets: dict[str, list[list]], title: bool = False) -> dict:
    path, mapping = workbook(tmp_path, sheets, title)
    return convert(path, mapping)


def tables(report: dict) -> list[str]:
    return [item["name"] for item in report["schema"]["tables"]]


def table(report: dict, name: str) -> dict:
    return next(item for item in report["schema"]["tables"] if item["name"] == name)


def column(report: dict, table_name: str, column_name: str) -> dict:
    return next(item for item in table(report, table_name)["columns"] if item["name"] == column_name)


def column_names(report: dict, table_name: str) -> list[str]:
    return [item["name"] for item in table(report, table_name)["columns"]]


def test_report_shape_and_column_defaults(tmp_path):
    report = convert_map(
        tmp_path, {"KOLONLAR": [row("TBLA", "KOD", "varchar(12)"), row("TBLA", "AD", "metin")]}
    )
    assert set(report) == {"schema", "tables", "columns", "skipped"}
    assert (report["tables"], report["columns"], report["skipped"]) == (1, 2, [])
    assert report["schema"]["tables"] == [
        {
            "name": "TBLA",
            "description": "",
            "module": "",
            "columns": [
                {
                    "name": "KOD",
                    "type": "VARCHAR(12)",
                    "description": "",
                    "fk": None,
                    "values": {},
                    "nullable": True,
                },
                {
                    "name": "AD",
                    "type": "NVARCHAR(255)",
                    "description": "",
                    "fk": None,
                    "values": {},
                    "nullable": True,
                },
            ],
        }
    ]


def test_tables_group_in_first_appearance_order(tmp_path):
    report = convert_map(
        tmp_path,
        {"K": [row("TBLB", "B1"), row("TBLA", "A1"), row("TBLB", "B2"), row("TBLA", "A2")]},
    )
    assert tables(report) == ["TBLB", "TBLA"]
    assert column_names(report, "TBLB") == ["B1", "B2"]
    assert column_names(report, "TBLA") == ["A1", "A2"]
    assert (report["tables"], report["columns"]) == (2, 4)


def test_names_follow_the_upper_case_convention_of_the_schema(tmp_path):
    report = convert_map(tmp_path, {"K": [row("tbla", "kod", "int"), row("TBLA", "AD", "metin")]})
    assert tables(report) == ["TBLA"]
    assert column_names(report, "TBLA") == ["KOD", "AD"]


def test_every_row_converts_not_only_the_preview(tmp_path):
    rows = [row("TBLA", f"KOD_{number}", "int") for number in range(config.EXCEL_PREVIEW_ROWS + 5)]
    report = convert_map(tmp_path, {"K": rows})
    assert report["columns"] == len(rows) > config.EXCEL_PREVIEW_ROWS
    assert len(column_names(report, "TBLA")) == len(rows)


def test_row_without_a_table_is_skipped_with_sheet_and_row(tmp_path):
    report = convert_map(
        tmp_path,
        {"KOLONLAR": [row(column="KOD", tip="int"), row("TBLA", "AD", "int")]},
        title=True,
    )
    assert [item["sheet"] for item in report["skipped"]] == ["KOLONLAR"]
    assert report["skipped"][0]["row"] == 4, "başlık 3. satırda; ilk veri satırı 4'tür"
    assert "TABLO" in report["skipped"][0]["reason"]
    assert column_names(report, "TBLA") == ["AD"]


def test_blank_table_cell_repeats_the_previous_table(tmp_path):
    report = convert_map(
        tmp_path, {"K": [row("TBLA", "K1"), row("", "K2"), row("TBLB", "K3"), row("", "K4")]}
    )
    assert column_names(report, "TBLA") == ["K1", "K2"]
    assert column_names(report, "TBLB") == ["K3", "K4"]
    assert report["skipped"] == []


def test_blank_rows_are_padding_not_skipped_rows(tmp_path):
    report = convert_map(
        tmp_path, {"K": [row("TBLA", "K1"), row(), row("TBLA", "K2"), row()]}
    )
    assert column_names(report, "TBLA") == ["K1", "K2"]
    assert report["skipped"] == []


def test_values_cell_parsed(tmp_path):
    report = convert_map(
        tmp_path,
        {"K": [row("TBLA", "GCKOD", "varchar(1)", "Giriş/çıkış", "", "G=Giriş; C=Çıkış")]},
    )
    assert column(report, "TBLA", "GCKOD")["values"] == {"G": "Giriş", "C": "Çıkış"}
    assert report["skipped"] == []


def test_invalid_values_cell_keeps_the_column_and_reports_the_row(tmp_path):
    report = convert_map(
        tmp_path,
        {"K": [row("TBLA", "K1"), row("TBLA", "GCKOD", "varchar(1)", "", "", "giriş ya da çıkış")]},
    )
    assert column(report, "TBLA", "GCKOD")["values"] == {}
    assert [(item["sheet"], item["row"]) for item in report["skipped"]] == [("K", 3)]
    assert "DEĞER" in report["skipped"][0]["reason"]


@pytest.mark.parametrize(
    "cell, expected",
    [
        ("sayı", "INT"),
        ("SAYI", "INT"),
        ("Tam Sayı", "INT"),
        ("integer", "INT"),
        ("int", "INT"),
        ("para", "DECIMAL(18,2)"),
        ("PARA", "DECIMAL(18,2)"),
        ("tutar", "DECIMAL(18,2)"),
        ("metin", "NVARCHAR(255)"),
        ("varchar", "NVARCHAR(255)"),
        ("tarih", "DATE"),
        ("DATE", "DATE"),
        ("varchar(20)", "VARCHAR(20)"),
        ("VARCHAR(20)", "VARCHAR(20)"),
        ("nvarchar(60)", "NVARCHAR(60)"),
        ("decimal(18,3)", "DECIMAL(18,3)"),
        ("DECIMAL(18, 2)", "DECIMAL(18,2)"),
        ("", "NVARCHAR(255)"),
    ],
)
def test_data_type_normalised_to_the_names_the_schema_uses(tmp_path, cell, expected):
    report = convert_map(tmp_path, {"K": [row("TBLA", "KOD", cell)]})
    assert column(report, "TBLA", "KOD")["type"] == expected
    assert report["skipped"] == []


def test_unknown_type_falls_back_to_text_and_reports_the_row(tmp_path):
    report = convert_map(tmp_path, {"K": [row("TBLA", "KOD", "garip tip")]})
    assert column(report, "TBLA", "KOD")["type"] == "NVARCHAR(255)"
    assert report["skipped"][0]["row"] == 2
    assert "garip tip" in report["skipped"][0]["reason"]


@pytest.mark.parametrize(
    "cell, expected",
    [
        ("", True),
        ("E", True),
        ("evet", True),
        ("boş", True),
        ("NULL", True),
        ("1", True),
        ("H", False),
        ("hayır", False),
        ("Dolu", False),
        ("NOT NULL", False),
        ("0", False),
        ("ş", True),
    ],
)
def test_nullable_reads_the_common_spellings_and_defaults_to_true(tmp_path, cell, expected):
    report = convert_map(tmp_path, {"K": [row("TBLA", "KOD", "int", "", "", "", cell)]})
    assert column(report, "TBLA", "KOD")["nullable"] is expected


def test_fk_target_must_be_table_dot_column(tmp_path):
    report = convert_map(
        tmp_path,
        {
            "K": [
                row("TBLA", "GRUP", "varchar(12)", "", "tblstgrup.grup_kodu"),
                row("TBLA", "KAYSIZ", "varchar(12)", "", "TBLSTGRUP"),
                row("TBLA", "FAZLA", "varchar(12)", "", "dbo.TBL.COL"),
                row("TBLA", "REFERANSIZ", "varchar(12)"),
            ]
        },
    )
    assert column(report, "TBLA", "GRUP")["fk"] == "TBLSTGRUP.GRUP_KODU"
    assert column(report, "TBLA", "KAYSIZ")["fk"] is None
    assert column(report, "TBLA", "FAZLA")["fk"] is None
    assert column(report, "TBLA", "REFERANSIZ")["fk"] is None
    assert [(item["row"], "TABLE.COL" in item["reason"]) for item in report["skipped"]] == [
        (3, True),
        (4, True),
    ]


def test_row_without_a_column_describes_the_table(tmp_path):
    report = convert_map(
        tmp_path,
        {
            "TABLOLAR": [
                row("TBLA", "", "", "Stok kartları.", modul="Stok"),
                row("TBLA", "KOD", "int", "Kartın kodu.", modul="Stok"),
            ],
            "KOLONLAR": [row("TBLB", "K1", "int", "", "", "", "", "Cari")],
        },
    )
    assert table(report, "TBLA")["description"] == "Stok kartları."
    assert table(report, "TBLA")["module"] == "Stok"
    assert column(report, "TBLA", "KOD")["description"] == "Kartın kodu."
    assert table(report, "TBLB")["module"] == "Cari"
    assert table(report, "TBLB")["description"] == ""
    assert (report["tables"], report["columns"]) == (2, 2)


def test_duplicate_column_is_skipped_with_a_reason(tmp_path):
    report = convert_map(
        tmp_path, {"K": [row("TBLA", "KOD", "int"), row("TBLA", "kod", "varchar(10)")]}
    )
    assert column_names(report, "TBLA") == ["KOD"]
    assert column(report, "TBLA", "KOD")["type"] == "INT"
    assert report["skipped"][0]["row"] == 3
    assert "tekrar" in report["skipped"][0]["reason"]


def test_mapping_sheet_missing_from_the_workbook_is_dropped(tmp_path, capsys):
    path, mapping = workbook(tmp_path, {"K": [row("TBLA", "KOD", "int")]})
    mapping["sheets"].append({"sheet": "YOK", "header_row": 1, "columns": []})
    report = convert(path, mapping)
    assert tables(report) == ["TBLA"]
    assert "YOK" in capsys.readouterr().out
