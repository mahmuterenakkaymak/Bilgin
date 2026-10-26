"""Bilgin şablonunun okuyucusu: doldurulmuş dosyadan veri kümesi, şema ve kurallar (PLAN R6-14).

Şablonun iki yüzü vardır: `Veri kümesi` ve `İş kuralları` Bilgin'in sabit biçimidir ve R6-12'nin
başlıklarıyla buradan okunur; `Tablolar` ve `Kolonlar` ise Run 3'ün borosundan geçer - sözlük
eşlemesi ve `convert`. Böylece şablon için LLM'e hiç gerek kalmaz. `Örnek`, `Nasıl doldurulur` ve
`_bilgin` hiçbir sonuca karışmaz: ilki biçimi gösterir, ikincisi talimat, üçüncüsü damga.

Şablon olmayan bir çalışma kitabı Run 3'ün yolundan gider: başlık önerisi modele sorulur (llm
verilmişse), sözlük eşlemesi her durumda altta yatar. İki yolda da bir `Veri kümesi` satırı
şarttır, çünkü her yükleme yeni bir veri kümesi yaratır.

Hücre hataları `MapIssue` olarak birikir ve okuma durmaz: kullanıcı hepsini aynı raporda görsün,
dosyayı düzeltip yeniden yüklemesi tek tur sürsün.

ASSUMPTION: şablonun DEĞERLER başlığı sözlüğe `values` eşanlamlısı olarak eklendi (R6-13'ün
sözlüğü tekili biliyordu); okuyucu yine sözlüğü kullanır, kendine ikinci bir eşleme tablosu
çıkarmaz.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any

import openpyxl

from nl2sql.index import text
from nl2sql.schema_map import excel, rules_edit
from nl2sql.schema_map.template import (
    COLUMN_HEADERS,
    DATASET_HEADERS,
    INFO_SHEET,
    RULE_HEADERS,
    SHEETS,
    TEMPLATE_MARK,
)

# Sayfa adları yazıcıyla aynı sabitlerden gelir; biri değişirse iki taraf birden kırılır.
DATASET_SHEET, TABLE_SHEET, COLUMN_SHEET, RULE_SHEET = SHEETS[1], SHEETS[2], SHEETS[3], SHEETS[4]
_SCHEMA_SHEETS = (TABLE_SHEET, COLUMN_SHEET)
# Şema olmayan sayfalar: şablon olmayan bir dosyada da şemaya karışmazlar.
_FIXED_SHEETS = (SHEETS[0], DATASET_SHEET, RULE_SHEET, SHEETS[5], INFO_SHEET)

_AD, _GORUNEN_AD, _BAGLANTI, _VARSAYILAN_SEMA, _VERI_TARIHI = DATASET_HEADERS
_KIMLIK, _TERIM, _ES_ANLAMLILAR, _TANIM, _SQL_IPUCU, _TABLOLAR = RULE_HEADERS
# Kolonlar'ın zorunlu üç hücresi ve E/H listesi olan iki hücresi.
_TABLO, _KOLON, _TIP = COLUMN_HEADERS[:3]
_KAPALI, _NULL = COLUMN_HEADERS[6], COLUMN_HEADERS[8]

_EH = ("e", "h")


class TemplateError(ValueError):
    """Yüklenen dosya bir veri kümesi tanımlamıyor: adını taşıdığı sayfa yok."""


def is_bilgin_template(path: str | Path) -> bool:
    """Gizli `_bilgin` sayfasının A1 hücresi şablonun damgasını taşıyor mu?"""
    return _stamp(path)[0]


def read_template(path: str | Path, llm=None) -> dict:
    """Doldurulmuş şablonu (ya da şema haritasını) TemplateRead sözlüğüne çevirir."""
    template, names = _stamp(path)
    if DATASET_SHEET not in names:
        raise TemplateError("Veri kümesi sayfası yok: Bilgin şablonunu kullanın.")
    converted = excel.convert(path, _schema_mapping(path, template, names, llm))
    schema = converted["schema"]
    rules = _rules(path) if RULE_SHEET in names else []
    return {
        "dataset": _dataset(path),
        "schema": schema,
        "rules": rules,
        "counts": _counts(schema, converted["columns"], rules),
        "errors": _issues(converted["skipped"]) + (_cell_issues(path, names) if template else []),
        "warnings": [],
        "template": template,
    }


def _stamp(path: str | Path) -> tuple[bool, list[str]]:
    """(şablon mu, sayfa adları): damga ile hangi sayfaların gerçekten olduğu tek açılışta çıkar."""
    book = openpyxl.load_workbook(path, data_only=True)
    try:
        names = list(book.sheetnames)
        mark = INFO_SHEET in names and _text(book[INFO_SHEET]["A1"].value) == TEMPLATE_MARK
        return mark, names
    finally:
        book.close()


def _schema_mapping(path: str | Path, template: bool, names: list[str], llm) -> dict:
    """Şemayı taşıyan sayfaların eşlemesi: şablon sözlükle geçer, harita öneri yolundan da."""
    if template:
        return excel.fallback_mapping(_preview(path, [n for n in _SCHEMA_SHEETS if n in names]))
    preview = excel.read_workbook(path)
    mapping = excel.propose(preview, llm) if llm else excel.fallback_mapping(preview)
    mapping["sheets"] = [
        sheet
        for sheet in mapping["sheets"]
        if sheet["sheet"] not in _FIXED_SHEETS and _says_anything(sheet)
    ]
    return mapping


def _preview(path: str | Path, names: list[str]) -> dict:
    """Yalnız istenen sayfaların önizlemesi; satırlar boş - sözlük başlıklara bakar, satırları
    `convert` kendisi okur.

    ASSUMPTION: `read_workbook` her sayfada başlık satırı arar; `Nasıl doldurulur` ve `_bilgin`
    başlık satırı taşımadığı için şablon yolu onları ona hiç sokmaz (R6-12'nin ASSUMPTION'ı).
    """
    sheets = []
    for name in names:
        number, headers, _ = excel.sheet_rows(path, name)
        sheets.append({"name": name, "header_row": number, "headers": headers, "rows": []})
    return {"file": str(path), "sheets": sheets}


def _says_anything(sheet: dict) -> bool:
    """Sayfa hiçbir alan iddia etmiyorsa şema sayfası değildir; boş sayfanın gürültüsü üretilmez."""
    return any(
        value
        for column in sheet.get("columns") or []
        for name, value in column.items()
        if name != "column"
    )


def _dataset(path: str | Path) -> dict:
    """Veri kümesi sayfasının tek dolu satırı; boş hücre sözleşmenin varsayılanıdır."""
    _, headers, rows = excel.sheet_rows(path, DATASET_SHEET)
    cells = next((cells for _, cells in rows if any(_text(value) for value in cells)), ())
    return {
        "name": _cell(cells, headers, _AD),
        "display_name": _cell(cells, headers, _GORUNEN_AD),
        # ASSUMPTION: boş BAĞLANTI sözleşmenin varsayılanıdır; uydurulan bir ad değil, listesi var.
        "connection": _cell(cells, headers, _BAGLANTI).lower() or "mssql",
        "default_schema": _cell(cells, headers, _VARSAYILAN_SEMA) or None,
        "as_of": _as_of(cells, headers),
    }


def _as_of(cells: tuple, headers: list[str]) -> str:
    """VERİ TARİHİ: Excel'in tarih hücresi de düz metni de aynı ISO güne iner."""
    value = _raw(cells, headers, _VERI_TARIHI)
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    return _text(value)


def _rules(path: str | Path) -> list[dict]:
    """İş kuralları sayfasının dolu satırları; EŞ ANLAMLILAR ve TABLOLAR , ; ile ayrılır."""
    _, headers, rows = excel.sheet_rows(path, RULE_SHEET)
    rules = []
    for _, cells in rows:
        if not any(_text(value) for value in cells):
            continue
        rules.append(
            rules_edit.normalize_rule(
                {
                    "id": _cell(cells, headers, _KIMLIK),
                    "term": _cell(cells, headers, _TERIM),
                    "synonyms": _list(_cell(cells, headers, _ES_ANLAMLILAR)),
                    "definition": _cell(cells, headers, _TANIM),
                    "sql_hint": _cell(cells, headers, _SQL_IPUCU),
                    "tables": _list(_cell(cells, headers, _TABLOLAR)),
                }
            )
        )
    return rules


def _counts(schema: dict, columns: int, rules: list[dict]) -> dict:
    """Raporun sayıları: kullanıcı ne yüklediğini bunlardan okur."""
    marked = [column for table in schema["tables"] for column in table["columns"]]
    return {
        "tables": len(schema["tables"]),
        "columns": columns,
        "pii": sum(1 for column in marked if column.get("pii")),
        "deny": sum(1 for column in marked if column.get("deny")),
        "references": sum(1 for column in marked if column.get("fk")),
        "rules": len(rules),
    }


def _cell_issues(path: str | Path, names: list[str]) -> list[dict]:
    """Şablonun kendi hücre kuralları: zorunlu hücreler ve E/H listeleri.

    `convert` boş TİP'i NVARCHAR(255) sayar, KAPALI'daki "Y"yi kapalı değil sayar; şablon
    ikisinde de uydurmaz, kullanıcıya sorar. KİŞİSEL VERİ sınıfını ve REFERANS biçimini zaten
    `convert` notluyor, burada yinelenmez.
    """
    issues: list[dict] = []
    for sheet, required in ((TABLE_SHEET, (_TABLO,)), (COLUMN_SHEET, (_TABLO, _KOLON, _TIP))):
        if sheet not in names:
            continue
        _, headers, rows = excel.sheet_rows(path, sheet)
        for number, cells in rows:
            if not any(_text(value) for value in cells):
                continue  # şablonun stil dolu 200 boş satırı dolgu, eksik hücresi sayılmaz
            for header in required:
                if not _cell(cells, headers, header):
                    issues.append(_issue(sheet, number, header, f"{header} boş; satır şemaya alınmadı."))
            for header in (_KAPALI, _NULL):
                value = _cell(cells, headers, header)
                if value and text.fold(value) not in _EH:
                    issues.append(_issue(sheet, number, header, f"{header} '{value}'; E ya da H olmalı."))
    return issues


def _issues(notes: list[dict]) -> list[dict]:
    """convert'in atlanan satır notları MapIssue'a döner: kullanıcı kusuru sayfada bulur."""
    return [_issue(note["sheet"], note["row"], None, note["reason"]) for note in notes]


def _issue(sheet: str, row: int | None, column: str | None, message: str) -> dict:
    return {"sheet": sheet, "row": row, "column": column, "message": message}


def _cell(cells: tuple, headers: list[str], header: str) -> str:
    return _text(_raw(cells, headers, header))


def _raw(cells: tuple, headers: list[str], header: str) -> Any:
    """Başlığın hücresi; sayfada o başlık yok ya da satır oraya ulaşmıyorsa boş."""
    index = next(
        (i for i, value in enumerate(headers) if text.fold(value) == text.fold(header)), None
    )
    return None if index is None or index >= len(cells) else cells[index]


def _list(value: str) -> list[str]:
    """'ciro, satış tutarı; hasılat' -> üç sözcük; boş hücre boş liste."""
    return [word.strip() for word in re.split(r"[,;]+", value) if word.strip()]


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()
