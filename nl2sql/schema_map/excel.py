"""Excel şema haritasını okuma: sayfalar, başlık satırı ve önizleme satırları (PLAN R3-2).

Başlık satırı, dolu metin hücresi sayısı eşiği geçen ilk satırdır; üstünde kalan satırlar (dosya
adı, boş satır) atılır - müşterinin haritasında başlık her zaman 1. satırda değil. Önizleme LLM'e
gittiği için satır sayısı config.EXCEL_PREVIEW_ROWS ile sınırlıdır; hücreler dönüştürülmeden, ham
değeriyle döner, böylece tip yazımı (`18,2` mi `DECIMAL(18,2)` mi) burada karara bağlanmaz.

Başlık eşleme (PLAN R3-3) başlık metnini profiles/excel_headers.json ile yapar: hangi kelimenin
hangi alan olduğunu dosya söyler, Python ERP bilgisi taşımaz. Eşleşmeyen başlık tüm alanları null
kalarak görünür kalır; uydurma alan adı sessizce geçiştirilmez.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from nl2sql import config
from nl2sql.index import text

# Sayı ile dolu bir satır başlık değildir; eşik metin hücreleri üzerinden sayılır.
_HEADER_TEXT_CELLS = 3

# Mapping kaydının taşıdığı alanlar (Contracts); sözlükte sırası olmayan alan eşlenemez.
_FIELDS = (
    "table_name",
    "column_name",
    "data_type",
    "description",
    "fk_target",
    "values",
    "nullable",
    "module",
)


class SheetError(RuntimeError):
    """Sayfada başlık satırı bulunamadı: boş sayfa ya da eşiği geçen tek satır yok."""


def read_workbook(path: str | Path) -> dict:
    """Her sayfa için önizleme: 1-tabanlı başlık satırı, başlıklar ve ilk EXCEL_PREVIEW_ROWS satır."""
    book = openpyxl.load_workbook(path, data_only=True)
    try:
        sheets = [_read_sheet(sheet) for sheet in book.worksheets]
    finally:
        book.close()
    return {"file": str(path), "sheets": sheets}


def _read_sheet(sheet: Worksheet) -> dict:
    rows = list(sheet.iter_rows(values_only=True))
    for number, row in enumerate(rows, start=1):
        if _text_cells(row) >= _HEADER_TEXT_CELLS:
            return {
                "name": sheet.title,
                "header_row": number,
                "headers": [_text(value) for value in row],
                "rows": [list(item) for item in rows[number : number + config.EXCEL_PREVIEW_ROWS]],
            }
    raise SheetError(
        f"'{sheet.title}' sayfasında başlık satırı yok; en az {_HEADER_TEXT_CELLS} dolu "
        "metin hücresi olan bir satır gerekir."
    )


def _text_cells(row: tuple[Any, ...]) -> int:
    return sum(1 for value in row if isinstance(value, str) and value.strip())


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def fallback_mapping(
    preview: dict, path: str | Path = config.EXCEL_HEADERS_PATH
) -> dict:
    """Başlıkları sözlükle tanıyarak mapping üretir; LLM'e hiç ihtiyaç kalmayan deterministik yol."""
    synonyms = _synonyms(path)
    return {
        "file": preview["file"],
        "generated_by": "fallback",
        "sheets": [_fallback_sheet(sheet, synonyms) for sheet in preview["sheets"]],
        "disagreements": [],
    }


def _fallback_sheet(sheet: dict, synonyms: dict[str, set[str]]) -> dict:
    columns = []
    for index, header in enumerate(sheet["headers"]):
        field = _match(synonyms, header)
        column = {"column": header or get_column_letter(index + 1)}
        for name in _FIELDS:
            column[name] = header if name == field else None
        columns.append(column)
    return {"sheet": sheet["name"], "header_row": sheet["header_row"], "columns": columns}


def _synonyms(path: str | Path) -> dict[str, set[str]]:
    """Alan -> katlanmış başlıklar.

    ASSUMPTION: TÜR hem tip hem değer için yazılabiliyor; dosyada hangisi önce duruyorsa o alan
    kazanır (excel_headers.json'da data_type önde), böylece tek başlık iki alana bölünmüyor.
    """
    with open(path, encoding="utf-8") as handle:
        table = json.load(handle)
    for field, words in table.items():
        if field not in _FIELDS:
            raise ValueError(
                f"excel_headers bilinmeyen alan '{field}'; bilinenler {list(_FIELDS)}."
            )
    return {field: {text.fold(word) for word in words} for field, words in table.items()}


def _match(synonyms: dict[str, set[str]], header: str) -> str | None:
    folded = text.fold(header)
    if not folded:
        return None
    for field, words in synonyms.items():
        if folded in words:
            return field
    return None
