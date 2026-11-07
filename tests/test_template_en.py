# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T415: şablonun İngilizce hâli (PLAN R8-12).

Şablonun her dili `LABELS` sözlüğünden çıkar; test İngilizce dosyayı openpyxl ile açıp kullanıcının
gerçekten gördüğüne bakar: sayfa adları, başlıklar, açılır listeler, Örnek blokları ve anlatım
satırları. Türkçe tarafın bugünkü hâli de burada sabitlenir - tek farkın yeni kural sütunu ile
`_bilgin`'in dil satırı olduğu oradan okunur.
"""

import io

import openpyxl
from openpyxl.utils import get_column_letter

from bilgin import config
from bilgin.i18n.detect import TURKISH_LETTERS
from bilgin.i18n.scan import user_literals
from bilgin.policy import pii
from bilgin.schema_map.template import LABELS, build_template, filled_example_workbook

EN_SHEETS = ("How to fill in", "Dataset", "Tables", "Columns", "Business rules", "Example")
EN_DATASET_HEADERS = ("NAME", "DISPLAY NAME", "CONNECTION", "DEFAULT SCHEMA", "DATA DATE")
EN_TABLE_HEADERS = ("TABLE", "MODULE", "DESCRIPTION", "KEYWORDS")
EN_COLUMN_HEADERS = (
    "TABLE",
    "COLUMN",
    "TYPE",
    "DESCRIPTION",
    "VALUES",
    "PERSONAL DATA",
    "CLOSED",
    "REFERENCE",
    "NULL",
)
EN_RULE_HEADERS = ("ID", "TERM", "SYNONYMS", "DEFINITION", "SQL HINT", "TABLES", "SYNONYMS (EN)")
EN_TABLE = "Sales.Invoice"

# Türkçe şablonun T415 öncesindeki hâli: tek başlığın bile kaymadığı buradan okunur.
TR_SHEETS = ("Nasıl doldurulur", "Veri kümesi", "Tablolar", "Kolonlar", "İş kuralları", "Örnek")
TR_DATASET_HEADERS = ("AD", "GÖRÜNEN AD", "BAĞLANTI", "VARSAYILAN ŞEMA", "VERİ TARİHİ")
TR_TABLE_HEADERS = ("TABLO", "MODÜL", "AÇIKLAMA", "ANAHTAR KELİMELER")
TR_COLUMN_HEADERS = (
    "TABLO",
    "KOLON",
    "TİP",
    "AÇIKLAMA",
    "DEĞERLER",
    "KİŞİSEL VERİ",
    "KAPALI",
    "REFERANS",
    "NULL",
)
TR_RULE_HEADERS_BEFORE = ("KİMLİK", "TERİM", "EŞ ANLAMLILAR", "TANIM", "SQL İPUCU", "TABLOLAR")
TR_EXAMPLE_RULE_BEFORE = (
    "fatura_tutari",
    "Fatura tutarı",
    "ciro, satış tutarı",
    "Bir faturanın KDV hariç toplamı; iade faturaları eksi olarak sayılır.",
    "SUM(Fatura.Tutar)",
    "Satis.Fatura",
)

SKELETON = {
    "tables": [
        {
            "name": EN_TABLE,
            "columns": [
                {"name": "InvoiceID", "type": "INT", "fk": None, "nullable": False},
                {
                    "name": "CustomerCode",
                    "type": "NVARCHAR(20)",
                    "fk": "Sales.Customer.CustomerCode",
                    "nullable": True,
                },
            ],
        }
    ]
}


def book(data: bytes) -> openpyxl.Workbook:
    return openpyxl.load_workbook(io.BytesIO(data))


def grid(sheet) -> list[list[str]]:
    """Sayfanın metni: boş hücre boş metin, böylece bloklar karşılaştırılabilir."""
    return [
        ["" if value is None else str(value) for value in row]
        for row in sheet.iter_rows(values_only=True)
    ]


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


def letter_of(headers, name: str) -> str:
    return get_column_letter(list(headers).index(name) + 1)


def widths_of(sheet, count: int) -> list[float]:
    return [sheet.column_dimensions[get_column_letter(index)].width for index in range(1, count + 1)]


def cells(workbook) -> list[str]:
    return [
        str(value)
        for sheet in workbook.worksheets
        for row in sheet.iter_rows(values_only=True)
        for value in row
        if value is not None
    ]


def english() -> openpyxl.Workbook:
    return book(build_template(lang="en"))


def test_both_languages_are_there_and_have_the_same_shape():
    assert set(LABELS) == {"tr", "en"}
    assert set(LABELS["tr"]) == set(LABELS["en"])
    for key in ("dataset_headers", "table_headers", "column_headers", "rule_headers"):
        assert len(LABELS["tr"][key]) == len(LABELS["en"][key]), key
    assert len(LABELS["tr"]["how_to"]) == len(LABELS["en"]["how_to"])
    assert len(LABELS["tr"]["example_columns"]) == len(LABELS["en"]["example_columns"])


def test_the_english_workbook_has_the_english_sheet_names_in_the_reading_order():
    assert english().sheetnames == [*EN_SHEETS, "_bilgin"]
    assert book(build_template()).sheetnames == [*TR_SHEETS, "_bilgin"]


def test_every_english_sheet_opens_with_the_headers_of_the_brief():
    template = english()
    assert headers_of(template[EN_SHEETS[1]]) == list(EN_DATASET_HEADERS)
    assert headers_of(template[EN_SHEETS[2]]) == list(EN_TABLE_HEADERS)
    assert headers_of(template[EN_SHEETS[3]]) == list(EN_COLUMN_HEADERS)
    assert headers_of(template[EN_SHEETS[4]]) == list(EN_RULE_HEADERS)


def test_the_english_dropdown_lists_are_yes_no_and_point_at_the_english_tables():
    columns = validations(english()[EN_SHEETS[3]])
    assert columns[letter_of(EN_COLUMN_HEADERS, "CLOSED")] == '"Y,N"'
    assert columns[letter_of(EN_COLUMN_HEADERS, "NULL")] == '"Y,N"'
    assert columns[letter_of(EN_COLUMN_HEADERS, "PERSONAL DATA")] == '"' + ",".join(pii.CLASSES) + '"'
    assert columns[letter_of(EN_COLUMN_HEADERS, "TABLE")] == f"{EN_SHEETS[2]}!$A$2:$A$201"
    dataset = validations(english()[EN_SHEETS[1]])
    assert dataset[letter_of(EN_DATASET_HEADERS, "CONNECTION")] == '"mssql,sqlite"'


def test_the_english_columns_are_wide_enough_and_as_wide_as_the_turkish_ones():
    template, turkish = english(), book(build_template())
    sheets = (EN_DATASET_HEADERS, EN_TABLE_HEADERS, EN_COLUMN_HEADERS, EN_RULE_HEADERS)
    for index, headers in enumerate(sheets, start=1):
        width = len(headers)
        assert widths_of(template[EN_SHEETS[index]], width) == widths_of(
            turkish[TR_SHEETS[index]], width
        )
    assert widths_of(template[EN_SHEETS[3]], len(EN_COLUMN_HEADERS)) == [28, 24, 18, 60, 26, 16, 10, 30, 8]


def test_the_hidden_sheet_records_which_language_the_template_speaks():
    for lang, data in (("en", build_template(lang="en")), ("tr", build_template())):
        info = book(data)["_bilgin"]
        assert info.sheet_state == "hidden"
        assert info["A1"].value == "bilgin-sablon"
        assert info["B1"].value == config.TEMPLATE_VERSION
        assert (info["A2"].value, info["B2"].value) == ("lang", lang)


def test_no_english_cell_writes_a_turkish_letter():
    for data in (
        build_template(lang="en"),
        build_template(SKELETON, lang="en"),
        filled_example_workbook("sales_demo", lang="en"),
        filled_example_workbook("sales_demo", connection="mssql", with_rule=False, lang="en"),
    ):
        for text in cells(book(data)):
            assert not [ch for ch in text if ch in TURKISH_LETTERS], text


def test_the_english_instructions_answer_everything_a_distributor_asks():
    lines = [row[0] for row in grid(english()[EN_SHEETS[0]]) if row[0]]
    assert 10 <= len(lines) <= 15
    text = " ".join(lines)
    for header in ("DESCRIPTION", "CLOSED", "REFERENCE", "VALUES", "KEYWORDS", "NULL"):
        assert header in text
    for sheet in EN_SHEETS[1:]:
        assert sheet in text
    assert "CLOSED = Y" in text and "NULL = N" in text


def test_the_english_example_is_one_finished_table_with_english_values():
    example = english()[EN_SHEETS[5]]
    assert [row[0] for row in block(example, EN_TABLE_HEADERS)] == [EN_TABLE]

    columns = block(example, EN_COLUMN_HEADERS)
    assert 6 <= len(columns) <= 8
    assert [row[EN_COLUMN_HEADERS.index("NULL")] for row in columns] == ["N"] * 5 + ["Y"] * 2
    assert any(
        row[EN_COLUMN_HEADERS.index("REFERENCE")] == "Sales.Customer.CustomerCode" for row in columns
    )
    assert any(row[EN_COLUMN_HEADERS.index("VALUES")] == "S=Sale; R=Return" for row in columns)
    assert any(row[EN_COLUMN_HEADERS.index("PERSONAL DATA")] == "person_name" for row in columns)
    assert any(row[EN_COLUMN_HEADERS.index("CLOSED")] == "Y" for row in columns)

    rules = block(example, EN_RULE_HEADERS)
    assert len(rules) == 1
    assert EN_TABLE in rules[0][EN_RULE_HEADERS.index("TABLES")]


def test_the_english_example_lands_in_the_real_sheets_under_its_own_name():
    template = book(filled_example_workbook("sales_demo", lang="en"))
    assert block(template[EN_SHEETS[1]], EN_DATASET_HEADERS)[0][:3] == [
        "sales_demo",
        "sales_demo",
        "sqlite",
    ]
    assert [row[0] for row in block(template[EN_SHEETS[2]], EN_TABLE_HEADERS)] == [EN_TABLE]
    assert len(block(template[EN_SHEETS[3]], EN_COLUMN_HEADERS)) == 7
    real_columns = block(template[EN_SHEETS[3]], EN_COLUMN_HEADERS)
    assert all(row[EN_COLUMN_HEADERS.index("REFERENCE")] == "" for row in real_columns)
    assert block(template[EN_SHEETS[4]], EN_RULE_HEADERS)[0][0] == "invoice_amount"


def test_an_english_skeleton_marks_nullable_with_y_and_n():
    columns = block(book(build_template(SKELETON, lang="en"))[EN_SHEETS[3]], EN_COLUMN_HEADERS)
    assert [row[:3] for row in columns] == [
        [EN_TABLE, "InvoiceID", "INT"],
        [EN_TABLE, "CustomerCode", "NVARCHAR(20)"],
    ]
    assert [row[EN_COLUMN_HEADERS.index("NULL")] for row in columns] == ["N", "Y"]
    assert columns[1][EN_COLUMN_HEADERS.index("REFERENCE")] == "Sales.Customer.CustomerCode"


def test_the_turkish_workbook_is_the_old_one_plus_the_new_column_and_the_lang_row():
    template = book(build_template())
    assert headers_of(template[TR_SHEETS[1]]) == list(TR_DATASET_HEADERS)
    assert headers_of(template[TR_SHEETS[2]]) == list(TR_TABLE_HEADERS)
    assert headers_of(template[TR_SHEETS[3]]) == list(TR_COLUMN_HEADERS)
    assert headers_of(template[TR_SHEETS[4]]) == [*TR_RULE_HEADERS_BEFORE, "EŞ ANLAMLILAR (EN)"]

    columns = validations(template[TR_SHEETS[3]])
    assert columns[letter_of(TR_COLUMN_HEADERS, "KAPALI")] == '"E,H"'
    assert columns[letter_of(TR_COLUMN_HEADERS, "NULL")] == '"E,H"'
    assert columns[letter_of(TR_COLUMN_HEADERS, "TABLO")] == f"{TR_SHEETS[2]}!$A$2:$A$201"

    example = template[TR_SHEETS[5]]
    assert [row[0] for row in block(example, TR_TABLE_HEADERS)] == ["Satis.Fatura"]
    assert [row[TR_COLUMN_HEADERS.index("NULL")] for row in block(example, TR_COLUMN_HEADERS)] == ["H"] * 5 + ["E"] * 2
    assert tuple(block(example, TR_RULE_HEADERS_BEFORE)[0]) == TR_EXAMPLE_RULE_BEFORE


def test_the_turkish_rules_sheet_carries_the_new_column_in_the_example_too():
    filled = book(filled_example_workbook("ornek", lang="tr"))[TR_SHEETS[4]]
    rules = block(filled, (*TR_RULE_HEADERS_BEFORE, "EŞ ANLAMLILAR (EN)"))
    assert rules[0][6] == "invoice amount, revenue"


def test_no_turkish_literal_is_left_outside_the_labels():
    assert user_literals("bilgin/schema_map/template.py", allow=("LABELS",)) == []
