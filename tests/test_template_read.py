# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T246: okuyucu, yazarın ürettiğini eksiksiz geri okur (PLAN R6-14).

Testler gerçek şablon baytları üzerinden gider: boş şablon, dolu örnek, elle değiştirilmiş tek
bir hücre. Beklentiler arayüzün göstereceği şekildedir - sayılar, veri kümesi bloğu, bir hücre
kusurunun sayfa/satır/sütun adresi - çünkü içe aktarımın tek kanıtı kullanıcının okuduğu rapor.
"""

import io

import openpyxl
import pytest

from bilgin import config
from bilgin.schema_map.template import SHEETS, build_template, filled_example_workbook
from bilgin.schema_map.template_import import (
    TemplateError,
    is_bilgin_template,
    read_template,
)

CUSTOMER_MAP = config.ROOT / "tests" / "fixtures" / "map_customer_map.xlsx"

TABLE = "SATIS.FATURA"
COLUMNS = ["FATURAID", "FATURATARIHI", "CARIKOD", "FATURATIPI", "TUTAR", "YETKILIADI", "ICNOT"]
EMPTY_DATASET = {
    "name": "",
    "display_name": "",
    "connection": "mssql",
    "default_schema": None,
    "as_of": "",
}
EMPTY_COUNTS = {"tables": 0, "columns": 0, "pii": 0, "deny": 0, "references": 0, "rules": 0}


def write(tmp_path, data: bytes, name: str = "sablon.xlsx") -> str:
    path = tmp_path / name
    path.write_bytes(data)
    return str(path)


def edit_cell(tmp_path, data: bytes, sheet: str, row: int, header: str, value) -> str:
    """Bir hücreyi değiştirilmiş dosya: kullanıcının doldururken yaptığı düzeltme (ya da hatası)."""
    book = openpyxl.load_workbook(io.BytesIO(data))
    headers = [item.value for item in book[sheet][1]]
    book[sheet].cell(row=row, column=headers.index(header) + 1).value = value
    stream = io.BytesIO()
    book.save(stream)
    return write(tmp_path, stream.getvalue())


def example_read(tmp_path):
    return read_template(write(tmp_path, filled_example_workbook("deneme_kume")))


def example_columns(tmp_path) -> dict:
    return {c["name"]: c for c in example_read(tmp_path)["schema"]["tables"][0]["columns"]}


def test_the_blank_template_reads_as_an_empty_dataset(tmp_path):
    read = read_template(write(tmp_path, build_template()))
    assert read["template"] is True
    assert read["schema"]["tables"] == []
    assert read["rules"] == []
    assert read["errors"] == []
    assert read["counts"] == EMPTY_COUNTS
    assert read["dataset"] == EMPTY_DATASET


def test_the_stamp_separates_the_template_from_a_customer_map(tmp_path):
    assert is_bilgin_template(write(tmp_path, build_template())) is True
    assert is_bilgin_template(str(CUSTOMER_MAP)) is False


def test_the_filled_example_reads_as_one_complete_table(tmp_path):
    read = example_read(tmp_path)
    assert read["template"] is True
    assert read["errors"] == []
    tables = read["schema"]["tables"]
    assert [table["name"] for table in tables] == [TABLE]
    assert [column["name"] for column in tables[0]["columns"]] == COLUMNS
    assert tables[0]["module"] == "Satış"
    assert tables[0]["keywords"] == ["fatura", "satış belgesi"]
    assert read["counts"] == {"tables": 1, "columns": 7, "pii": 1, "deny": 1, "references": 0, "rules": 1}


def test_the_marks_of_the_example_land_on_their_columns(tmp_path):
    columns = example_columns(tmp_path)
    assert columns["YETKILIADI"]["pii"] == "person_name"
    assert columns["ICNOT"]["deny"] is True
    assert columns["FATURAID"]["pii"] is None
    assert columns["FATURAID"]["deny"] is False
    assert columns["FATURATIPI"]["values"] == {"S": "Satış", "I": "İade"}
    assert columns["TUTAR"]["type"] == "DECIMAL(18,2)"
    assert columns["FATURAID"]["nullable"] is False
    assert columns["YETKILIADI"]["nullable"] is True
    # Örneğin REFERANS'ı kopyalanmayan Satis.Cari'ya gittiği için şablonda zaten düşmüştü (R6-12).
    assert all(column["fk"] is None for column in columns.values())


def test_qualified_names_keep_their_dot(tmp_path):
    path = edit_cell(
        tmp_path,
        filled_example_workbook("deneme_kume"),
        SHEETS[3],
        4,
        "REFERANS",
        "Satis.Cari.CariKod",
    )
    read = read_template(path)
    assert read["errors"] == []
    assert read["schema"]["tables"][0]["name"] == TABLE
    assert [c["fk"] for c in read["schema"]["tables"][0]["columns"] if c["fk"]] == [
        "SATIS.CARI.CARIKOD"
    ]
    assert read["counts"]["references"] == 1


def test_the_dataset_block_is_the_row_the_template_carries(tmp_path):
    assert example_read(tmp_path)["dataset"] == {
        "name": "deneme_kume",
        "display_name": "deneme_kume",
        "connection": "sqlite",
        "default_schema": None,
        "as_of": "2026-10-01",
    }


def test_the_rule_row_becomes_a_rule(tmp_path):
    assert example_read(tmp_path)["rules"] == [
        {
            "id": "fatura_tutari",
            "term": "Fatura tutarı",
            "synonyms": ["ciro", "satış tutarı"],
            "definition": "Bir faturanın KDV hariç toplamı; iade faturaları eksi olarak sayılır.",
            "sql_hint": "SUM(Fatura.Tutar)",
            "tables": ["Satis.Fatura"],
            "markers": [],
            "synonyms_en": ["invoice amount", "revenue"],  # Updated automatically: T415/R8-13 changed this contract.
        }
    ]


def test_the_example_sheet_is_never_read(tmp_path):
    data = filled_example_workbook("deneme_kume")
    before = read_template(write(tmp_path, data, "once.xlsx"))
    book = openpyxl.load_workbook(io.BytesIO(data))
    for row in book[SHEETS[5]].iter_rows():
        for item in row:
            if isinstance(item.value, str) and "Satis.Fatura" in item.value:
                item.value = item.value.replace("Satis.Fatura", "Pazarlama.Siparis")
    stream = io.BytesIO()
    book.save(stream)
    assert read_template(write(tmp_path, stream.getvalue(), "sonra.xlsx")) == before


def test_a_map_without_a_dataset_sheet_is_refused():
    with pytest.raises(TemplateError) as record:
        read_template(str(CUSTOMER_MAP))
    assert str(record.value) == "Veri kümesi sayfası yok: Bilgin şablonunu kullanın."


def test_a_filled_row_without_a_type_is_reported_where_it_is(tmp_path):
    path = edit_cell(tmp_path, filled_example_workbook("deneme_kume"), SHEETS[3], 6, "TİP", None)
    assert read_template(path)["errors"] == [
        {
            "sheet": SHEETS[3],
            "row": 6,
            "column": "TİP",
            "message": "TİP boş; satır şemaya alınmadı.",
        }
    ]


def test_a_filled_row_without_a_table_is_reported_although_convert_inherits(tmp_path):
    path = edit_cell(tmp_path, filled_example_workbook("deneme_kume"), SHEETS[3], 5, "TABLO", None)
    assert read_template(path)["errors"] == [
        {
            "sheet": SHEETS[3],
            "row": 5,
            "column": "TABLO",
            "message": "TABLO boş; satır şemaya alınmadı.",
        }
    ]


def test_an_eh_cell_that_is_neither_e_nor_h_is_reported(tmp_path):
    path = edit_cell(tmp_path, filled_example_workbook("deneme_kume"), SHEETS[3], 8, "KAPALI", "Y")
    assert read_template(path)["errors"] == [
        {"sheet": SHEETS[3], "row": 8, "column": "KAPALI", "message": "KAPALI 'Y'; E ya da H olmalı."}
    ]


def test_an_unknown_personal_data_class_is_reported(tmp_path):
    path = edit_cell(
        tmp_path, filled_example_workbook("deneme_kume"), SHEETS[3], 7, "KİŞİSEL VERİ", "telefon"
    )
    read = read_template(path)
    # Notu convert tutuyor, o yüzden sütun adresi yok; sınıfın adı ve satırı mesajla birlikte gelir.
    assert [issue["column"] for issue in read["errors"]] == [None]
    assert read["errors"][0]["sheet"] == SHEETS[3]
    assert read["errors"][0]["row"] == 7
    assert "telefon" in read["errors"][0]["message"]
    assert read["counts"]["pii"] == 0
