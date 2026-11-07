# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T372: pano kartları kendi yüksekliğinde durur (M23 görsel inceleme 7).

`#start` bir ızgaraydı ama `align-items` demiyordu, dolayısıyla ızgara maddeleri satırın en
yüksek kartına geriliyordu: grafikli kartın kutusunu doldururken yanındaki KPI kartının "Yenile"
düğmesinin altında ~150px boş kart kalıyordu (start-sales-1366.png, db-dot-user-ok-1366.png,
landing-empty-state-1366.png). Pano kullanıcının gördüğü ilk ekran ve boş altlar onu yarı yüklenmiş
gösteriyor. İddia kaynak CSS'te kurulur: panonun temeli `align-items: start` demeli - tek sütuna
inen telefon kuralının içinde değil, her genişlikte geçerli olan kuralın içinde.
"""

import re

from bilgin import config

STYLES = config.WEB_DIR / "src" / "styles.css"

CSS = re.sub(r"/\*.*?\*/", "", STYLES.read_text(encoding="utf-8"), flags=re.S)


def declarations(selector: str) -> dict[str, str]:
    """``selector``'ın birebir kendisini taşıyan kuralların bildirimi, sırayla üstüne binerek.

    Bileşik seçici ayrı bir seçicidir: ``#start.start-grid`` buraya ``#start`` olarak düşmez,
    dolayısıyla telefonun tek sütun kuralı bu iddiaya malzeme olmaz.
    """
    decls: dict[str, str] = {}
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", CSS):
        selectors = [part.strip() for part in match.group(1).split(",")]
        if selector not in selectors:
            continue
        for chunk in match.group(2).split(";"):
            prop, sep, value = chunk.partition(":")
            if sep:
                decls[prop.strip().lower()] = value.strip().lower()
    assert decls, f"{STYLES.name} içinde {selector} kuralı yok"
    return decls


def test_the_board_is_a_grid():
    """Kartlar hâlâ ızgarada: düzeltme akort, yerleşim değil."""
    board = declarations("#start")
    assert board.get("display") == "grid", f"#start ızgara değil: {board.get('display')!r}"
    assert "grid-template-columns" in board, "#start sütunlarını söylemiyor"


def test_a_card_is_its_own_height():
    """Izgara maddeleri yukarı yaslanır: satırın en yükseği boyunun komşulara dayatamaz."""
    board = declarations("#start")
    assert board.get("align-items") == "start", (
        f"#start kartları satıra germeyi kesmiyor: align-items {board.get('align-items')!r}"
    )
