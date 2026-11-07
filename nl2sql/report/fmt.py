# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Türkçe sayı yazımı: ekrana çıkan her sayının tek kaynağı (PLAN R5-6, R5-7).

Değeri burası üretmez; SQL'in döndürdüğünü yalnız okunur kılar — binlik ayıracı nokta, ondalık
virgül, yüzde işareti sayının önünde. Yuvarlama yalnız gösterilir, toplanan şey değişmez. Boş
hücre "0" değil "–"dir: sıfır bir bilgidir, yokluk değil.
"""

from __future__ import annotations

NULL_TEXT = "–"
DECIMALS = 2
PERCENT_DECIMALS = 1
COMPACT_DECIMALS = 1
COMPACT_MIN = 10_000

_SWAP = str.maketrans(",.", ".,")
_SCALES = ((1_000_000_000, "milyar"), (1_000_000, "milyon"), (1_000, "bin"))


def tr_number(value, decimals: int | None = None) -> str:
    """Sayı Türkçe okunuşu: 1234.56 -> "1.234,56", 12345 -> "12.345", None -> "–".

    Basamak verilmezse tam sayı basamaksız, kesirli sayı en çok DECIMALS kadar ve gereksiz son
    sıfırı olmadan yazılır (1234.5 -> "1.234,5"); verilirse tam olarak o kadar yazılır, para bu
    yolla "1.234,50" olur.
    """
    if value is None:
        return NULL_TEXT
    if decimals is not None:
        text = f"{value:,.{decimals}f}"
    elif isinstance(value, int):
        text = f"{value:,d}"
    else:
        text = f"{value:,.{DECIMALS}f}".rstrip("0").rstrip(".")
    text = text.translate(_SWAP)
    return text[1:] if text.startswith("-") and _only_zeros(text) else text


def tr_percent(value, decimals: int = PERCENT_DECIMALS) -> str:
    """Yüzde Türkçe: %12,3 — imleç birlikte yazılır, eksi -%1,5 olur."""
    if value is None:
        return NULL_TEXT
    return f"{'-' if value < 0 else ''}%{tr_number(abs(value), decimals)}"


def tr_compact(value) -> str:
    """Büyük sayıyı ölçekle okunur kılar: 12500 -> "12,5 bin"; 10.000'dan küçüğü olduğu gibi sayı."""
    if value is None:
        return NULL_TEXT
    size = abs(value)
    if size < COMPACT_MIN:
        return tr_number(value)
    scale, name = next(item for item in _SCALES if size >= item[0])
    return f"{'-' if value < 0 else ''}{tr_number(size / scale, COMPACT_DECIMALS)} {name}"


def _only_zeros(text: str) -> bool:
    """Yuvarlama sıfıra mı indirdi: gösterilen -0, gerçek bir bilgi değildir."""
    return not any(char.isdigit() and char != "0" for char in text)
