# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Dışa aktarım dosyaları: bir cevabın satırları CSV ve XLSX olarak (PLAN R5-16).

Satırlar yürütücünün döndürdükleridir: maske burada yeniden hesaplanmaz, hücreye olduğu gibi
yazılır. CSV Excel'in de açtığı dosyadır, o yüzden ayraç ``;`` ve ondalık virgül; XLSX'te sayı
sayı olarak kalır, yani indirilen dosyada toplama yeniden girilebilir.
"""

from __future__ import annotations

import csv
import io

import openpyxl
from openpyxl.styles import Font

# Contracts "export file": BOM + ``;`` + satır sonu, ondalık virgül, binlik ayıracı yok, NULL boş.
# BOM'nin kendisi U+FEFF: Excel UTF-8'i ancak onu görünce tanır, o yüzden kaynakta karakter taşımıyoruz.
CSV_BOM = chr(0xFEFF)
CSV_DELIMITER = ";"
CSV_LINE_END = "\r\n"
SHEET_NAME = "Sonuç"

# İndirme başlığının uzantıya göre türü: tarayıcı dosyayı bunlarla tanır (R5-15 yolu).
MEDIA_TYPES = {
    "csv": "text/csv; charset=utf-8",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}

_HEADER_FONT = Font(bold=True)


def to_csv_bytes(columns: list[str], rows: list[tuple]) -> bytes:
    """Başlık ve satırların CSV'si: BOM ile açılır, ``;`` ile ayrılır, satır sonu CRLF."""
    text = io.StringIO()
    writer = csv.writer(text, delimiter=CSV_DELIMITER, lineterminator=CSV_LINE_END)
    writer.writerow(list(columns))
    for row in rows:
        writer.writerow([_text(value) for value in row])
    return (CSV_BOM + text.getvalue()).encode("utf-8")


def to_xlsx_bytes(columns: list[str], rows: list[tuple]) -> bytes:
    """Tek sayfalık kitap: başlık kalın, sayılar sayı hücresi, None boş hücre."""
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = SHEET_NAME
    sheet.append([str(name) for name in columns])
    for cell in sheet[1]:
        cell.font = _HEADER_FONT
    for row in rows:
        sheet.append([_number(value) for value in row])
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def _text(value) -> str:
    """CSV hücresi: sayı virgüllü ve ayıraçsız, None boş alan; geri kalanının kendi metni."""
    if value is None:
        return ""
    if isinstance(value, float):
        return str(value).replace(".", ",")
    return str(value)


def _number(value):
    """XLSX hücresi: sayı olduğu gibi gider ki toplanabilsin; None boş, metin metin."""
    if value is None or isinstance(value, (int, float)):
        return value
    return str(value)
