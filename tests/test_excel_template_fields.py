"""T244: okuyucu şablonun ek alanlarını da taşır (PLAN R6-13).

Zincir gerçek parçalardan geçer: `read_workbook` -> `fallback_mapping` -> `convert`. Şablonun
KİŞİSEL VERİ / KAPALI / ANAHTAR KELİMELER başlıkları sözlükte yerini almadan eşlenmez; Run 3'ün
haritaları o başlıkları taşımadığı için dönüşümü ek alan anahtarı hiç görmez.
"""

from pathlib import Path

import openpyxl

from nl2sql.schema_map.excel import convert, fallback_mapping, read_workbook, sheet_rows

MESSY = str(Path(__file__).parent / "fixtures" / "map_customer_map.xlsx")

TABLOLAR = ["TABLO", "AÇIKLAMA", "ANAHTAR KELİMELER"]
KOLONLAR = ["TABLO", "KOLON", "TİP", "AÇIKLAMA", "KİŞİSEL VERİ", "KAPALI", "REFERANS", "NULL"]
RUN3 = ["TABLO", "KOLON", "TİP", "AÇIKLAMA", "REFERANS", "DEĞER", "NULL", "MODÜL"]


def template(kolonlar=(), tablolar=()) -> dict:
    """Şablonun iki şema sayfası: TABLOLAR sonra KOLONLAR, başlıkları 1. satırda."""
    return {"TABLOLAR": (TABLOLAR, list(tablolar)), "KOLONLAR": (KOLONLAR, list(kolonlar))}


def write(tmp_path, sheets: dict[str, tuple[list[str], list[list]]]) -> str:
    book = openpyxl.Workbook()
    book.remove(book.active)
    for name, (headers, rows) in sheets.items():
        sheet = book.create_sheet(name)
        sheet.append(headers)
        for row in rows:
            sheet.append(row)
    path = tmp_path / "sablon.xlsx"
    book.save(path)
    return str(path)


def convert_sheets(tmp_path, sheets: dict) -> dict:
    path = write(tmp_path, sheets)
    return convert(path, fallback_mapping(read_workbook(path)))


def mapped_fields(mapping: dict, sheet: int = 0) -> dict[str, list[str]]:
    """Sütun başlığı -> eşlendiği alanlar; bir başlık en fazla bir alan taşır."""
    return {
        entry["column"]: [
            name for name, value in entry.items() if name != "column" and value is not None
        ]
        for entry in mapping["sheets"][sheet]["columns"]
    }


def table(report: dict, name: str) -> dict:
    return next(item for item in report["schema"]["tables"] if item["name"] == name)


def column(report: dict, table_name: str, column_name: str) -> dict:
    return next(item for item in table(report, table_name)["columns"] if item["name"] == column_name)


def test_the_three_new_headers_map_through_the_fallback(tmp_path):
    path = write(tmp_path, template([["MUSTERI", "KOD", "varchar(12)", "Kod", "", "", "", ""]]))
    mapping = fallback_mapping(read_workbook(path))
    assert mapped_fields(mapping, 0)["ANAHTAR KELİMELER"] == ["keywords"]
    assert mapped_fields(mapping, 1)["KİŞİSEL VERİ"] == ["pii"]
    assert mapped_fields(mapping, 1)["KAPALI"] == ["deny"]
    assert mapped_fields(mapping, 1)["NULL"] == ["nullable"], "NULL yerinde duruyor"


def test_pii_class_and_closed_flag_land_on_the_column(tmp_path):
    report = convert_sheets(
        tmp_path,
        template(
            [
                ["MUSTERI", "ADSOYAD", "nvarchar(120)", "Ad soyad", "person_name", "", "", "H"],
                ["MUSTERI", "KIMLIK", "varchar(11)", "T.C. kimlik", "TCKN", "", "", "H"],
                ["MUSTERI", "SIFRE", "varchar(64)", "Parola", "", "E", "", "H"],
                ["MUSTERI", "KOD", "varchar(12)", "Kod", "", "H", "", "H"],
            ]
        ),
    )
    assert column(report, "MUSTERI", "ADSOYAD")["pii"] == "person_name"
    assert column(report, "MUSTERI", "KIMLIK")["pii"] == "tckn", "yazım büyükse de sınıf tanınır"
    assert column(report, "MUSTERI", "SIFRE")["pii"] is None
    assert column(report, "MUSTERI", "KOD")["pii"] is None
    assert column(report, "MUSTERI", "SIFRE")["deny"] is True
    assert column(report, "MUSTERI", "KOD")["deny"] is False
    assert report["skipped"] == []


def test_an_unknown_pii_class_stays_out_of_the_schema_with_a_note(tmp_path):
    report = convert_sheets(
        tmp_path,
        template([["MUSTERI", "TELEFON", "varchar(20)", "Telefon", "telefon", "", "", "H"]]),
    )
    assert column(report, "MUSTERI", "TELEFON")["pii"] is None
    assert [(item["sheet"], item["row"]) for item in report["skipped"]] == [("KOLONLAR", 2)]
    assert "telefon" in report["skipped"][0]["reason"]


def test_table_keywords_split_on_comma_and_semicolon(tmp_path):
    report = convert_sheets(
        tmp_path,
        template(
            [["MUSTERI", "KOD", "varchar(12)", "Kod", "", "", "", ""]],
            tablolar=[["MUSTERI", "Cari kartlar", "müşteri, cari; bayi "]],
        ),
    )
    assert table(report, "MUSTERI")["keywords"] == ["müşteri", "cari", "bayi"]
    assert table(report, "MUSTERI")["description"] == "Cari kartlar"
    assert report["skipped"] == []


def test_a_mapped_field_writes_its_key_even_when_the_cell_is_empty(tmp_path):
    report = convert_sheets(
        tmp_path,
        template(
            [["MUSTERI", "KOD", "varchar(12)", "Kod"]],
            tablolar=[["MUSTERI", "Cari kartlar", ""]],
        ),
    )
    assert table(report, "MUSTERI")["keywords"] == []
    assert column(report, "MUSTERI", "KOD")["pii"] is None
    assert column(report, "MUSTERI", "KOD")["deny"] is False


def test_a_run3_workbook_gains_no_new_keys(tmp_path):
    report = convert_sheets(
        tmp_path,
        {"KOLONLAR": (RUN3, [["TBLA", "KOD", "int", "Kartın kodu", "", "", "", "Stok"]])},
    )
    assert report["skipped"] == []
    assert [set(item) for item in report["schema"]["tables"]] == [
        {"name", "description", "module", "columns"}
    ]
    assert [
        set(item) for item in report["schema"]["tables"] for item in item["columns"]
    ] == [{"name", "type", "description", "fk", "values", "nullable"}]


def test_the_customer_fixture_converts_without_the_new_fields():
    report = convert(MESSY, fallback_mapping(read_workbook(MESSY)))
    assert report["schema"]["tables"], "fixture hâlâ şema üretiyor"
    for item in report["schema"]["tables"]:
        assert set(item) == {"name", "description", "module", "columns"}
        for column in item["columns"]:
            assert set(column) == {"name", "type", "description", "fk", "values", "nullable"}


def test_a_qualified_reference_survives(tmp_path):
    report = convert_sheets(
        tmp_path,
        template(
            [
                ["SATIS", "MUSTERI", "varchar(12)", "Cari", "", "", "Sales.Customers.CustomerID", "H"],
                ["SATIS", "GRUP", "varchar(12)", "Grup", "", "", "tblstgrup.grup_kodu", "H"],
                ["SATIS", "KAYSIZ", "varchar(12)", "Yalnız tablo", "", "", "TBLSTGRUP", "H"],
            ]
        ),
    )
    assert column(report, "SATIS", "MUSTERI")["fk"] == "SALES.CUSTOMERS.CUSTOMERID"
    assert column(report, "SATIS", "GRUP")["fk"] == "TBLSTGRUP.GRUP_KODU"
    assert column(report, "SATIS", "KAYSIZ")["fk"] is None
    assert [(item["sheet"], item["row"]) for item in report["skipped"]] == [("KOLONLAR", 4)]


def test_sheet_rows_numbers_are_the_numbers_the_user_sees(tmp_path):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "KOLONLAR"
    for row in (
        ["MÜŞTERİ ŞEMA HARİTASI"],
        [],
        KOLONLAR,
        ["MUSTERI", "KOD", "varchar(12)"],
        [],
        ["MUSTERI", "AD", "metin"],
    ):
        sheet.append(row)
    path = tmp_path / "harita.xlsx"
    book.save(path)

    header_row, headers, rows = sheet_rows(str(path), "KOLONLAR")
    assert header_row == 3
    assert headers == KOLONLAR
    assert [number for number, _ in rows] == [4, 5, 6], "boş satır da numarasını korur"
    assert rows[0][1][:3] == ("MUSTERI", "KOD", "varchar(12)")
    assert rows[2][1][:3] == ("MUSTERI", "AD", "metin")
    assert not any(rows[1][1])
