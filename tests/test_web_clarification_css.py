# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T462: netleştirme seçeneğinin satırı basılabilir görünmüyor (M25 işçilik 2).

Üç seçenek, satırın mı yoksa ucundaki okun mu hedef olduğunu söylemeyen düz `.btn`ler
(ask-ambiguous-clarify-then-answer-clarification-card-1366.png, -390.png): hover arka planı bir
ton açıyor, ok ise satırın ucunda sabit duruyor. Doğrusu vurgunun satırın üstüne binmesi — ton +
çerçeve — ve okun birkaç px kayması; hareket "bu satır gidiyor" diyen tek şey. İddia kaynak CSS'te
kurulur - ölçülen yazarın niyeti, küçültücünün metni değil.
"""

import re

from bilgin import config

STYLES = config.WEB_DIR / "src" / "styles.css"
OPTION = ".clarification-option"
REDUCED = "prefers-reduced-motion"


def strip_comments(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def parse_rules(css: str) -> list[tuple[str, dict[str, str]]]:
    """Yaprak kurallar: (seçiciler tek satır, bildirimler). Media kümelerinin içi de okunur."""
    out = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        decls = {}
        for chunk in match.group(2).split(";"):
            prop, sep, value = chunk.partition(":")
            if sep:
                decls[prop.strip().lower()] = " ".join(value.split()).lower()
        out.append((" ".join(match.group(1).split()), decls))
    return out


CSS = strip_comments(STYLES.read_text(encoding="utf-8"))


def media_spans(css: str, condition_part: str) -> list[tuple[int, int]]:
    """Koşulu condition_part içeren @media bloklarının gövde aralıkları: küme derinliği sayılır."""
    spans = []
    for match in re.finditer(r"@media([^{]*)\{", css):
        depth = 0
        for index in range(match.end() - 1, len(css)):
            if css[index] == "{":
                depth += 1
            elif css[index] == "}":
                depth -= 1
                if depth == 0:
                    if condition_part in match.group(1):
                        spans.append((match.end(), index))
                    break
        else:
            raise AssertionError(f"{STYLES.name}: eşleşmeyen süslü parantez")
    return spans


def without_media(css: str, condition_part: str) -> str:
    """Koşulu işlemediği dünya: o bloklar çıkar, içerideki kurallar okunmaz."""
    keep, cursor = [], 0
    for start, end in media_spans(css, condition_part):
        keep.append(css[cursor : start - 1])
        cursor = end + 1
    keep.append(css[cursor:])
    return "".join(keep)


# Hareketi isteyen kurallar hareketi kapatandan ayrı okunur: ikisi aynı seçiciyi taşıyor.
LIFT_RULES = parse_rules(without_media(CSS, REDUCED))
REDUCED_RULES = [
    rule
    for start, end in media_spans(CSS, REDUCED)
    for rule in parse_rules(CSS[start:end])
]


def lifted(part: str) -> dict[str, str]:
    """Seçicisinde ``.clarification-option<part>`` taşıyan kuralların kazanan bildirimleri."""
    won: dict[str, str] = {}
    for selector, decls in LIFT_RULES:
        if f"{OPTION}{part}" in selector:
            won.update(decls)
    return won


def base_decls(selector: str) -> dict[str, str]:
    won: dict[str, str] = {}
    for selector_text, decls in LIFT_RULES:
        if selector in [part.strip() for part in selector_text.split(",")]:
            won.update(decls)
    return won


def test_the_hover_paints_the_row():
    """Vurgu satıra binmeli: çerçeve vurgu rengine, zemin vurgunun tonuna dönmeli. Yalnız yazı
    rengi değişen ya da zeminin bir ton açıldığı hover, satırı düğme değil satır gibi bırakıyor."""
    hover = lifted(":hover")
    assert hover.get("border-color", "").strip(), f"{OPTION}:hover çerçeve rengi vermiyor: {hover}"
    assert "accent" in hover["border-color"], (
        f"çerçeve vurgu rengi değil: {hover['border-color']}"
    )
    background = hover.get("background", hover.get("background-color", "")).strip()
    assert background not in ("", "none", "transparent"), (
        f"{OPTION}:hover zemini boyamıyor: {hover}"
    )
    plain = base_decls(OPTION).get("background", "")
    assert background != plain, f"{OPTION}:hover zemini zaten durduğu zemin: {background}"


def test_the_arrow_slides_with_the_row():
    """Okun kayması, hedefin satırın kendisi olduğunun tek işareti: ucda sabit duran ok,
    basılacak yerin yalnız kendisi sandırıyor. Kayma geçişle birlikte çalışmalı."""
    moved = [
        (selector, decls["transform"])
        for selector, decls in LIFT_RULES
        if f"{OPTION}:hover" in selector and decls.get("transform", "none") != "none"
    ]
    assert moved, f"{OPTION}:hover oku kaydıran kural yok — ok ucda sabit duruyor"
    selector, transform = moved[0]
    assert selector.endswith("::after"), f"ok değil, satırın kendisi kayıyor: {selector}"
    shift = re.search(r"-?[\d.]+px", transform)
    assert shift and float(shift.group(0)[:-2]) != 0.0, (
        f"transform oku oynatmıyor: {transform}"
    )
    assert "transform" in base_decls(f"{OPTION}::after").get("transition", ""), (
        "geçiş yok: ok yerinde beliriyor, kaymıyor"
    )


def test_the_keyboard_cursor_gets_the_same_lift():
    """Klavyeyle dolaşan kullanıcı fareyle gelenle aynı satırı görmeli: imleç vurgusu yalnız
    çerçeveyle sınırlı kalırsa tuşla gezinen, hangi seçeneğin üzerinde olduğunu ayırt edemez."""
    hover, focus = lifted(":hover"), lifted(":focus-visible")
    for prop in ("background", "border-color"):
        value = hover.get(prop, hover.get(f"{prop}-color", ""))
        assert value, f"{OPTION}:hover {prop} vermiyor: {hover}"
        assert focus.get(prop, focus.get(f"{prop}-color", "")) == value, (
            f"imleç {prop} konusunda hover ile uyuşmuyor: {focus}"
        )


def test_reduced_motion_stops_the_slide():
    """Hareketi istemeyen kullanıcı için kayma kapanmalı: geçişin kendisi değil, okun
    yer değiştirmesi asıl mesaj — kapandığı yerde satırın vurgusu yine de duruyor."""
    stopped = [
        selector
        for selector, decls in REDUCED_RULES
        if OPTION in selector and decls.get("transform") == "none"
    ]
    assert stopped, (
        f"{STYLES.name}: {REDUCED} bloğu okun kaymasını kapatmıyor — "
        f"hareketi istemeyene de kayıyor"
    )
