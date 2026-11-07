# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T476: telefonun pano kartı üçüncü satırı gliflerin ortasından kesiyor (M27 görsel inceleme 3).

``.start-card-table`` 140px'lik kutuya ``config.CARD_TABLE_ROWS`` satır sokuyor; 390'da 13px
hücreler iki satıra sarıyor ve üçüncü ürün adı tam ortadan kesiliyor — ne yumuşak bir sönme ne
görünür bir kaydırma çubuğu kutunun kaydırılabilir olduğunu söylüyor
(``start-purchasing-start-purchasing-cards-390.png``), aynı kart 1366'da üç satırı bütün
gösteriyor. İddia kaynak CSS'te kurulur: kutu başlık + üç sarayan satırı alacak boyda ve hâlâ
kırpıyorsa bunu söyleyen bir alt sönme taşıyor.
"""

import re

from nl2sql import config

STYLES = config.WEB_DIR / "src" / "styles.css"
BOX = ".start-card-table"
MIN_HEIGHT_PX = 180.0

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


def draws(selector: str, name: str) -> bool:
    """Seçicinin SON bileşeni ``name`` mi: ``.start-card-table th`` başlığı çizer, kutunun kendi
    boyu sorusu ona sorulmaz."""
    last = re.split(r"[\s>+~]+", selector.strip())[-1]
    return last == name or last.startswith(f"{name}[") or last.startswith(f"{name}:")


def box_rules() -> list[dict[str, str]]:
    """Kutuyu çizen kurallar: içlerinden biri tavan yüksekliğini söylüyor olmalı."""
    found = [
        decls
        for selector, decls in parse_rules(CSS)
        if any(draws(part, BOX) for part in selector.split(","))
    ]
    assert found, f"{STYLES.name} içinde {BOX} kuralı yok"
    assert any("max-height" in decls for decls in found), f"{BOX} kutusunun tavanı yok"
    return found


def max_height_px(decls: dict[str, str]) -> float:
    value = decls["max-height"]
    match = re.fullmatch(r"([\d.]+)px", value)
    assert match, f"{BOX} tavanı px olarak söylenmeli, {value!r} değil"
    return float(match.group(1))


def test_the_box_is_tall_enough_for_whole_rows():
    """Tavan, başlık artı telefonda iki satıra saran üç satırı bütün hâlde alacak kadar yüksek
    olmalı: 140px satırı yazıların ortasından biçiyordu."""
    for decls in box_rules():
        if "max-height" not in decls:
            continue
        px = max_height_px(decls)
        assert px >= MIN_HEIGHT_PX, (
            f"{BOX} tavanı {px:g}px; başlık + iki satıra sarayan üç satır için taban "
            f"{MIN_HEIGHT_PX:g}px olmalı"
        )


def test_the_box_says_when_it_still_clips():
    """Kutu kırpıyorsa son satır yumuşakça sönüyor: sönmenin kendisi kaydırılabilir kutunun
    işareti — ondan yoksun bir kesim, satırın yazı hatlarından bölünmesiyle aynı şey."""
    faded = [decls for decls in box_rules() if "max-height" in decls and "mask-image" in decls]
    assert faded, f"{BOX} tavanı kırpıldığını söylemiyor: aynı kural bloğunda mask-image yok"
