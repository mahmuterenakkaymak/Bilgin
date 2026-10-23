"""Excel şema haritasını okuma: sayfalar, başlık satırı ve önizleme satırları (PLAN R3-2).

Başlık satırı, dolu metin hücresi sayısı eşiği geçen ilk satırdır; üstünde kalan satırlar (dosya
adı, boş satır) atılır - müşterinin haritasında başlık her zaman 1. satırda değil. Önizleme LLM'e
gittiği için satır sayısı config.EXCEL_PREVIEW_ROWS ile sınırlıdır; hücreler dönüştürülmeden, ham
değeriyle döner, böylece tip yazımı (`18,2` mi `DECIMAL(18,2)` mi) burada karara bağlanmaz.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from nl2sql import config

# Sayı ile dolu bir satır başlık değildir; eşik metin hücreleri üzerinden sayılır.
_HEADER_TEXT_CELLS = 3


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
