# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Cevabın sayıları: özetler koddan çıkar, anlatı onları uydurmaz (PLAN R5-7, Contracts Fact).

Guard'ın izin listesi de arayüzün gösterdiği satır da buradan gelir. Maske burada yeniden
hesaplanmaz: maskeli hücre çoktan metne dönmüştür, o yüzden sayı kolonu değildir ve zaten
toplanmaz. Boş hücre ortalamaya girmez ama satır sayısı satırdır; pay ile dönem değişimi
yalnız anlamlı oldukları durumda yazılır — negatif toplamlada pay, sıfır önceki dönemde yüzde
uydurulmaz.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from nl2sql.report import fmt, shape

MEAN_DECIMALS = 2


@dataclass(frozen=True)
class Fact:
    """Tek bir özet: ne olduğu, kimi anlatığı, Türkçe okunuşu ve sayısı (Contracts Fact)."""

    name: str
    label: str
    value: int | float | str
    display: str
    column: str | None = None
    percent: bool = False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "column": self.column,
            "value": self.value,
            "display": self.display,
            "percent": self.percent,
        }


def compute_facts(columns: list[str], rows: list[tuple]) -> list[Fact]:
    """Sonucun olguları: satır sayısı, her sayı kolonunun toplamı/ucu/ortalaması, payı ve dönem değişimi."""
    picked = shape.pick(columns, rows)
    facts = [Fact("row_count", "Satır sayısı", len(rows), fmt.tr_number(len(rows)))]
    for index in picked["number"]:
        facts += _column_facts(columns, rows, index, picked["category"], picked["date"])
    return facts


def _column_facts(columns, rows, index, category, dates):
    """Tek sayı kolonunun özetleri; kolonun tamamı maskeliyse buraya zaten gelinmez."""
    column = columns[index]
    cells = [(row, _number(row[index])) for row in rows]
    filled = [(row, value) for row, value in cells if value is not None]
    numbers = [value for _, value in filled]
    total = sum(numbers)
    highest = max(filled, key=_value_of)
    lowest = min(filled, key=_value_of)
    mean = round(total / len(numbers), MEAN_DECIMALS)

    facts = [
        _number_fact("total", "Toplam", column, total),
        _number_fact("max", _row_label(highest[0], category, dates), column, highest[1]),
        _number_fact("min", "En düşük", column, lowest[1]),
        Fact("mean", "Ortalama", mean, fmt.tr_number(mean, MEAN_DECIMALS), column),
    ]
    if category is not None:
        facts += _share(filled, column, total, category)
    facts += _periods(rows, index, column, dates)
    return facts


def _share(filled, column, total, category):
    """En kalem ve payı: negatif değer ya da sıfır toplamda payın anlatılacak bir şeyi yoktur."""
    if not all(value >= 0 for _, value in filled) or total <= 0:
        return []
    # ASSUMPTION: PLAN koşumu yalnız top_share'a bağlıyor; top_item de aynı koşumda yazılır,
    # aksi halde payı olmayan bir "en çok" ekranda asılı durur.
    top_row, top_value = max(filled, key=_value_of)
    item = _text(top_row[category])
    share = round(top_value / total * 100, fmt.PERCENT_DECIMALS)
    return [
        Fact("top_item", "Öne çıkan", item, item, column),
        Fact("top_share", "En yüksek pay", share, fmt.tr_percent(share), column, percent=True),
    ]


def _periods(rows, index, column, dates):
    """Son iki dönemin değeri ve değişimi: tarih kolonuna göre sıralanınca sondaki iki satır."""
    if not dates:
        return []
    # ASSUMPTION: dönem olguları her sayı kolonu için ilk tarih kolonu üzerinden okunur.
    date = dates[0]
    ordered = sorted(
        (row for row in rows if _number(row[index]) is not None),
        key=lambda row: _period_key(row[date]),
    )
    if len(ordered) < 2 or ordered[-1][date] == ordered[-2][date]:
        return []

    previous, last = ordered[-2], ordered[-1]
    previous_value = _number(previous[index])
    last_value = _number(last[index])
    change = last_value - previous_value
    facts = [
        _number_fact("last_period", f"Son dönem ({_text(last[date])})", column, last_value),
        _number_fact("previous_period", f"Önceki dönem ({_text(previous[date])})", column, previous_value),
        _number_fact("change", "Değişim", column, change),
    ]
    if previous_value:
        pct = round(change / previous_value * 100, fmt.PERCENT_DECIMALS)
        facts.append(Fact("change_pct", "Değişim oranı", pct, fmt.tr_percent(pct), column, percent=True))
    return facts


def _number_fact(name, label, column, value) -> Fact:
    return Fact(name, label, value, fmt.tr_number(value), column)


def _row_label(row, category, dates, word: str = "En yüksek") -> str:
    """Ucun ait olduğu satırın adı: kategori hücresi, yoksa tarih hücresi (PLAN R5-7)."""
    # ASSUMPTION: PLAN etiketi "satırın kategori ya da tarih hücresi" diye veriyor; hangi özet
    # olduğu anlaşılsın diye Türkçe sözcük hücreyle birlikte yazılır: "En yüksek (Çay)".
    index = category if category is not None else (dates[0] if dates else None)
    if index is None or row[index] is None:
        return word
    return f"{word} ({_text(row[index])})"


def _number(value) -> float | None:
    """Hücrenin sayısal okunuşu; NULL, maskeli metin ve bool sayı değildir, atlanır."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    return float(value)


def _period_key(value):
    """Sıralama anahtarı: ISO metin kendi içinde, tam sayı dönem (AY 9 < 10) kendi içinde sıralanır."""
    number = _number(value)
    return (0, number, "") if number is not None else (1, 0.0, _text(value))


def _text(value) -> str:
    return "" if value is None else str(value)


def _value_of(item):
    return item[1]
