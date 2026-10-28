"""Grafiğin kendisi: hangi sonucun hangi grafiği çizdiği (PLAN R5-6, Contracts ChartSpec).

Tür büyük ölçüde dönen kolonlardan okunur; sorunun sözcükleri yalnız pay ve saçılım kararında
söz sahibidir. Grafik çıkmayacaksa None döner — arayüz uydurma bir grafik çizmez. Option düz
JSON'dur: işlev taşıyamayacağı için sayı biçimi ``bilgin`` bloğunun adıyla anlatılır.
Maske burada yeniden hesaplanmaz: maskeli bir kolonun hücresi metne dönmüştür, o yüzden sayı
türü değildir ve zaten eksen çıkmaz.

Grafiğin insanca cümlesi cevabın dilindendir (R8-3): reddin gerekçesi ``chart.*`` anahtarlarından
kurulur; Türkçe cümleler eskisiyle bayt bayt aynıdır.
"""

from __future__ import annotations

import json
import math
from decimal import Decimal

from nl2sql import config
from nl2sql.i18n import t
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

# Red cümlesi catalog'dan kurulur (chart.reason + chart.kind.* + chart.missing.*):
# "Bu sonuç çizgi grafiğe uygun değil: <neyin eksik olduğu>."

# Izgara boşlukları plot'un kendi payıdır: containLabel True, dönen adları bottom'un İÇİNE
# yerleştirip plot'u ezdiği için kapatıldı (M20 görsel inceleme 2). Sol boşluk o yüzden sayısal
# eksenin Türkçe biçimli etiketini (123.456,78) de tek başına tutmak zorundadır.
_GRID = {"left": 56, "right": 20, "top": 40, "bottom": 30, "containLabel": False}
# ECharts'ın interval "auto"su çakışan adları sessizce düşürür: hepsi çizilir, 45° döner. Kutu en
# dar telefon kartının payı kadardır (330px'lik .chart'ta beş kategori 66px paylaşır): 160px'lik
# kutu dönünce yanındakinin üstüne basıyordu (M24 görsel inceleme 2). Taşan ad üç noktayla kesilir,
# tüm adı tooltip taşır. Kutu küçülünce ad dikleşir — yatay izim payın altında kalır.
_CATEGORY_SHARE_PX = 64
# Payın üst sınırı en geniş kart değil en dar karttır: board kartının .chart'ı 250px ölçer
# (1366'da ~275px'lik kartın içi), o yüzden beş kategori 320px'lik ad kutusu vaat edemez — adlar
# yanındakinin üstüne basıyordu (M25 görsel inceleme 3).
BOARD_CHART_PX = 250
_CATEGORY_ROTATE = 45
_CATEGORY_LABEL = {
    "interval": 0,
    "rotate": _CATEGORY_ROTATE,
    "hideOverlap": False,
    "width": _CATEGORY_SHARE_PX,
    "overflow": "truncate",
    "lineHeight": 14,
}
# Adlar alt boşluğun dışında, onun içine çiziliyor: ad kutusunun 45° dönük düşey izimi
# (64·sin45° = 46) + tek satır (14) + eksen payı (8) — _category_bottom(64)'ün ürettiği değer.
# Pasta ve saçılımın düz ekseni bu büyümeyi almaz; ızgaranın altı her option'da gerçekten
# kullanılan ad kutusundan hesaplanır.
_CATEGORY_BOTTOM = 68


def _category_width(count: int) -> int:
    """Kategori başına ad kutusu: kategori artınca kutu küçülür, en dar kartın payını hiç aşmaz."""
    return min(_CATEGORY_SHARE_PX, BOARD_CHART_PX // count)


def _category_bottom(width: int) -> int:
    """width px'lik ad kutusunun 45° dönük düşey izimi + tek satır + eksen payı."""
    reach = width * math.sin(math.radians(_CATEGORY_ROTATE))
    return math.ceil(reach + _CATEGORY_LABEL["lineHeight"] + 8)


def chart_spec(
    columns: list[str],
    rows: list[tuple],
    question: str,
    kind: str | None = None,
    lang: str = "tr",
) -> dict | None:
    """Sonucun grafiği: {"type", "option"} ya da çizilecek bir şey yoksa None.

    ``kind`` kullanıcının istediği türdür (PLAN R7-10): sonuç biçimi onu kaldırıyorsa mevcut
    üreticiyle o tür çizilir; kaldırmıyorsa kendiliğinden seçilen tür döner ve yanına neyin eksik
    olduğunu söyleyen bir ``reason`` eklenir. "table" grafik değildir: None. ``lang`` gerekçe
    cümlesinin dilidir (R8-3); option'ın kendisi metin taşımaz, sayıları arayüz biçimlendirir.
    """
    if kind is not None:
        return _forced(columns, rows, question, kind, lang)
    return _auto(columns, rows, question)


def _auto(columns, rows, question):
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


def _forced(columns, rows, question, kind, lang):
    """İstenen tür: biçim onu kaldırıyorsa mevcut üreticiyle çizilir, kaldırmıyorsa auto + reason."""
    if kind == "table":
        return None
    spec, missing = _fit(kind, columns, rows, question)
    if spec is not None:
        return spec
    # ASSUMPTION: kendiliğinden seçilen grafik de yoksa {"type": None, "option": None} döner; arayüz
    # hiçbir şey çizmez, reason cümlesini gösterir (Contracts "chart_spec (ext.)" reason'ı taşır).
    auto = _auto(columns, rows, question) or {"type": None, "option": None}
    reason = t("chart.reason", lang, kind=t(f"chart.kind.{kind}", lang), missing=t(missing, lang))
    return dict(auto, reason=reason)


def _fit(kind, columns, rows, question):
    """İstenen türün şartı: (çizilebiliyorsa spec, çizilemiyorsa neyin eksik olduğunun anahtarı)."""
    picked = shape.pick(columns, rows)
    dates, numbers, category = picked["date"], picked["number"], picked["category"]
    # Etiket kategori yoksa tek tarih kolonudur: aylık bir sonuç hem sütun hem pasta olur.
    label = category if category is not None else (dates[0] if len(dates) == 1 else None)

    if len(rows) <= 1:
        return None, "chart.missing.rows"
    if kind == "line":
        if not dates:
            return None, "chart.missing.date"
        if len(dates) > 1:
            return None, "chart.missing.dates"
        if not numbers:
            return None, "chart.missing.number"
        if len(numbers) > 3:
            return None, "chart.missing.numbers"
        return _line(columns, rows, dates[0], numbers, question), None
    if not numbers:
        return None, "chart.missing.number"
    if label is None:
        return None, "chart.missing.label"
    if kind == "bar":
        return _bar(columns, rows, label, numbers[0], question), None
    if len(rows) > config.CHART_PIE_MAX_PARTS:
        return None, "chart.missing.slices"
    if not all(_positive(row[numbers[0]]) for row in rows):
        return None, "chart.missing.positive"
    return _pie(columns, rows, label, numbers[0], question), None


def validate_option(option) -> list[str]:
    """Option'un ECharts için hazır ve düz JSON olduğunu doğrular: sorun listesi, [] temiz demek."""
    if not isinstance(option, dict):
        return [_problem("not_object")]
    series = option.get("series")
    if not isinstance(series, list) or not series:
        return [_problem("no_series")]

    problems = []
    for item in series:
        kind = item.get("type") if isinstance(item, dict) else None
        if kind not in SERIES_TYPES:
            problems.append(_problem("series_type", kind=kind))

    if any(_type_of(item) in CARTESIAN_TYPES for item in series):
        for axis in ("xAxis", "yAxis"):
            if not isinstance(option.get(axis), dict):
                problems.append(_problem("axis_missing", axis=axis))

    axis = option.get("xAxis")
    if isinstance(axis, dict) and axis.get("type") == "category":
        count = len(axis.get("data") or [])
        for item in series:
            data = item.get("data") if isinstance(item, dict) else None
            if isinstance(data, list) and len(data) != count:
                problems.append(_problem("category_length", count=count, length=len(data)))

    for item in series:
        if _type_of(item) != "pie":
            continue
        for point in item.get("data") or []:
            if not isinstance(point, dict) or "name" not in point or "value" not in point:
                problems.append(_problem("pie_point"))

    for value in _numbers(option):
        if not math.isfinite(value):
            problems.append(_problem("not_finite", value=value))
            break

    try:
        json.loads(json.dumps(option, allow_nan=False))
    except (TypeError, ValueError):
        problems.append(_problem("not_json"))
    return problems


def _problem(key: str, **params) -> str:
    """Doğrulama satırı: ekrana çıkmaz, yalnız tanıyı üreten okur (R8-3 "Stay"). Türkçe sabittir —
    cümleler testlerde birebir karşılaştırılır; catalog'daki İngilizcesi hazır durur."""
    return t(f"chart.problem.{key}", "tr", **params)


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
    # Ad, dilimin kendi çizgisiyle dışında okunur: kaydırmalı açıklama telefon genişliğinde beş adın
    # ikisini "1/5" sayfalayıcısının arkasına atıyordu (M24 görsel inceleme 2). Dilim küçülüp yerini
    # etiketlere bırakır; uzun ad sarar.
    # Dış etiketin çakışma kuralı yoktu: beş ad yanındakinin üstüne basıp "62"yi tek başına bırakıyordu
    # (M28 görsel inceleme 2). shiftY çakışanı düşeyde kaydırır; ızgaranın altı da kayan adların payı
    # kadar büyür — aynı kategori sayısının sütunda aldığı alt boşluk kadar.
    # ASSUMPTION: pastanın ekseni yok, ızgara burada yalnız adların altına kalan payı anlatır.
    series = [
        {
            "type": "pie",
            "name": columns[number],
            "radius": "40%",
            "center": ["50%", "44%"],
            "label": {"show": True, "width": 76, "overflow": "break", "lineHeight": 14},
            "labelLayout": {"moveOverlap": "shiftY"},
            "labelLine": {"show": True, "length": 10, "length2": 6},
            "data": [{"name": _label(row[category]), "value": _value(row[number])} for row in rows],
        }
    ]
    bottom = _category_bottom(_category_width(len(rows)))
    option = {"tooltip": {"trigger": "item"}, "grid": dict(_GRID, bottom=bottom), "series": series}
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
    width = _category_width(len(labels))
    return {
        "tooltip": {"trigger": trigger},
        "grid": dict(_GRID, bottom=_category_bottom(width)),
        "xAxis": {"type": "category", "data": labels, "axisLabel": dict(_CATEGORY_LABEL, width=width)},
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
