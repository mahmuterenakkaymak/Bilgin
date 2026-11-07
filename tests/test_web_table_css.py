# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T269: telefonda cevap tablosunun başlığı ortadan bölünmemeli (M19 görsel inceleme 4).

Telefon bloğu ``.result-table th``'yu da hücrelerle birlikte sara alıyor, o yüzden her dar
ekran cevabı sütun adını alt çizgisinden kırıyor: ``STOK_KO / DU``. İddia kaynak CSS'te kurulur
- ölçülen yazarın niyeti, küçültücünün metni değil. Bildirimler yığılarak okunur (kaskad):
blokta birden çok ``th`` kuralı olabilir, önemli olan telefon genişliğinde hangisinin kazandığı.
"""

import re

from nl2sql import config

STYLES = config.WEB_DIR / "src" / "styles.css"

# Görsel incelemede başlığın kesildiği genişlik.
PHONE_PX = 390
HEADER = ".result-table th"
CELL = ".result-table td"

CSS = re.sub(r"/\*.*?\*/", "", STYLES.read_text(encoding="utf-8"), flags=re.S)


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


def upper_bound(condition: str) -> int | None:
    """Koşulun üst sınırı px olarak; alt sınırlı (min-width) koşullar telefon için işlemez."""
    match = re.search(r"max-width:\s*(\d+)px", condition)
    return int(match.group(1)) if match else None


def phone_bodies(css: str) -> list[str]:
    """Telefon genişliğinde gerçekten işleyen bloklar: üst sınırı telefon genişliğinden dar değil."""
    bodies = [
        css[start:end]
        for condition, start, end in media_spans(css)
        if (bound := upper_bound(condition)) is not None and bound >= PHONE_PX
    ]
    assert bodies, f"{STYLES.name} içinde {PHONE_PX}px'e inen bir max-width bloğu yok"
    return bodies


def base_css(css: str) -> str:
    """Media sorgularından arınmış kısım: ekran genişliğinden bağımsız temeller."""
    keep, cursor = [], 0
    for _, start, end in media_spans(css):
        keep.append(css[cursor : start - 1])
        cursor = end + 1
    keep.append(css[cursor:])
    return "".join(keep)


def rules(css: str) -> list[tuple[list[str], dict[str, str]]]:
    """Yaprak kurallar: (seçiciler, bildirimler). Küme işareti taşımadığı için @-başlıklar sayılmaz."""
    out = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        decls = {}
        for chunk in match.group(2).split(";"):
            prop, sep, value = chunk.partition(":")
            if sep:
                decls[prop.strip().lower()] = value.strip().lower()
        selectors = [part.strip() for part in match.group(1).split(",") if part.strip()]
        out.append((selectors, decls))
    return out


def effective(selector: str) -> dict[str, str]:
    """Telefon genişliğinde kazanan bildirimler: temeller, sonra işleyen media blokları, sıra ile."""
    won: dict[str, str] = {}
    for body in [base_css(CSS), *phone_bodies(CSS)]:
        for selectors, decls in rules(body):
            if selector in selectors:
                won.update(decls)
    return won


def test_the_header_holds_one_line_on_a_phone():
    """Bölünmeyen başlık: dokuz karakterlik sütun adı alt çizgisinden kesilirse ekranın konusu okunamaz."""
    won = effective(HEADER)
    assert won.get("white-space") == "nowrap", won
    assert won.get("overflow-wrap", "normal") != "anywhere", won


def test_the_cells_keep_wrapping_on_a_phone():
    """Başlık tek satıra dönerken hücreler sararak sığmaya devam etmeli: kural yalnız başlığa dokunur."""
    won = effective(CELL)
    assert won.get("white-space") == "normal", won
    assert won.get("overflow-wrap", "normal") != "normal", won
