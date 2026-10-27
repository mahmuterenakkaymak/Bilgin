"""Sayı bekçisi: anlatının sayıları sonuçta yoksa cümle geçmez (PLAN R5-8, Contracts GuardResult).

Bekçi sayı uydurmaz, karşılaştırır: anlatıda geçen her sayının sonucun hücrelerinde, olgularında
ya da sorusunda bir karşılığı olmak zorundadır. Karşılık birebir eşitlik değildir — gösterilen son
basamağın yarısı kadar tolerans vardır (config.NUMBER_TOLERANCE_UNITS); aksi halde "12,5 bin" doğru
bir okuma olduğu hâlde reddedilirdi. Yüzde yüzde olgusuna denk düşer: sonuçta %12,3 yoksa anlatının
%13'ü uydurmadır. Biçim de sayı kadar kesindir: `1,234.56` ve `12.5` İngilizce yazımdır, Türkçe
ekrana çıkmaz; `STK001` ise sayı değil koddur, hiç sorulmaz.

Bekçi cümlenin hangi dilde yazıldığını da bilir (R8-7): `extract_numbers(text, lang)` ve
`check_text(..., lang)` İngilizce tarafında `1,234.56`, `1234.56`, `12.3%`, `-12.3%` ve ölçekli
`12.5K` / `12.5 million` okur — `fmt.format_compact`'ın kendi yazdığı bitişik K/M/B da ölçektir.
Öteki dilin biçimindeki sayı yabancıdır: değeri doğru olsa bile hiç eşleşmez ve geçmeyenlerin
arasında yazar. Türkçe tarafının okunuşu dünle bayt bayt aynıdır: `12K` Türkçede hâlâ sayı değildir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from nl2sql import config

_SCALES = {"bin": 1e3, "milyon": 1e6, "milyar": 1e9}
# İngilizce ölçek (R8-7): `fmt.format_compact`'ın bitişik kısaltması ve ölçek sözcükleri. Türkçe
# sözcükler de taşınır — İngilizce cümlede ikisi de okunur, Türkçe cümlede yalnız kendi sözcükleri.
_EN_SCALES = {**_SCALES, "k": 1e3, "m": 1e6, "b": 1e9, "thousand": 1e3, "million": 1e6, "billion": 1e9}

# Türkçe binlik ayıracı: ilk küme 1-3 basamak, sonraki her küme tam üç. `12.5` bu yüzden geçmez.
_TURKISH = re.compile(r"\d+|\d{1,3}(?:\.\d{3})+")

# İngilizce yazım: virgüllü küme ya da ondalık nokta, ikisi karışık değil. `1.234,56` ve `12,3`
# (virgülden sonra tam üç basamak değil) bu yüzden İngilizcede okunmaz.
_ENGLISH = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")

# Aday sayı: işaret ve Türkçe yüzde imleci sayının önünde, İngilizce imleç, bitişik ölçek harfi ve
# ölçek sözcüğü ardından. `(?<!\w)` harfe yapışık sayıyı (STK001, Q3) baştan eler; ölçek tutmazsa
# sayı yine de tek başına alınır. Ölçek harfi İngilizcede okunur (`12.5K`), Türkçede yoksayılır.
_CANDIDATE = re.compile(
    r"(?<!\w)(?P<sign>-)?(?P<percent>%)?(?P<core>\d[\d.,]*)(?P<tail>%)?(?P<compact>[KMB])?"
    r"(?:[ \t]*(?P<scale>bin|milyon|milyar|thousand|million|billion))?",
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


def extract_numbers(text: str, lang: str = "tr") -> list[NumberToken]:
    """Yazıdaki sayılar, metin sırasıyla: dilin biçimleriyle, yüzdeler ve ölçek sözcükleriyle;
    öteki dilin biçimi `format_error` ile işaretli gelir."""
    tokens = []
    for match in _CANDIDATE.finditer(text or ""):
        token = _token(text, match, lang)
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


def check_text(text: str, allowed: dict, lang: str = "tr") -> GuardResult:
    """Cümledeki her sayı izin listesinde olmak zorundadır; uymayanlar ve yabancı biçimli olanlar
    metin sırasıyla yazılır."""
    numbers = extract_numbers(text, lang)
    # ASSUMPTION: Contracts'ın "rejected"i GuardResult.offending'dir; yabancı biçim de oraya yazar.
    offending = [token.raw for token in numbers if not _matches(token, allowed)]
    return GuardResult(ok=not offending, offending=offending, numbers=numbers)


def _token(text: str, match, lang: str) -> NumberToken | None:
    """Adayın okunuşu; cümle noktası sayıya dahil değildir, harfe yapışık dize hiç sayı değildir."""
    scales = _EN_SCALES if lang == "en" else _SCALES
    core = match.group("core").rstrip(".,")
    # ASSUMPTION: bitişik ölçek harfi yalnız İngilizcede ve rakama yapışık okunur; ardına bir harf
    # daha gelirse ("10kg") yapışık dize sayı değildir. Türkçe taraf harfi hiç görmez.
    compact = match.group("compact") if lang == "en" else None
    scale_text = match.group("scale")
    if scale_text and scale_text.lower() not in scales:
        scale_text = None
    following = text[match.start("core") + len(core) + (1 if compact else 0) :][:1]
    if not core or following.isalpha():
        return None
    sign = match.group("sign")
    # ASSUMPTION: yüzde imleci dilin kendi tarafındadır (tr "%12,3", en "12.3%"); Türkçede sonda
    # duran imleç bugünkü gibi sayının parçası değildir. Ölçek sözcüğü iki dilde de aynı okunur.
    percent = match.group("percent") is not None or (lang == "en" and match.group("tail") is not None)
    raw = f"{sign or ''}{'%' if match.group('percent') else ''}{core}"
    if lang == "en" and match.group("tail"):
        raw += "%"
    if compact:
        raw += compact
    if scale_text:
        raw += f" {scale_text}"
    parsed = _parse(core, lang)
    if parsed is None:
        return NumberToken(raw, percent=percent, format_error=True)
    value, decimals = parsed
    if compact:
        scale = scales[compact.lower()]
    else:
        scale = scales[scale_text.lower()] if scale_text else 1.0
    return NumberToken(raw, (-value if sign else value) * scale, decimals, scale, percent)


def _parse(core: str, lang: str) -> tuple[float, int] | None:
    """Yazımın okunuşu: Türkçe ondalık virgül ve binlik nokta, İngilizce tam tersi; öteki dilin
    biçimi bu dilde yabancıdır, None döner."""
    if lang == "en":
        if not _ENGLISH.fullmatch(core):
            return None
        head, _, fraction = core.partition(".")
        return float(head.replace(",", "") + (f".{fraction}" if fraction else "")), len(fraction)
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
