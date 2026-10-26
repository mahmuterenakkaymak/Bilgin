"""T245: şablonu programın kendisi üretir (PLAN R6-12).

Şablon bir dosyadan okunmaz, her indirmede üretilir; bu yüzden testler üretilen baytları tekrar
openpyxl ile açar ve kullanıcının gerçekten gördüğüne bakar: sayfa sırası, başlıklar, açılır
listeler, Örnek blokları. İçe aktarımın (R6-14) okuyacağı sayfalar ile okumayacakları da burada
sabitlenir - bir sayfanın adı ya da başlığı değişirse iki taraf birden buradan haberdar olur.
"""

import io

import openpyxl
from openpyxl.utils import get_column_letter

from nl2sql import config
from nl2sql.policy import pii
from nl2sql.schema_map.template import (
    COLUMN_HEADERS,
    DATASET_HEADERS,
    RULE_HEADERS,
    SHEETS,
    TABLE_HEADERS,
    build_template,
    filled_example_workbook,
)

TABLE = "Satis.Fatura"

SKELETON = {
    "tables": [
        {
            "name": TABLE,
            "description": "",
            "module": "",
            "kind": "unknown",
            "columns": [
                {"name": "FaturaID", "type": "INT", "fk": None, "nullable": False},
                {"name": "CariKod", "type": "NVARCHAR(20)", "fk": "Satis.Cari.CariKod", "nullable": True},
            ],
        }
    ]
}


def book(data: bytes) -> openpyxl.Workbook:
    return openpyxl.load_workbook(io.BytesIO(data))


def grid(sheet) -> list[list[str]]:
    """Sayfanın metni: boş hücre boş metin, böylece bloklar karşılaştırılabilir."""
    return [["" if value is None else str(value) for value in row] for row in sheet.iter_rows(values_only=True)]


def headers_of(sheet) -> list[str]:
    return grid(sheet)[0]


def block(sheet, headers) -> list[list[str]]:
    """Başlık satırından sonraki dolu satırlar; boş satır bloğu bitirir."""
    rows = grid(sheet)
    wanted = list(headers)
    start = next(index for index, row in enumerate(rows) if row[: len(wanted)] == wanted)
    found: list[list[str]] = []
    for row in rows[start + 1 :]:
        if not any(row):
            break
        found.append(row[: len(wanted)])
    return found


def validations(sheet) -> dict[str, str]:
    """Doğrulama yapılan sütun harfi -> liste formülü."""
    return {
        str(rule.sqref).split(":")[0].rstrip("0123456789"): rule.formula1
        for rule in sheet.data_validations.dataValidation
    }


def column_of(headers, name: str) -> int:
    return list(headers).index(name)


def letter_of(headers, name: str) -> str:
    return get_column_letter(column_of(headers, name) + 1)


def test_the_sheets_are_there_in_the_order_the_user_reads_them():
    assert book(build_template()).sheetnames == [*SHEETS, "_bilgin"]


def test_the_hidden_sheet_carries_the_template_stamp():
    info = book(build_template())["_bilgin"]
    assert info.sheet_state == "hidden"
    assert info["A1"].value == "bilgin-sablon"
    assert info["B1"].value == config.TEMPLATE_VERSION


def test_every_data_sheet_opens_with_its_own_header_row():
    template = book(build_template())
    assert headers_of(template[SHEETS[1]]) == list(DATASET_HEADERS)
    assert headers_of(template[SHEETS[2]]) == list(TABLE_HEADERS)
    assert headers_of(template[SHEETS[3]]) == list(COLUMN_HEADERS)
    assert headers_of(template[SHEETS[4]]) == list(RULE_HEADERS)


def test_the_blank_template_holds_nothing_but_its_own_headers():
    template = book(build_template())
    for sheet, headers in (
        (template[SHEETS[1]], DATASET_HEADERS),
        (template[SHEETS[2]], TABLE_HEADERS),
        (template[SHEETS[3]], COLUMN_HEADERS),
        (template[SHEETS[4]], RULE_HEADERS),
    ):
        assert block(sheet, headers) == []


def test_the_dropdown_lists_are_the_projects_own_values():
    template = book(build_template())
    kolonlar = validations(template[SHEETS[3]])
    assert kolonlar[letter_of(COLUMN_HEADERS, "KİŞİSEL VERİ")] == '"' + ",".join(pii.CLASSES) + '"'
    assert kolonlar[letter_of(COLUMN_HEADERS, "KAPALI")] == '"E,H"'
    assert kolonlar[letter_of(COLUMN_HEADERS, "NULL")] == '"E,H"'
    assert kolonlar[letter_of(COLUMN_HEADERS, "TABLO")] == f"{SHEETS[2]}!$A$2:$A$201"
    assert validations(template[SHEETS[1]])[letter_of(DATASET_HEADERS, "BAĞLANTI")] == '"mssql,sqlite"'


def test_the_example_sheet_shows_one_finished_table_and_the_rule_that_uses_it():
    example = book(build_template())[SHEETS[5]]
    assert [row[0] for row in block(example, TABLE_HEADERS)] == [TABLE]

    columns = block(example, COLUMN_HEADERS)
    assert 6 <= len(columns) <= 8
    assert any(row[column_of(COLUMN_HEADERS, "REFERANS")] for row in columns)
    assert any(row[column_of(COLUMN_HEADERS, "DEĞERLER")] for row in columns)
    assert any(row[column_of(COLUMN_HEADERS, "KİŞİSEL VERİ")] == "person_name" for row in columns)
    assert any(row[column_of(COLUMN_HEADERS, "KAPALI")] == "E" for row in columns)

    rules = block(example, RULE_HEADERS)
    assert len(rules) == 1
    assert TABLE in rules[0][column_of(RULE_HEADERS, "TABLOLAR")]


def test_the_how_to_sheet_says_everything_a_distributor_asks():
    lines = [row[0] for row in grid(book(build_template())[SHEETS[0]]) if row[0]]
    assert 10 <= len(lines) <= 15
    text = " ".join(lines)
    for word in ("AÇIKLAMA", "KAPALI", "REFERANS", "DEĞERLER", "ANAHTAR KELİMELER", "NULL"):
        assert word in text
    for sheet in SHEETS[1:]:
        assert sheet in text


def test_a_skeleton_fills_the_structure_and_leaves_the_meanings_empty():
    template = book(build_template(SKELETON))
    assert block(template[SHEETS[2]], TABLE_HEADERS) == [[TABLE, "", "", ""]]

    columns = block(template[SHEETS[3]], COLUMN_HEADERS)
    assert [row[:3] for row in columns] == [
        [TABLE, "FaturaID", "INT"],
        [TABLE, "CariKod", "NVARCHAR(20)"],
    ]
    assert all(
        row[column_of(COLUMN_HEADERS, name)] == ""
        for row in columns
        for name in ("AÇIKLAMA", "DEĞERLER", "KİŞİSEL VERİ", "KAPALI")
    )
    assert [row[column_of(COLUMN_HEADERS, "NULL")] for row in columns] == ["H", "E"]
    assert columns[1][column_of(COLUMN_HEADERS, "REFERANS")] == "Satis.Cari.CariKod"


def test_the_filled_example_lands_in_the_real_sheets_under_its_own_name():
    template = book(filled_example_workbook("ornek_fatura"))
    assert block(template[SHEETS[1]], DATASET_HEADERS)[0][:3] == ["ornek_fatura", "ornek_fatura", "sqlite"]
    assert [row[0] for row in block(template[SHEETS[2]], TABLE_HEADERS)] == [TABLE]
    assert len(block(template[SHEETS[3]], COLUMN_HEADERS)) == 7
    assert block(template[SHEETS[4]], RULE_HEADERS)[0][0] == "fatura_tutari"


def test_the_reference_to_the_absent_table_is_dropped_and_the_rule_is_optional():
    template = book(filled_example_workbook("ornek_fatura", connection="mssql", with_rule=False))
    assert block(template[SHEETS[1]], DATASET_HEADERS)[0][2] == "mssql"
    assert all(row[column_of(COLUMN_HEADERS, "REFERANS")] == "" for row in block(template[SHEETS[3]], COLUMN_HEADERS))
    assert block(template[SHEETS[4]], RULE_HEADERS) == []
