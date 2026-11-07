# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T248: doğrulama, yüklemenin uygulanmasını engelleyen kusurları raporlar (PLAN R6-15).

Testler yazarın dolu örneğini openpyxl ile bozar - tek hücre, tek satır - ve bekler ki kusur
kullanıcıya nerede olduğunu söylesin: hangi sayfa, hangi sütun başlığı. Okumanın kendi hücre
kusurları (TİP boş, KAPALI 'Y', bilinmeyen sınıf) adresleriyle birlikte geçer; şablonun bütünlük
kuralları - bağlı sayfalar, benzersiz adlar, çözülen referanslar, veri kümesi satırı, kurallar ve
canlı iskeletin farkı - buradan eklenir.
"""

import io

import openpyxl
import pytest

from nl2sql import datasets
from nl2sql.schema_map.template import SHEETS, filled_example_workbook
from nl2sql.schema_map.template_import import read_template, validate

DATASET_SHEET, TABLE_SHEET, COLUMN_SHEET, RULE_SHEET = SHEETS[1], SHEETS[2], SHEETS[3], SHEETS[4]
TABLE = "SATIS.FATURA"
NAME = "deneme_kume"
NO_DB = {
    "checked": False,
    "missing_in_db": [],
    "only_in_db": [],
    "message": "Canlı veritabanı bağlantısı yok; karşılaştırma yapılmadı.",
}


def example() -> bytes:
    return filled_example_workbook(NAME)


def write(tmp_path, data: bytes) -> str:
    path = tmp_path / "sablon.xlsx"
    path.write_bytes(data)
    return str(path)


def save(tmp_path, book) -> str:
    stream = io.BytesIO()
    book.save(stream)
    return write(tmp_path, stream.getvalue())


def fill(tmp_path, data: bytes, cells) -> str:
    """[(sayfa, satır, başlık, değer), ...] hücrelerini yazan dosya: kullanıcının düzeltmesi."""
    book = openpyxl.load_workbook(io.BytesIO(data))
    for sheet, row, header, value in cells:
        headers = [item.value for item in book[sheet][1]]
        book[sheet].cell(row=row, column=headers.index(header) + 1).value = value
    return save(tmp_path, book)


def drop_row(tmp_path, data: bytes, sheet: str, row: int) -> str:
    """Bir satırın her hücresini boşaltan dosya: Excel'de satırı silmek budur."""
    book = openpyxl.load_workbook(io.BytesIO(data))
    for column in range(1, len([item.value for item in book[sheet][1]]) + 1):
        book[sheet].cell(row=row, column=column).value = None
    return save(tmp_path, book)


def copy_row(tmp_path, data: bytes, sheet: str, source: int, target: int) -> str:
    """Bir satırın kopyasını boş bir satıra yazan dosya: en sık yapılan ikinci doldurma hatası."""
    book = openpyxl.load_workbook(io.BytesIO(data))
    for column in range(1, len([item.value for item in book[sheet][1]]) + 1):
        book[sheet].cell(row=target, column=column).value = book[sheet].cell(
            row=source, column=column
        ).value
    return save(tmp_path, book)


def read_of(tmp_path):
    return read_template(write(tmp_path, example()))


def errors_of(tmp_path, path: str) -> list[dict]:
    errors, _warnings, _check = validate(read_template(path))
    return errors


def skeleton_of(read, without=()) -> dict:
    """Okunan şemanın veritabanı iskeleti: aynı adlar ve tipler, seçilen kolonlar yok."""
    return {
        "tables": [
            {
                "name": table["name"],
                "columns": [
                    column for column in table["columns"] if column["name"] not in without
                ],
            }
            for table in read["schema"]["tables"]
        ]
    }


def test_the_filled_example_needs_nothing(tmp_path):
    errors, warnings, db_check = validate(read_of(tmp_path))
    assert errors == []
    assert warnings == []
    assert db_check == NO_DB


def test_a_row_without_a_type_keeps_its_cell_address(tmp_path):
    path = fill(tmp_path, example(), [(COLUMN_SHEET, 6, "TİP", None)])
    assert errors_of(tmp_path, path) == [
        {
            "sheet": COLUMN_SHEET,
            "row": 6,
            "column": "TİP",
            "message": "TİP boş; satır şemaya alınmadı.",
        }
    ]


def test_a_column_whose_table_the_tables_sheet_never_saw(tmp_path):
    path = drop_row(tmp_path, example(), TABLE_SHEET, 2)
    assert errors_of(tmp_path, path) == [
        {
            "sheet": COLUMN_SHEET,
            "row": None,
            "column": "TABLO",
            "message": f"'{TABLE}' Tablolar sayfasında yok; her tablonun orada bir satırı olmalı.",
        }
    ]


def test_a_repeated_column_is_reported_where_it_was_written(tmp_path):
    errors = errors_of(tmp_path, copy_row(tmp_path, example(), COLUMN_SHEET, 2, 9))
    assert len(errors) == 1
    assert errors[0]["sheet"] == COLUMN_SHEET
    assert errors[0]["row"] == 9
    assert "tekrar" in errors[0]["message"]
    assert "FATURAID" in errors[0]["message"]


def test_an_unknown_personal_data_class_keeps_its_cell_address(tmp_path):
    errors = errors_of(
        tmp_path, fill(tmp_path, example(), [(COLUMN_SHEET, 7, "KİŞİSEL VERİ", "telefon")])
    )
    assert len(errors) == 1
    assert (errors[0]["sheet"], errors[0]["row"]) == (COLUMN_SHEET, 7)
    assert "telefon" in errors[0]["message"]


def test_an_eh_cell_that_is_neither_e_nor_h(tmp_path):
    assert errors_of(tmp_path, fill(tmp_path, example(), [(COLUMN_SHEET, 8, "KAPALI", "Y")])) == [
        {
            "sheet": COLUMN_SHEET,
            "row": 8,
            "column": "KAPALI",
            "message": "KAPALI 'Y'; E ya da H olmalı.",
        }
    ]


def test_a_reference_to_a_column_the_workbook_does_not_have(tmp_path):
    path = fill(tmp_path, example(), [(COLUMN_SHEET, 4, "REFERANS", "Satis.Cari.CariKod")])
    assert errors_of(tmp_path, path) == [
        {
            "sheet": COLUMN_SHEET,
            "row": None,
            "column": "REFERANS",
            "message": "REFERANS 'SATIS.CARI.CARIKOD' şablonda yok; hedef kolon Kolonlar sayfasında olmalı.",
        }
    ]


def test_a_reference_the_workbook_itself_answers(tmp_path):
    path = fill(tmp_path, example(), [(COLUMN_SHEET, 4, "REFERANS", "Satis.Fatura.FaturaID")])
    assert errors_of(tmp_path, path) == []


def test_a_dataset_without_a_name(tmp_path):
    assert errors_of(tmp_path, fill(tmp_path, example(), [(DATASET_SHEET, 2, "AD", None)])) == [
        {"sheet": DATASET_SHEET, "row": None, "column": "AD", "message": "AD boş; veri kümesinin klasör adını yazın."}
    ]


def test_a_name_the_folder_rules_refuse(tmp_path):
    errors = errors_of(tmp_path, fill(tmp_path, example(), [(DATASET_SHEET, 2, "AD", "Deneme-Kume")]))
    assert len(errors) == 1
    assert (errors[0]["sheet"], errors[0]["column"]) == (DATASET_SHEET, "AD")
    assert "Deneme-Kume" in errors[0]["message"]


@pytest.mark.parametrize("name", ["synthetic_erp", "wwi_real"])
def test_a_name_that_already_owns_a_dataset_folder(tmp_path, name):
    assert datasets.name_taken(name) is True
    errors = errors_of(tmp_path, fill(tmp_path, example(), [(DATASET_SHEET, 2, "AD", name)]))
    assert len(errors) == 1
    assert errors[0]["message"] == f"Bu ad zaten bir veri kümesi: {name}."


def test_a_connection_outside_the_two_dialects(tmp_path):
    assert errors_of(
        tmp_path, fill(tmp_path, example(), [(DATASET_SHEET, 2, "BAĞLANTI", "oracle")])
    ) == [
        {
            "sheet": DATASET_SHEET,
            "row": None,
            "column": "BAĞLANTI",
            "message": "BAĞLANTI 'oracle'; mssql ya da sqlite olmalı.",
        }
    ]


def test_a_data_date_that_is_not_iso(tmp_path):
    errors = errors_of(
        tmp_path, fill(tmp_path, example(), [(DATASET_SHEET, 2, "VERİ TARİHİ", "1 Ekim 2026")])
    )
    assert len(errors) == 1
    assert (errors[0]["sheet"], errors[0]["column"]) == (DATASET_SHEET, "VERİ TARİHİ")
    assert "1 Ekim 2026" in errors[0]["message"]


def test_a_rule_naming_a_table_the_schema_does_not_have(tmp_path):
    path = fill(tmp_path, example(), [(RULE_SHEET, 2, "TABLOLAR", "Satis.Siparis")])
    assert errors_of(tmp_path, path) == [
        {
            "sheet": RULE_SHEET,
            "row": None,
            "column": "TABLOLAR",
            "message": "Kural 'fatura_tutari': Şemada olmayan tablo: Satis.Siparis.",
        }
    ]


def test_descriptions_left_empty_warn_without_blocking(tmp_path):
    path = fill(
        tmp_path,
        example(),
        [
            (TABLE_SHEET, 2, "AÇIKLAMA", None),
            (COLUMN_SHEET, 2, "AÇIKLAMA", None),
            (COLUMN_SHEET, 3, "AÇIKLAMA", None),
        ],
    )
    _errors, warnings, _check = validate(read_template(path))
    assert len(warnings) == 2
    assert warnings[0] == {
        "sheet": TABLE_SHEET,
        "row": None,
        "column": "AÇIKLAMA",
        "message": f"{TABLE} açıklamasız; model tabloyu yalnız oraya yazılan metinden bilir.",
    }
    assert (warnings[1]["sheet"], warnings[1]["column"]) == (COLUMN_SHEET, "AÇIKLAMA")
    assert warnings[1]["message"] == (
        f"2 kolon açıklamasız: {TABLE}.FATURAID, {TABLE}.FATURATARIHI"
    )


def test_a_column_the_database_does_not_have_blocks_the_upload(tmp_path):
    read = read_of(tmp_path)
    errors, warnings, db_check = validate(read, skeleton_of(read, without=("TUTAR",)))
    assert db_check == {
        "checked": True,
        "missing_in_db": [f"{TABLE}.TUTAR"],
        "only_in_db": [],
        "message": None,
    }
    assert errors == [
        {
            "sheet": COLUMN_SHEET,
            "row": None,
            "column": "KOLON",
            "message": f"Kolon veritabanında yok: {TABLE}.TUTAR.",
        }
    ]
    assert warnings == []


def test_what_only_the_database_has_is_a_warning(tmp_path):
    read = read_of(tmp_path)
    skeleton = skeleton_of(read)
    skeleton["tables"][0]["columns"].append({"name": "Vadeli", "type": "INT"})
    skeleton["tables"].append({"name": "Satis.Cari", "columns": [{"name": "CariKod", "type": "NVARCHAR(20)"}]})
    errors, warnings, db_check = validate(read, skeleton)
    assert errors == []
    assert db_check["checked"] is True
    assert db_check["missing_in_db"] == []
    assert db_check["only_in_db"] == ["Satis.Cari", f"{TABLE}.Vadeli"]
    assert [warning["message"] for warning in warnings] == [
        "Tablo yalnız veritabanında: Satis.Cari.",
        f"Kolon yalnız veritabanında: {TABLE}.Vadeli.",
    ]
