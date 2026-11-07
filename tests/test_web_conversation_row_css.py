# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T371: konuşma satırının başlığı kendi çizgisini alır (M23 görsel inceleme 6).

`.side-text` zamanı, başlığı ve tur sayısını tek çizgiye diziyordu: `.side-label` ~18 karaktere
kısalıyor ve aynı soruyla açılan beş konuşma yan yana aynı okunuyordu
(conversation-three-turns-conversation-list-390.png, conversation-chart-refine-1366.png). O liste
konuşmaya tek dönüş yolu. İddia kaynak CSS'te kurulur: satır bir ızgaradır, üst çizgiyi zaman ve
sayaçlar paylaşır, başlık ikinci çizgide ızgaranın tüm sütunlarını alır.
"""

import re

from bilgin import config

STYLES = config.WEB_DIR / "src" / "styles.css"

# Üst çizginin parçaları: her biri .side-text'in ızgarasında kendi alanını adar.
META = (".side-marker", ".side-time", ".side-turn", ".side-count")

CSS = re.sub(r"/\*.*?\*/", "", STYLES.read_text(encoding="utf-8"), flags=re.S)


def parse_rules(css: str) -> list[tuple[str, dict[str, str]]]:
    """Yaprak kurallar: (seçiciler tek satır, bildirimler). Media kümelerinin içi de okunur."""
    out = []
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        decls = {}
        for chunk in match.group(2).split(";"):
            prop, sep, value = chunk.partition(":")
            if sep:
                decls[prop.strip().lower()] = value.strip().lower()
        out.append((" ".join(match.group(1).split()), decls))
    return out


def covers(token: str, name: str) -> bool:
    """Seçici parçası ``name`` mi ya da onun bir hâli: ``.side-text:hover`` evet,
    ``.side-label`` hayır - alt sınıf adları ayrı seçicidir."""
    return token == name or token.startswith(f"{name}[") or token.startswith(f"{name}:")


def merged(name: str) -> dict[str, str]:
    """Bir seçicinin CSS'teki son hâli: onu taşıyan her kuralın bildirimleri sırayla üstüne biner."""
    decls: dict[str, str] = {}
    for selector, rule in RULES:
        if any(covers(part, name) for part in selector.split()):
            decls.update(rule)
    assert decls, f"{STYLES.name} içinde {name} kuralı yok"
    return decls


RULES = parse_rules(CSS)


def test_the_row_is_a_grid():
    """Satır ızgara olmalı: tek çizgili flex'te başlık, yanındakiler pay aldıkça kısalıyor."""
    row = merged(".side-text")
    assert row.get("display") == "grid", f".side-text ızgara değil: {row.get('display')!r}"
    assert "grid-template-columns" in row, ".side-text sütunlarını söylemiyor"


def test_the_title_takes_the_whole_second_line():
    """Başlık ızgaranın ilk çizgisinden son çizgisine kadar uzuyor: panelin tamamı onun.
    Üst çizgi tek satırdan ibaret kalmalı - ikinci bir çizgi adlandırılırsa başlık üçüncüye
    düşer ve satır üç çizgiye iner."""
    title = merged(".side-label")
    assert title.get("grid-column") == "1 / -1", (
        f".side-label tüm sütunları almıyor: {title.get('grid-column')!r}"
    )
    rows = re.findall(r'"([^"]*)"', merged(".side-text").get("grid-template-areas", ""))
    assert len(rows) == 1, f"üst çizgi {len(rows)} çizgiye bölünmüş: {rows}"
    areas = rows[0].split() if rows else []
    for name in META:
        area = merged(name).get("grid-area", "")
        assert area in areas, f"{name} üst çizgide alanını adamıyor: {area!r} {areas} içinde yok"
