"""Grafiğin kendisi: hangi sonucun hangi grafiği çizdiği (PLAN R5-6, Contracts ChartSpec).

Tür büyük ölçüde dönen kolonlardan okunur; sorunun sözcükleri yalnız pay ve saçılım kararında
söz sahibidir. Grafik çıkmayacaksa None döner — arayüz uydurma bir grafik çizmez. Option düz
JSON'dur: işlev taşıyamayacağı için Türkçe sayı biçimi ``bilgin`` bloğunun adıyla anlatılır.
Maske burada yeniden hesaplanmaz: maskeli bir kolonun hücresi metne dönmüştür, o yüzden sayı
türü değildir ve zaten eksen çıkmaz.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal

from nl2sql import config
from nl2sql.report import shape

SERIES_TYPES = ("line", "bar", "pie", "scatter")
CARTESIAN_TYPES = ("line", "bar", "scatter")

# Adlar ASCII'ye katlanarak karşılaştırılır: soru da kolon adı da aynı sözlükle küçültülür.
_FOLD = str.maketrans("çÇğĞıİöÖşŞüÜ", "CCGGIIOOSSUU")
_SHARE_WORDS = ("pay", "oran", "yuzde", "dagilim", "share", "pasta")
_SCATTER_WORDS = ("iliski", "korelasyon", "sacilim", "scatter")
# ASSUMPTION: PLAN value_format'un ne zaman "percent" olacağını vermiyor; oran/yüzde sözcüğü
# değer kolonunun adında ya da soruda geçiyorsa yüzde, değilse sayı.
_PERCENT_WORDS = ("oran", "yuzde", "percent", "ratio")

# Izgara boşlukları plot'un kendi payıdır: containLabel True, dönen adları bottom'un İÇİNE
# yerleştirip plot'u ezdiği için kapatıldı (M20 görsel inceleme 2). Sol boşluk o yüzden sayısal
# eksenin Türkçe biçimli etiketini (123.456,78) de tek başına tutmak zorundadır.
_GRID = {"left": 56, "right": 20, "top": 40, "bottom": 30, "containLabel": False}
# ECharts'ın interval "auto"su çakışan adları sessizce düşürür: hepsi çizilir, 30° döner.
# Kutu altın cevabın en uzun adının (21 karakter) üstünde: ad üç noktayla kesilmez, sığmazsa sarar.
_CATEGORY_LABEL = {
    "interval": 0,
    "rotate": 30,
    "hideOverlap": False,
    "width": 160,
    "overflow": "break",
    "lineHeight": 14,
}
# Adlar artık alt boşluğun dışında, onun içine çiziliyor: 160px'lik ad kutusunun 30° dönük düşey
# izimi (160·sin30° = 80) + iki satır (2·14) + eksen payı (8). Pasta ve saçılımın düz ekseni bu
# büyümeyi almaz.
_CATEGORY_BOTTOM = 116


def chart_spec(columns: list[str], rows: list[tuple], question: str) -> dict | None:
    """Sonucun grafiği: {"type", "option"} ya da çizilecek bir şey yoksa None."""
    if len(rows) <= 1:
        return None
    picked = shape.pick(columns, rows)
    dates, numbers, category = picked["date"], picked["number"], picked["category"]

    if len(dates) == 1 and 1 <= len(numbers) <= 3:
        return _line(columns, rows, dates[0], numbers, question)
    if category is not None and len(numbers) == 1 and len(rows) <= config.CHART_BAR_MAX_ROWS:
        values = [row[numbers[0]] for row in rows]
        if _shares(question) and len(rows) <= config.CHART_PIE_MAX_PARTS and all(_positive(v) for v in values):
            return _pie(columns, rows, category, numbers[0], question)
        return _bar(columns, rows, category, numbers[0], question)
    if len(numbers) == 2 and not dates and _scatters(question):
        return _scatter(columns, rows, numbers, question)
    return None


def validate_option(option) -> list[str]:
    """Option'un ECharts için hazır ve düz JSON olduğunu doğrular: sorun listesi, [] temiz demek."""
    if not isinstance(option, dict):
        return ["Seçenek bir nesne değil."]
    series = option.get("series")
    if not isinstance(series, list) or not series:
        return ["Seri yok: çizilecek bir veri dizisi bulunmuyor."]

    problems = []
    for item in series:
        kind = item.get("type") if isinstance(item, dict) else None
        if kind not in SERIES_TYPES:
            problems.append(f"Bilinmeyen seri türü: {kind}")

    if any(_type_of(item) in CARTESIAN_TYPES for item in series):
        for axis in ("xAxis", "yAxis"):
            if not isinstance(option.get(axis), dict):
                problems.append(f"Eksik eksen: {axis}")

    axis = option.get("xAxis")
    if isinstance(axis, dict) and axis.get("type") == "category":
        count = len(axis.get("data") or [])
        for item in series:
            data = item.get("data") if isinstance(item, dict) else None
            if isinstance(data, list) and len(data) != count:
                problems.append(f"Kategori sayısı {count}, seri uzunluğu {len(data)}")

    for item in series:
        if _type_of(item) != "pie":
            continue
        for point in item.get("data") or []:
            if not isinstance(point, dict) or "name" not in point or "value" not in point:
                problems.append("Pasta diliminde ad ya da değer eksik")

    for value in _numbers(option):
        if not math.isfinite(value):
            problems.append(f"Sonlu olmayan sayı: {value}")
            break

    try:
        json.loads(json.dumps(option, allow_nan=False))
    except (TypeError, ValueError):
        problems.append("Seçenek düz JSON olarak yazılıp okunamıyor")
    return problems


def _line(columns, rows, date, numbers, question):
    # Tür dolu hücrelerden okunur: NULL dönem çizgiye ulaşabilir, o yüzden sıralamada sonda kalır.
    ordered = sorted(rows, key=lambda row: (row[date] is None, row[date]))
    series = [
        {"type": "line", "name": columns[index], "data": [_value(row[index]) for row in ordered]}
        for index in numbers
    ]
    option = _cartesian("axis", [_label(row[date]) for row in ordered], series)
    return _spec("line", option, columns[numbers[0]], columns[date], question)


def _bar(columns, rows, category, number, question):
    ordered = sorted(rows, key=lambda row: _sortable(row[number]), reverse=True)
    series = [{"type": "bar", "name": columns[number], "data": [_value(row[number]) for row in ordered]}]
    option = _cartesian("axis", [_label(row[category]) for row in ordered], series)
    return _spec("bar", option, columns[number], columns[category], question)


def _pie(columns, rows, category, number, question):
    series = [
        {
            "type": "pie",
            "name": columns[number],
            "data": [{"name": _label(row[category]), "value": _value(row[number])} for row in rows],
        }
    ]
    option = {"tooltip": {"trigger": "item"}, "series": series}
    return _spec("pie", option, columns[number], columns[category], question)


def _scatter(columns, rows, numbers, question):
    x, y = numbers
    series = [
        {
            "type": "scatter",
            "name": columns[y],
            "data": [[_value(row[x]), _value(row[y])] for row in rows],
        }
    ]
    option = {
        "tooltip": {"trigger": "item"},
        "grid": dict(_GRID),
        "xAxis": {"type": "value"},
        "yAxis": {"type": "value"},
        "series": series,
    }
    return _spec("scatter", option, columns[y], None, question)


def _cartesian(trigger, labels, series):
    return {
        "tooltip": {"trigger": trigger},
        "grid": dict(_GRID, bottom=_CATEGORY_BOTTOM),
        "xAxis": {"type": "category", "data": labels, "axisLabel": dict(_CATEGORY_LABEL)},
        "yAxis": {"type": "value"},
        "series": series,
    }


def _spec(kind, option, value_column, label_column, question):
    option["bilgin"] = {
        "value_format": "percent" if _percent(value_column, question) else "number",
        "value_column": value_column,
        "label_column": label_column,
    }
    return {"type": kind, "option": option}


def _fold(text) -> str:
    return str(text).translate(_FOLD).lower()


def _shares(question: str) -> bool:
    return any(word in _fold(question) for word in _SHARE_WORDS)


def _scatters(question: str) -> bool:
    return any(word in _fold(question) for word in _SCATTER_WORDS)


def _percent(value_column: str, question: str) -> bool:
    return any(word in _fold(value_column) or word in _fold(question) for word in _PERCENT_WORDS)


def _positive(value) -> bool:
    return value is not None and value > 0


def _sortable(value):
    return float(value) if value is not None else float("-inf")


def _value(value):
    """JSON'un taşıdığı sayı: Decimal ondalık olarak yazılamaz, float'a döner."""
    return float(value) if isinstance(value, Decimal) else value


def _label(value) -> str:
    return "" if value is None else str(value)


def _type_of(item) -> str | None:
    return item.get("type") if isinstance(item, dict) else None


def _numbers(node):
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _numbers(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from _numbers(value)
