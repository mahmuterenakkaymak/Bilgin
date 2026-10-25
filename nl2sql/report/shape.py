"""Sonucun biçimi: kolonlar ne tür ve grafik hangisini çizer (PLAN R5-6).

Tür dönen değerlerden anlaşılır, sorulan sözcüklerden değil; o yüzden aynı sonuç her koşumda aynı
biçimi verir. Tür tüm dolu hücrelerden okunur: tek NULL bir kolonu bozmaz, hepsi NULLsa ortada
tür yoktur (onun uyarısı R5-5'in işi). Kod benzeri ad (URUN_KODU, FIS_NO) sayı taşasa da sayı
değildir — toplanması bir şey ifade etmeyen kolon grafiğin eksenine çıkmaz.
"""

from __future__ import annotations

import re
from decimal import Decimal

DATE = "date"
NUMBER = "number"
CODE = "code"
CATEGORY = "category"

# Adlar ASCII büyük harfe katlanarak karşılaştırılır (DÖNEM -> DONEM); set ve son ekler ASCII'dir.
_FOLD = str.maketrans("çÇğĞıİöÖşŞüÜ", "CCGGIIOOSSUU")
_DATE_NAMES = frozenset({"AY", "YIL", "DONEM", "TARIH", "MONTH", "YEAR", "DATE"})
_CODE_SUFFIXES = ("KOD", "KODU", "ID", "NO")
_ISO_PERIOD = re.compile(r"\d{4}-\d{2}(-\d{2})?")


def column_kinds(columns: list[str], rows: list[tuple]) -> list[str]:
    """Kolon başına tür: "date" | "number" | "code" | "category"."""
    return [_kind(name, [row[i] for row in rows]) for i, name in enumerate(columns)]


def pick(columns: list[str], rows: list[tuple]) -> dict:
    """Grafik işinin kolon seçimi: tarih, sayı ve kod kolonlarının indeksleri, tek kategori."""
    kinds = column_kinds(columns, rows)
    return {
        "date": _indexes(kinds, DATE),
        "number": _indexes(kinds, NUMBER),
        "category": _category(kinds),
        "code": _indexes(kinds, CODE),
    }


def _kind(name: str, values: list) -> str:
    cells = [value for value in values if value is not None]
    if not cells:
        return CATEGORY
    if all(_is_period(value) for value in cells):
        return DATE
    folded = name.translate(_FOLD).upper()
    if folded in _DATE_NAMES and all(_is_int(value) for value in cells):
        return DATE
    if all(_is_number(value) for value in cells) and not folded.endswith(_CODE_SUFFIXES):
        return NUMBER
    if folded.endswith(_CODE_SUFFIXES):
        return CODE
    return CATEGORY


def _category(kinds: list[str]) -> int | None:
    """Kategori: metin kolonları içinden ilki; yalnız kod varsa ilk kod kolonu."""
    for kind in (CATEGORY, CODE):
        for index, value in enumerate(kinds):
            if value == kind:
                return index
    return None


def _indexes(kinds: list[str], kind: str) -> list[int]:
    return [index for index, value in enumerate(kinds) if value == kind]


def _is_period(value) -> bool:
    return isinstance(value, str) and bool(_ISO_PERIOD.fullmatch(value))


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
