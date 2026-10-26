"""T80: deterministik başlık eşleme - profiles/excel_headers.json ile LLM'siz mapping.

Önizlemeler elle kurulur (okuyucunun kendi testi var); tek uçtan uca test gerçek bir çalışma
kitabı üzerinden iki parçanın şekillerinin birbirini tuttuğunu doğrular.
"""

import json

import openpyxl
import pytest

from nl2sql import config
from nl2sql.index.text import fold
from nl2sql.schema_map.excel import fallback_mapping, read_workbook

FIELDS = (
    "table_name",
    "column_name",
    "data_type",
    "description",
    "fk_target",
    "values",
    "nullable",
    "module",
    "pii",
    "deny",
    "keywords",
)


def preview(headers, name="KOLONLAR", header_row=1, file="harita.xlsx") -> dict:
    return {
        "file": file,
        "sheets": [
            {"name": name, "header_row": header_row, "headers": list(headers), "rows": []}
        ],
    }


def columns(mapping: dict, sheet: int = 0) -> list[dict]:
    return mapping["sheets"][sheet]["columns"]


def fields_of(entry: dict) -> dict:
    return {name: value for name, value in entry.items() if name != "column"}


def mapped_as(header: str) -> str | None:
    """Tek başlıklı bir önizlemede başlığın yazıldığı alan; eşlenmezse None."""
    entry = columns(fallback_mapping(preview([header])))[0]
    filled = [name for name, value in fields_of(entry).items() if value is not None]
    assert len(filled) <= 1, f"{header} birden fazla alana yazıldı: {filled}"
    return filled[0] if filled else None


def test_netsis_style_headers_cover_every_field():
    headers = ["TABLO", "KOLON", "TİP", "AÇIKLAMA", "REFERANS", "DEĞER", "NULL", "MODÜL"]
    entries = columns(fallback_mapping(preview(headers)))
    assert [entry["column"] for entry in entries] == headers
    for entry, field in zip(entries, FIELDS):
        assert fields_of(entry) == {
            name: (entry["column"] if name == field else None) for name in FIELDS
        }


def test_english_headers():
    headers = ["TABLE", "FIELD", "TYPE", "DESCRIPTION", "MODULE"]
    assert [mapped_as(header) for header in headers] == [
        "table_name",
        "column_name",
        "data_type",
        "description",
        "module",
    ]


def test_tablo_adi_and_kolon_variants():
    assert mapped_as("TABLO ADI") == "table_name"
    assert mapped_as("Tablo Adı") == "table_name"
    assert mapped_as("ALAN") == "column_name"
    assert mapped_as("Kolon") == "column_name"


def test_tip_tip_tip_all_land_on_data_type():
    for header in ("TİP", "Tip", "tip", "TIP", "tıp", "TYPE"):
        assert mapped_as(header) == "data_type", header


def test_ascii_and_diacritic_spellings_agree():
    for dotted, ascii_form, field in (
        ("AÇIKLAMA", "ACIKLAMA", "description"),
        ("MODÜL", "MODUL", "module"),
        ("DEĞER", "DEGER", "values"),
        ("BOŞ", "BOS", "nullable"),
    ):
        assert mapped_as(dotted) == mapped_as(ascii_form) == field, (dotted, ascii_form)


def test_tur_belongs_to_one_field_only():
    assert mapped_as("TÜR") == mapped_as("TUR") == "data_type"


def test_unknown_headers_keep_every_field_null():
    entries = columns(fallback_mapping(preview(["TABLO", "KOD_AÇILIMI", "ETİKET", "SIRA"])))
    assert fields_of(entries[0])["table_name"] == "TABLO"
    for entry in entries[1:]:
        assert set(fields_of(entry).values()) == {None}


def test_blank_header_is_named_by_its_column_letter():
    entries = columns(fallback_mapping(preview(["TABLO", "", "KOLON"])))
    assert [entry["column"] for entry in entries] == ["TABLO", "B", "KOLON"]
    assert set(fields_of(entries[1]).values()) == {None}


def test_every_entry_carries_the_full_field_set():
    for entry in columns(fallback_mapping(preview(["TABLO", "bilinmeyen", ""]))):
        assert set(entry) == {"column", *FIELDS}


def test_mapping_shape_and_sheet_metadata():
    result = fallback_mapping(preview(["TABLO", "KOLON"], name="SHEET-1", header_row=4, file="a.xlsx"))
    assert result["file"] == "a.xlsx"
    assert result["generated_by"] == "fallback"
    assert result["disagreements"] == []
    assert [(s["sheet"], s["header_row"]) for s in result["sheets"]] == [("SHEET-1", 4)]


def test_every_sheet_is_mapped():
    result = {
        "file": "cift.xlsx",
        "sheets": [
            {"name": "TABLOLAR", "header_row": 1, "headers": ["TABLO", "MODÜL"], "rows": []},
            {"name": "KOLONLAR", "header_row": 2, "headers": ["KOLON", "TİP"], "rows": []},
        ],
    }
    mapping = fallback_mapping(result)
    assert [sheet["sheet"] for sheet in mapping["sheets"]] == ["TABLOLAR", "KOLONLAR"]
    assert [c["column"] for c in columns(mapping, 0)] == ["TABLO", "MODÜL"]
    assert [c["column_name"] for c in columns(mapping, 1)] == ["KOLON", None]


def test_default_profile_covers_the_canonical_fields_without_ambiguity():
    with open(config.EXCEL_HEADERS_PATH, encoding="utf-8") as handle:
        table = json.load(handle)
    assert set(table) == set(FIELDS)
    folded = {field: {fold(word) for word in words} for field, words in table.items()}
    for field, words in folded.items():
        assert words, field
    for left in FIELDS:
        for right in FIELDS:
            if left < right:
                assert not folded[left] & folded[right], f"{left} ve {right} aynı başlığı istiyor"


def test_unknown_field_in_the_profile_is_rejected(tmp_path):
    path = tmp_path / "excel_headers.json"
    path.write_text(json.dumps({"TABLO_ADI": ["TABLO"]}), encoding="utf-8")
    with pytest.raises(ValueError) as record:
        fallback_mapping(preview(["TABLO"]), path)
    assert "TABLO_ADI" in str(record.value), "hata hangi alanın bilinmediğini söylemeli"


def test_real_workbook_preview_flows_into_the_mapping(tmp_path):
    book = openpyxl.Workbook()
    book.remove(book.active)
    sheet = book.create_sheet("KOLONLAR")
    for row in (
        ["MÜŞTERİ ŞEMA HARİTASI"],
        [],
        ["Tablo", "Alan", "Tip", "Açıklama", "Referans", "Değer", "Boş", "Modül"],
        ["TBLSTHAR", "STHAR_GCKOD", "VARCHAR", "Giriş/çıkış", None, "G=Giriş; C=Çıkış", "H", "STOCK"],
    ):
        sheet.append(row)
    path = tmp_path / "harita.xlsx"
    book.save(path)

    mapping = fallback_mapping(read_workbook(str(path)))
    entries = columns(mapping)
    assert mapping["sheets"][0]["header_row"] == 3
    assert mapping["generated_by"] == "fallback"
    expected = {
        "Tablo": "table_name",
        "Alan": "column_name",
        "Tip": "data_type",
        "Açıklama": "description",
        "Referans": "fk_target",
        "Değer": "values",
        "Boş": "nullable",
        "Modül": "module",
    }
    for entry in entries:
        filled = [field for field, value in fields_of(entry).items() if value is not None]
        assert filled == [expected[entry["column"]]], entry["column"]
