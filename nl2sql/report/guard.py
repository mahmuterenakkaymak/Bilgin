"""Sayı bekçisi: anlatının sayıları sonuçta yoksa cümle geçmez (PLAN R5-8, Contracts GuardResult).

Bekçi sayı uydurmaz, karşılaştırır: anlatıda geçen her sayının sonucun hücrelerinde, olgularında
ya da sorusunda bir karşılığı olmak zorundadır. Karşılık birebir eşitlik değildir — gösterilen son
basamağın yarısı kadar tolerans vardır (config.NUMBER_TOLERANCE_UNITS); aksi halde "12,5 bin" doğru
bir okuma olduğu hâlde reddedilirdi. Yüzde yüzde olgusuna denk düşer: sonuçta %12,3 yoksa anlatının
%13'ü uydurmadır. Biçim de sayı kadar kesindir: `1,234.56` ve `12.5` İngilizce yazımdır, Türkçe
ekrana çıkmaz; `STK001` ise sayı değil koddur, hiç sorulmaz.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from nl2sql import config

_SCALES = {"bin": 1e3, "milyon": 1e6, "milyar": 1e9}

# Türkçe binlik ayıracı: ilk küme 1-3 basamak, sonraki her küme tam üç. `12.5` bu yüzden geçmez.
_TURKISH = re.compile(r"\d+|\d{1,3}(?:\.\d{3})+")

# Aday sayı: işaret ve imleç sayının önünde, ölçek sözcüğü ardından. `(?<!\w)` harfe yapışık sayıyı
# (STK001, Q3) baştan eler; ölçek sözcüğü tutmazsa sayı yine de tek başına alınır.
_CANDIDATE = re.compile(
    r"(?<!\w)(?P<sign>-)?(?P<percent>%)?(?P<core>\d[\d.,]*)(?:[ \t]*(?P<scale>bin|milyon|milyar))?",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class NumberToken:
    """Yazıdaki tek sayı: ham yazımı, okunduğu değer, gösterilen basamak sayısı ve ölçeği."""

    raw: str
    value: float | None = None
    decimals: int = 0
    scale: float = 1.0
    percent: bool = False
    format_error: bool = False


@dataclass(frozen=True)
class GuardResult:
    """Cümlenin hükmü: geçen sayıların listesi değil, geçmeyenlerin ham yazımları (Contracts)."""

    ok: bool
    offending: list[str]
    numbers: list[NumberToken]


def extract_numbers(text: str) -> list[NumberToken]:
    """Yazıdaki sayılar, metin sırasıyla: Türkçe biçimler, yüzdeler ve ölçek sözcükleriyle."""
    tokens = []
    for match in _CANDIDATE.finditer(text or ""):
        token = _token(text, match)
        if token is not None:
            tokens.append(token)
    return tokens


def allowed_values(columns: list[str], rows: list[tuple], facts, question: str) -> dict:
    """İzin listesi: hücrelerin sayıları, metin içindeki tam sayılar, ISO tarihin parçaları, satır
    sayısı, olgular ve sorunun kendi sayıları; yüzdeler ayrı havuzda (PLAN R5-8)."""
    # ASSUMPTION: columns sözleşme gereği imzada durur; izin listesi hücrelerden okunur, kolon
    # adlarından sayı uydurulmaz.
    values: list[float] = [len(rows)]
    percents: list[float] = []
    for row in rows:
        for cell in row:
            values.extend(_cell_numbers(cell))
    for fact in facts or []:
        value = _field(fact, "value")
        if _is_number(value):
            (percents if _field(fact, "percent") else values).append(float(value))
    for token in extract_numbers(question or ""):
        if token.value is not None:
            (percents if token.percent else values).append(token.value)
    return {"values": values, "percent": percents}


def check_text(text: str, allowed: dict) -> GuardResult:
    """Cümledeki her sayı izin listesinde olmak zorundadır; uymayanlar metin sırasıyla yazılır."""
    numbers = extract_numbers(text)
    offending = [token.raw for token in numbers if not _matches(token, allowed)]
    return GuardResult(ok=not offending, offending=offending, numbers=numbers)


def _token(text: str, match) -> NumberToken | None:
    """Adayın okunuşu; cümle noktası sayıya dahil değildir, harfe yapışık dize hiç sayı değildir."""
    core = match.group("core").rstrip(".,")
    following = text[match.start("core") + len(core) :][:1]
    if not core or following.isalpha():
        return None
    sign = match.group("sign")
    percent = match.group("percent") is not None
    scale_text = match.group("scale")
    raw = f"{sign or ''}{'%' if percent else ''}{core}"
    if scale_text:
        raw += f" {scale_text}"
    parsed = _parse(core)
    if parsed is None:
        return NumberToken(raw, percent=percent, format_error=True)
    value, decimals = parsed
    scale = _SCALES[scale_text.lower()] if scale_text else 1.0
    return NumberToken(raw, (-value if sign else value) * scale, decimals, scale, percent)


def _parse(core: str) -> tuple[float, int] | None:
    """Türkçe yazımın okunuşu: ondalık virgül, binlik ayıracı nokta; İngilizce biçim None döner."""
    head, comma, fraction = core.partition(",")
    if comma and not fraction.isdigit():
        return None
    if not _TURKISH.fullmatch(head):
        return None
    return float(head.replace(".", "") + (f".{fraction}" if fraction else "")), len(fraction)


def _matches(token: NumberToken, allowed: dict) -> bool:
    """Yarım basamak tolerans: gösterilen son basamağın yarısı, ölçek kadar büyütülür (PLAN R5-8)."""
    if token.format_error or token.value is None:
        return False
    pool = allowed["percent"] if token.percent else allowed["values"]
    tolerance = config.NUMBER_TOLERANCE_UNITS * 10.0**-token.decimals * token.scale
    return any(abs(token.value - float(value)) <= tolerance for value in pool)


def _cell_numbers(value) -> list[float]:
    """Hücrenin izin verdiği sayılar: sayısal hücre kendi değeri, metin hücresinin tam sayıları ve
    ISO tarihinin yıl/ay/günü (metnin içindeki sayılar olarak okunur)."""
    if value is None or isinstance(value, bool):
        return []
    if _is_number(value):
        return [float(value)]
    if not isinstance(value, str):
        return []
    return [token.value for token in extract_numbers(value) if token.value is not None and token.value.is_integer()]


def _field(fact, name: str):
    """Olgu hem Fact nesnesinden hem payload sözlüğünden okunur (Contracts Fact)."""
    return fact.get(name) if isinstance(fact, dict) else getattr(fact, name, None)


def _is_number(value) -> bool:
    return isinstance(value, (int, float, Decimal)) and not isinstance(value, bool)
