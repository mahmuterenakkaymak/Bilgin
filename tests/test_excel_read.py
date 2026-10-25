"""T79: Excel okuyucu - başlık satırının bulunması, başlıklar ve sınırlı önizleme.

Çalışma kitapları openpyxl ile tmp_path içinde kurulur (gerçek .xlsx fixture'ları T83'ün işi),
böylece her test bozuk kabul ettiği tam yapıyı kendi satırlarıyla söyler.
"""

import openpyxl
import pytest

from nl2sql import config
from nl2sql.schema_map.excel import SheetError, read_workbook

HEADERS = ["TABLO", "KOLON", "TİP", "AÇIKLAMA"]


def write(tmp_path, sheets: dict[str, list[list]]) -> str:
    """{sayfa adı: satırlar} ile çalışma kitabı yazar; yolunu döndürür."""
    book = openpyxl.Workbook()
    book.remove(book.active)
    for title, rows in sheets.items():
        sheet = book.create_sheet(title)
        for row in rows:
            sheet.append(row)
    path = tmp_path / "harita.xlsx"
    book.save(path)
    return str(path)


def first_sheet(preview: dict) -> dict:
    assert [sheet["name"] for sheet in preview["sheets"]] == ["KOLONLAR"], preview["sheets"]
    return preview["sheets"][0]


def test_turkish_headers_and_rows(tmp_path):
    path = write(tmp_path, {
        "KOLONLAR": [
            HEADERS,
            ["STOK_HAREKET", "HAREKET_YONU", "VARCHAR", "Giriş/çıkış kodu"],
            ["STOK_HAREKET", "HAREKET_ADET", "SAYI", "Miktar"],
        ]
    })
    preview = read_workbook(path)
    assert preview["file"] == path
    sheet = first_sheet(preview)
    assert sheet["header_row"] == 1
    assert sheet["headers"] == HEADERS
    assert sheet["rows"] == [
        ["STOK_HAREKET", "HAREKET_YONU", "VARCHAR", "Giriş/çıkış kodu"],
        ["STOK_HAREKET", "HAREKET_ADET", "SAYI", "Miktar"],
    ]


def test_title_and_empty_rows_above_the_header(tmp_path):
    path = write(tmp_path, {
        "KOLONLAR": [
            ["ŞİRKET ŞEMA HARİTASI - EKİM 2026"],
            [],
            HEADERS,
            ["KART", "KODU", "VARCHAR", "Malzeme kodu"],
        ]
    })
    sheet = first_sheet(read_workbook(path))
    assert sheet["header_row"] == 3
    assert sheet["headers"] == HEADERS
    assert sheet["rows"] == [["KART", "KODU", "VARCHAR", "Malzeme kodu"]]


def test_only_text_rows_are_headers(tmp_path):
    path = write(tmp_path, {
        "KOLONLAR": [
            [1, 2, 3, 4],
            HEADERS,
            ["KART", "AD", "VARCHAR", "Malzeme adı"],
        ]
    })
    sheet = first_sheet(read_workbook(path))
    assert sheet["header_row"] == 2, "sayı ile dolu satır başlık sayılmamalı"
    assert sheet["headers"] == HEADERS


def test_cell_values_stay_raw_and_empty_headers_are_blank(tmp_path):
    path = write(tmp_path, {
        "KOLONLAR": [
            ["TABLO", "KOLON", "TİP", None, "AÇIKLAMA"],
            ["FATURA", "GENEL_TOPLAM", "SAYI", None, 12.5],
            ["FATURA", "PARA", "SAYI", None, None],
        ]
    })
    sheet = first_sheet(read_workbook(path))
    assert sheet["headers"] == ["TABLO", "KOLON", "TİP", "", "AÇIKLAMA"]
    assert sheet["rows"] == [
        ["FATURA", "GENEL_TOPLAM", "SAYI", None, 12.5],
        ["FATURA", "PARA", "SAYI", None, None],
    ]


def test_preview_capped_at_config_rows(tmp_path):
    body = [[f"TBL{i:02d}", f"KOLON{i:02d}", "VARCHAR", f"Açıklama {i}"] for i in range(25)]
    path = write(tmp_path, {"KOLONLAR": [HEADERS, *body]})
    sheet = first_sheet(read_workbook(path))
    assert len(sheet["rows"]) == config.EXCEL_PREVIEW_ROWS == 20
    assert sheet["rows"][0] == body[0]
    assert sheet["rows"][-1] == body[config.EXCEL_PREVIEW_ROWS - 1]


def test_every_sheet_is_previewed_in_order(tmp_path):
    path = write(tmp_path, {
        "TABLOLAR": [["TABLO", "MODÜL", "AÇIKLAMA"], ["KART", "STOCK", "Malzeme kartı"]],
        "KOLONLAR": [HEADERS, ["KART", "KODU", "VARCHAR", "Kod"]],
    })
    preview = read_workbook(path)
    assert [sheet["name"] for sheet in preview["sheets"]] == ["TABLOLAR", "KOLONLAR"]
    assert preview["sheets"][0]["rows"] == [["KART", "STOCK", "Malzeme kartı"]]
    assert preview["sheets"][1]["header_row"] == 1


def test_sheet_without_header_raises_naming_it(tmp_path):
    path = write(tmp_path, {"KOLONLAR": [HEADERS[:2]], "BOŞ": []})
    with pytest.raises(SheetError) as record:
        read_workbook(path)
    assert "KOLONLAR" in str(record.value), "hata hangi sayfada olduğunu söylemeli"


def test_empty_sheet_raises_naming_it(tmp_path):
    path = write(tmp_path, {"KOLONLAR": [HEADERS], "Bekleyen": []})
    with pytest.raises(SheetError) as record:
        read_workbook(path)
    assert "Bekleyen" in str(record.value)
