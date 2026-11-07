# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T111: eşlemedeki header_row dönüşüme uygulanır (PLAN R3-2).

Öneri adımının yazdığı 1-tabanlı başlık satırı kullanıcıya "eşlemeyi elle düzeltmek isterseniz
--mapping ile geri verin" denerek bırakılıyor; dönüşüm o alanı yok sayarsa düzeltme hiçbir işe
yaramaz: 3 dolu metin hücresi olan bir unvan satırı başlık sanılınca sütun referansları hiçbir
yere çözülmez ve sayfa 0 tabloya düşer.
"""

import openpyxl
import pytest

from nl2sql.schema_map.excel import convert, fallback_mapping, read_workbook

HEADERS = ["TABLO", "KOLON", "TİP", "AÇIKLAMA", "REFERANS", "DEĞER", "NULL", "MODÜL"]

# Üç dolu metin hücresi: eşiği geçtiği için otomatik seçim bu satırı başlık sayar.
TITLED = ["MÜŞTERİ ŞEMA HARİTASI", "2026", "ONAYLI"]

ROWS = [
    ["TBLA", "KOD", "varchar(12)", "Kart kodu."],
    ["TBLA", "AD", "metin"],
    ["TBLB", "K1", "int"],
]


def write(tmp_path, name="harita.xlsx", rows=ROWS, top=()) -> str:
    """Geçici kitap: üstte ek satırlar, sonra gerçek başlık ve veri satırları."""
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "KOLONLAR"
    for item in top:
        sheet.append(item)
    sheet.append(HEADERS)
    for item in rows:
        sheet.append(item)
    path = tmp_path / name
    book.save(path)
    return str(path)


def mapping(tmp_path) -> dict:
    """Gerçek başlık satırından üretilmiş eşleme; düzeltme bu referanslarla ölçülür."""
    return fallback_mapping(read_workbook(write(tmp_path, "temiz.xlsx")))


def column_names(report: dict, name: str) -> list[str]:
    table = next(item for item in report["schema"]["tables"] if item["name"] == name)
    return [item["name"] for item in table["columns"]]


def test_uncorrected_header_row_yields_no_tables(tmp_path):
    path = write(tmp_path, top=[TITLED])
    report = convert(path, mapping(tmp_path))
    assert report["schema"]["tables"] == []
    assert report["columns"] == 0
    assert all("TABLO boş" in item["reason"] for item in report["skipped"])
    assert [item["row"] for item in report["skipped"]][:2] == [2, 3], "başlık satırı da boş sayılır"


def test_corrected_header_row_converts_the_sheet(tmp_path):
    path = write(tmp_path, top=[TITLED])
    fixed = mapping(tmp_path)
    fixed["sheets"][0]["header_row"] = 2
    report = convert(path, fixed)
    assert report["skipped"] == []
    assert (report["tables"], report["columns"]) == (2, 3)
    assert column_names(report, "TBLA") == ["KOD", "AD"]
    assert column_names(report, "TBLB") == ["K1"]


def test_mapping_without_header_row_keeps_auto_detection(tmp_path):
    path = write(tmp_path, top=[["MÜŞTERİ ŞEMA HARİTASI"], []])
    fixed = mapping(tmp_path)
    del fixed["sheets"][0]["header_row"]
    report = convert(path, fixed)
    assert report["skipped"] == []
    assert (report["tables"], report["columns"]) == (2, 3)


@pytest.mark.parametrize("value", [0, -1, "2", None])
def test_header_row_that_is_not_a_row_number_falls_back_to_auto_detection(tmp_path, value):
    path = write(tmp_path, top=[TITLED])
    fixed = mapping(tmp_path)
    fixed["sheets"][0]["header_row"] = value
    report = convert(path, fixed)
    assert report["schema"]["tables"] == [], "otomatik seçim unvan satırını başlık sayar"
    assert any("TABLO boş" in item["reason"] for item in report["skipped"])
