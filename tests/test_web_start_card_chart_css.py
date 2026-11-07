# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T366: başlangıç panosundaki grafik kutusu (M23 görsel inceleme 1).

Kartın grafiği 140px'lik kutuya başlıklı ve eğik etiketli bir opsiyon çiziyordu: başlık eksen
sayılarının üstüne basıyor, etiketler barların üstüne yığılıyordu — panodaki tek grafik okunmuyordu.
İddia kaynak CSS'te kurulur: kutunun boyu ölçülen bir tabanın (200px) altında olamaz, grafik kutuyu
``height: 100%`` ile doldurmaya devam eder ve hiçbir ``@media`` bloğu kutuyu tabanın altına
düşürmez (390px'de de okunmuyordu, yani istisna telefonda değil).
"""

import re

from bilgin import config

STYLES = config.WEB_DIR / "src" / "styles.css"
FLOOR_PX = 200.0
BOX = ".start-card-chart"
INNER = ".start-card-chart .chart"

CSS = re.sub(r"/\*.*?\*/", "", STYLES.read_text(encoding="utf-8"), flags=re.S)


def parse_rules(css: str) -> list[tuple[str, dict[str, str]]]:
    """Yaprak kurallar: (seçiciler tek satır, bildirimler). Media kümelerinin içi de okunur.

    Gövde küme işareti taşımadığı için ``@media`` başlıkları kural sayılmaz; içlerindeki her
    kural kendi seçicisiyle ayrı satıra düşer.
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


def media_spans(css: str) -> list[tuple[str, int, int]]:
    """(koşul, gövde başı, gövde sonu): küme derinliği sayılır, media bloğunun içi kural taşır."""
    spans = []
    for match in re.finditer(r"@media([^{]*)\{", css):
        depth = 0
        for index in range(match.end() - 1, len(css)):
            if css[index] == "{":
                depth += 1
            elif css[index] == "}":
                depth -= 1
                if depth == 0:
                    spans.append((match.group(1).strip(), match.end(), index))
                    break
        else:
            raise AssertionError(f"{STYLES.name}: eşleşmeyen süslü parantez")
    return spans


def base_css(css: str) -> str:
    """Media sorgularından arınmış kısım: ekran genişliğinden bağımsız temeller."""
    keep, cursor = [], 0
    for _condition, start, end in media_spans(css):
        keep.append(css[cursor:start])
        cursor = end
    keep.append(css[cursor:])
    return "".join(keep)


def draws(selector: str, name: str) -> bool:
    """Seçicinin SON bileşeni ``name`` mi: ``.start-card-chart .chart`` kutuyu değil içindeki
    grafiği çizer — kutunun boyu sorusu ona sorulmaz. ``.start-card-chart:hover`` onun bir hâlidir,
    ``.start-card-table`` değildir."""
    last = re.split(r"[\s>+~]+", selector.strip())[-1]
    return last == name or last.startswith(f"{name}[") or last.startswith(f"{name}:")


def rules_drawing(name: str, rules: list[tuple[str, dict[str, str]]]) -> list[dict[str, str]]:
    """``name``i çizen kurallar: virgülle ayrılmış seçici listelerinin her üyesi ayrı sayılır."""
    out = []
    for selector, decls in rules:
        if any(draws(part, name) for part in selector.split(",")):
            out.append(decls)
    return out


def height_px(decls: dict[str, str], where: str) -> float:
    """Kutunun boyu px olarak: ``auto``/yüzde ölçülemez bir taban vermez, taban ölçülebilmeli."""
    value = decls.get("height", "")
    match = re.fullmatch(r"([\d.]+)px", value)
    assert match, f"{where}: {BOX} yüksekliği px olarak söylenmeli, {value!r} değil"
    return float(match.group(1))


RULES = parse_rules(CSS)
BASE = parse_rules(base_css(CSS))


def test_the_chart_box_has_a_measured_floor():
    """Kutunun kendi boyu bir temel kuralda duruyor ve 200px'in altına inmiyor."""
    decls: dict[str, str] = {}
    for rule in rules_drawing(BOX, BASE):
        decls.update(rule)
    assert decls, f"{STYLES.name} içinde {BOX} kuralı yok"
    px = height_px(decls, "temel")
    assert px >= FLOOR_PX, (
        f"{BOX} yüksekliği {px:g}px; başlıklı ve eğik etiketli bir opsiyon için taban "
        f"{FLOOR_PX:g}px olmalı"
    )


def test_the_chart_fills_the_box():
    """Grafik yüksekliği kendisi seçmez: kutu büyüyünce plot da büyür (``.chart`` 280/320px'te
    kalırsa kartın kutusu boş kalır)."""
    decls: dict[str, str] = {}
    for selector, rule in RULES:
        if any(draws(part, ".chart") and BOX in part for part in selector.split(",")):
            decls.update(rule)
    assert decls, f"{STYLES.name} içinde {INNER} kuralı yok"
    assert decls.get("height") == "100%", f"{INNER} kutuyu doldurmuyor: {decls.get('height')!r}"


def test_no_media_block_shrinks_the_box():
    """Kutuyu daraltan bir ekran genişliği yok: taban her genişlikte geçerli."""
    for condition, start, end in media_spans(CSS):
        for rule in rules_drawing(BOX, parse_rules(CSS[start:end])):
            if "height" not in rule:
                continue
            px = height_px(rule, f"@media ({condition})")
            assert px >= FLOOR_PX, (
                f"@media ({condition}) {BOX} yüksekliğini {px:g}px'e indiriyor; taban "
                f"{FLOOR_PX:g}px"
            )
