"""T268: kalın sol kenarlık yuvarlak köşede kıvrılıp yazının önüne düşüyor (M19 görsel inceleme 3).

``border-left: 3px solid`` + ``border-radius``: öteki üç kenar çizgisiz kalınca tarayıcı kalın solu
köşeden geçiriyor ve ``login-deeplink-login-error-390.png``'da parola hatası
"( Kullanıcı adı ya da parola hatalı." diye okunuyor. Doğrusu ``.warnings``/``.rules-readonly``
zaten öyle: dört yanı saran 1px ton çizgisi, vurgu onun kalınlaşmış solu. İddia kaynak CSS'te
kurulur - ölçülen yazarın niyeti, küçültücünün metni değil.
"""

import re

from nl2sql import config

STYLES = config.WEB_DIR / "src" / "styles.css"
SIDES = ("top", "right", "bottom", "left")


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def parse_rules(css: str) -> list[tuple[str, dict[str, str]]]:
    """Yaprak kurallar: (seçiciler tek satır, bildirimler). Media kümelerinin içi de okunur.

    Gövde küme işareti taşımadığı için ``@media``/``@keyframes`` başlıkları kural sayılmaz;
    içlerindeki her kural kendi seçicisiyle ayrı satıra düşer.
    """
    out = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        decls = {}
        for chunk in match.group(2).split(";"):
            prop, sep, value = chunk.partition(":")
            if sep:
                decls[prop.strip().lower()] = value.strip().lower()
        out.append((" ".join(match.group(1).split()), decls))
    return out


CSS = strip_comments(STYLES.read_text(encoding="utf-8"))
RULES = parse_rules(CSS)
VARS = {
    name: value
    for selector, decls in RULES
    if ":root" in selector
    for name, value in decls.items()
    if name.startswith("--")
}


def px(value: str) -> float:
    """Uzunluğu px'e çevirir: ``var(--space)`` kökten çözülür, ``calc(<uzunluk> * <sayı>)`` hesaplanır."""
    value = re.sub(
        r"var\(\s*(--[\w-]+)\s*\)", lambda m: VARS.get(m.group(1), ""), value.strip().lower()
    )
    calc = re.fullmatch(r"calc\(\s*([\d.]+)px?\s*\*\s*([\d.]+)\s*\)", value)
    if calc:
        return float(calc.group(1)) * float(calc.group(2))
    plain = re.fullmatch(r"([\d.]+)px", value)
    if plain:
        return float(plain.group(1))
    raise AssertionError(f"px'e çevrilemeyen değer: {value!r}")


def split_value(value: str) -> list[str]:
    """Boşluktan böler ama parantez dibine inmez: ``calc(...)`` tek parça kalır."""
    parts, depth, current = [], 0, ""
    for char in value:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == " " and depth == 0:
            if current:
                parts.append(current)
                current = ""
            continue
        current += char
    if current:
        parts.append(current)
    return parts


def accent_width(decls: dict[str, str]) -> float | None:
    """Kalın sol kenarlığın genişliği: ``border-left-width`` ya da ``border-left`` kısayolundan."""
    raw = decls.get("border-left-width")
    if raw is None:
        shorthand = decls.get("border-left", "")
        raw = next((t for t in split_value(shorthand) if re.fullmatch(r"[\d.]+px", t)), "")
    return px(raw) if raw else None


def padding_left(decls: dict[str, str]) -> float | None:
    """Sol iç boşluk: ``padding-left`` yoksa ``padding`` kısayolunun dördüncü yanı."""
    raw = decls.get("padding-left")
    if raw is None:
        raw = decls.get("padding")
        if raw is None:
            return None
        parts = split_value(raw)
        raw = parts[{1: 0, 2: 1, 3: 1, 4: 3}[len(parts)]]
    return px(raw)


def has_four_sides(decls: dict[str, str]) -> bool:
    """Dört yan da çizgili mi: ``border`` kısayolu ya da dört kenarın kısayolunun hepsi."""
    return "border" in decls or all(f"border-{side}" in decls for side in SIDES)


def accent_rules() -> list[tuple[str, dict[str, str], float]]:
    """1px'den kalın sol kenarlık taşıyan kurallar: (seçiciler, bildirimler, vurgunun px'i)."""
    found = [
        (selector, decls, width)
        for selector, decls in RULES
        if (width := accent_width(decls)) is not None and width > 1.0
    ]
    assert found, f"{STYLES.name} içinde kalın sol kenarlık taşıyan kural kalmadı"
    return found


def test_a_wide_accent_is_always_a_full_border():
    """Vurgu, dört yanı saran çizginin kalınlaşmış solu olmalı: üç yanı boş bırakılan sol,
    ``border-radius`` ile köşeden kıvrılıp ilk harfin önüne parantez gibi düşüyor."""
    for selector, decls, width in accent_rules():
        borders = sorted(key for key in decls if key.startswith("border"))
        assert has_four_sides(decls), (
            f"{selector}: border-left {width}px ama dört yan çizgili değil: {borders}"
        )


def test_the_accent_stays_clear_of_the_text():
    """Sol iç boşluk vurgudan geniş kalmalı: aksi hâlde kalın çizgi yazıya yapışıyor."""
    for selector, decls, width in accent_rules():
        left = padding_left(decls)
        assert left is not None, f"{selector}: sol iç boşluk yok, {width}px vurgu yazıya değer"
        assert left > width, (
            f"{selector}: padding-left {left}px, {width}px vurgunun altında kalıyor"
        )
