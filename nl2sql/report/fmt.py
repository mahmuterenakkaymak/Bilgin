"""Türkçe sayı yazımı: ekrana çıkan her sayının tek kaynağı (PLAN R5-6, R5-7).

Değeri burası üretmez; SQL'in döndürdüğünü yalnız okunur kılar — binlik ayıracı nokta, ondalık
virgül, yüzde işareti sayının önünde. Yuvarlama yalnız gösterilir, toplanan şey değişmez. Boş
hücre "0" değil "–"dir: sıfır bir bilgidir, yokluk değil.

Aynı sayı dil anahtarıyla da yazılır (R8-7): `format_*(value, lang)` İngilizce tarafında binliği
virgülle, ondalığı nokta ile, yüzdeyi sonda, ölçeği K/M/B ile yazar. Türkçe okunuş `tr_*`
sarmalayıcılarındaki ile bayt bayt aynıdır; yokluk iki dilde de "–".
"""

from __future__ import annotations

NULL_TEXT = "–"
DECIMALS = 2
PERCENT_DECIMALS = 1
COMPACT_DECIMALS = 1
COMPACT_MIN = 10_000

_SWAP = str.maketrans(",.", ".,")
_SCALES = ((1_000_000_000, "milyar"), (1_000_000, "milyon"), (1_000, "bin"))
_SCALES_EN = ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K"))


def format_number(value, lang: str = "tr", decimals: int | None = None) -> str:
    """Sayıyı dilin okunuşuyla yazar: 1234.56 -> "1.234,56" (tr) / "1,234.56" (en), None -> "–".

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
    if lang != "en":
        text = text.translate(_SWAP)
    return text[1:] if text.startswith("-") and _only_zeros(text) else text


def format_percent(value, lang: str = "tr", decimals: int = PERCENT_DECIMALS) -> str:
    """Yüzde dilin okunuşuyla: tr "%12,3" / en "12.3%" — eksi iki dilde de sayının önünde."""
    if value is None:
        return NULL_TEXT
    if lang == "en":
        return f"{format_number(value, lang, decimals)}%"
    return f"{'-' if value < 0 else ''}%{format_number(abs(value), lang, decimals)}"


def format_compact(value, lang: str = "tr") -> str:
    """Büyük sayıyı ölçekle okunur kılar: 12500 -> tr "12,5 bin" / en "12.5K".

    COMPACT_MIN'dan küçüğü olduğu gibi sayıdır; ölçek adı Türkçede ayrı, İngilizcede bitişik yazılır.
    """
    if value is None:
        return NULL_TEXT
    size = abs(value)
    if size < COMPACT_MIN:
        return format_number(value, lang)
    scales = _SCALES_EN if lang == "en" else _SCALES
    scale, name = next(item for item in scales if size >= item[0])
    sep = "" if lang == "en" else " "
    return f"{'-' if value < 0 else ''}{format_number(size / scale, lang, COMPACT_DECIMALS)}{sep}{name}"


def tr_number(value, decimals: int | None = None) -> str:
    """Sayı Türkçe okunuşu: 1234.56 -> "1.234,56", 12345 -> "12.345", None -> "–"."""
    return format_number(value, "tr", decimals)


def tr_percent(value, decimals: int = PERCENT_DECIMALS) -> str:
    """Yüzde Türkçe: %12,3 — imleç birlikte yazılır, eksi -%1,5 olur."""
    return format_percent(value, "tr", decimals)


def tr_compact(value) -> str:
    """Büyük sayıyı ölçekle okunur kılar: 12500 -> "12,5 bin"; 10.000'dan küçüğü olduğu gibi sayı."""
    return format_compact(value, "tr")


def _only_zeros(text: str) -> bool:
    """Yuvarlama sıfıra mı indirdi: gösterilen -0, gerçek bir bilgi değildir."""
    return not any(char.isdigit() and char != "0" for char in text)
