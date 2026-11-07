# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

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


# M20 görsel inceleme 7'nin gördüğü bantlar: cümlesini kullanıcıya söyleyenler.
BANDS = {
    ".warnings",
    ".rules-readonly",
    ".login-note",
    ".login-error",
    ".route-note",
    ".users-error",
    ".map-error",
    ".map-errors-wrap",
    ".rule-errors",
}


def selector_classes(selector: str) -> set[str]:
    """Kuralın seçiciler listesindeki sınıf adları: ``.gate > .login-error, .route-note``."""
    return {
        token for part in selector.split(",") for token in part.split() if token.startswith(".")
    }


def effective_decls(name: str) -> dict[str, str]:
    """Bir bandın CSS'teki son hâli: onu listeleyen her kuralın bildirimleri sırayla üstüne
    biner — şekli taşıyan ortak kural ile rengini taşıyan kendi kuralı birlikte okunur."""
    decls: dict[str, str] = {}
    for selector, rule in RULES:
        if name in selector_classes(selector):
            decls.update(rule)
    return decls


def corner(value: str) -> float:
    """Köşe yarıçapı: ``0`` birimsiz de yazılıyor, ``px`` ondan önce ``0px`` istiyor."""
    return px("0px" if value.strip() == "0" else value)


def left_corner_radii(decls: dict[str, str]) -> tuple[float, float]:
    """Kalın sol kenarlığın bastığı iki köşe: ``border-radius`` kısayolunun ilk ve son yanı
    (dikey bileşen eğriyi değiştirmez); uzun biçimler tek başına da yazılabiliyor."""
    raw = decls.get("border-radius")
    if raw is None:
        return (
            corner(decls.get("border-top-left-radius", "0")),
            corner(decls.get("border-bottom-left-radius", "0")),
        )
    parts = split_value(raw.split("/")[0])
    assert parts, "border-radius boş yazılmış"
    return corner(parts[0]), corner(parts[{1: 0, 2: 1, 3: 1, 4: 3}[len(parts)]])


def test_the_accent_never_bends_around_a_corner():
    """Kalın sol kenarlık yuvarlak köşeden inemez: tarayıcı 4px'lik vurguyu köşenin eğrisine
    oturtunca bant, ilk harfin önüne düşen bir ``(``e dönüşüyor — dört yanı saran çizgi
    (T268'in istediği) eğriyi taşımıyordu, ``login-deeplink-login-error-390.png`` ve
    ``user-readonly-rules-rules-as-user-1366.png`` o yüzden hâlâ parantezliydi. Vurgu
    köşeden çıkmak zorunda: kalın solun bastığı iki köşe kare kalır, ya da vurgu
    kenarlık olmaktan çıkar."""
    for name in sorted(BANDS):
        decls = effective_decls(name)
        assert decls, f"{name}: {STYLES.name} içinde kuralı yok"
        width = accent_width(decls)
        # ASSUMPTION: vurgu kenarlıktan çıkmışsa (iç gölge) köşe eğrisinin zararı kalmıyor;
        # bu kural o durumda bakacak bir şey aramıyor.
        if width is None or width <= 1.0:
            continue
        top, bottom = left_corner_radii(decls)
        assert top == 0.0 and bottom == 0.0, (
            f"{name}: {width}px sol vurgu yuvarlak köşeye değiyor (üst {top}px, alt "
            f"{bottom}px) — köşeyi dolanıp ilk harfin önüne \"(\" gibi düşüyor"
        )
