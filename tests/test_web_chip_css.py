# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T478: ilk ekranın örnek çipleri yer tutucu gibi duruyor (M27 zanaat 2).

``.example-chip`` ``border: 1px dashed`` + ``background: var(--bg)`` çiziliyor, kesik çizgi yalnız
``:hover``'da doluya dönüyordu — evde kesik çizgi "henüz gerçek değil" kısayolu, telefonun hover'ı
yok, soru kutusunun altındaki beş soru da ekranın tek keşif aracı
(``landing-empty-state-empty-state-390.png``). İddia kaynak CSS'te kurulur: çipin çizgisi kesik
değil ve zemni sayfanın zemni değil.
"""

import re

from nl2sql import config

STYLES = config.WEB_DIR / "src" / "styles.css"
CHIP = ".example-chip"

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


RULES = parse_rules(CSS)


def draws(selector: str, name: str) -> bool:
    """Seçicinin SON bileşeni ``name`` mi: ``.example-chip:hover`` çipi basılı hâlde çizer, ama
    sorunun kendisi çipin kendi kuralında."""
    last = re.split(r"[\s>+~]+", selector.strip())[-1]
    return last == name or last.startswith(f"{name}[") or last.startswith(f"{name}:")


def chip_rules() -> list[dict[str, str]]:
    """Çipi çizen kurallar: hover ve devre dışı hâlleri de dâhil — basılabilir bir şeyin hiçbir
    hâli kesik çizgi taşıyamaz."""
    found = [
        decls
        for selector, decls in RULES
        if any(CHIP in part for part in selector.split(","))
    ]
    assert found, f"{STYLES.name} içinde {CHIP} kuralı yok"
    return found


def base_rule() -> dict[str, str]:
    """Çipin kendi kuralı: ``.example-chip`` (sonekli hâlleri değil)."""
    bases = [
        decls
        for selector, decls in RULES
        if any(draws(part, CHIP) for part in selector.split(","))
    ]
    assert bases, f"{STYLES.name} içinde {CHIP} kuralı yok"
    return bases[0]


def test_the_chip_is_not_drawn_with_a_dashed_line():
    """Kesik çizgi taslağın/yer tutucunun işareti: sorunun kendisi basılabilir bir şey, o yüzden
    çizgisi ince tam bir çizgi. Telefonun hover'ı olmadığı için kesik çizgi orada hiç doluya
    dönmüyor."""
    assert any("border" in decls for decls in chip_rules()), f"{CHIP} çizgisiz kaldı"
    for decls in chip_rules():
        dashed = {
            prop: value
            for prop, value in decls.items()
            if prop.startswith("border") and "dashed" in value
        }
        assert not dashed, f"{CHIP} kesik çizgiyle çizilmeye devam ediyor: {dashed}"


def test_the_chip_sits_on_a_surface_not_the_page_ground():
    """Zemni sayfanın zemniyle aynı olan kutu, boşluğun üstüne yazılmış bir etiket gibi duruyor:
    çipin kendi yüzeyi olmalı."""
    background = base_rule().get("background") or base_rule().get("background-color")
    assert background, f"{CHIP} zemnini söylemiyor"
    assert "var(--bg)" not in background, f"{CHIP} sayfanın zemininde duruyor: {background}"
