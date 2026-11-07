# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T370: görsel koşu masayı hangi dünyada bırakırsa ikinci genişlik orada açılır (M23 incelemesi 5).

``scripts/visual_serve.py`` tek süreçtir: 1366px ve 390px koşuları aynı sunucuyu paylaşır, o yüzden
bir sayfanın sonda bıraktığı etkin küme sıradaki sayfanın - ve öteki genişliğin ilk karesinin -
dünyasıdır. ``admin-map-onboard`` ``ornek_fatura``ya geçip oradan ``synthetic_erp``e dönüyordu;
koşu ``wwi``yle açıldığından sonraki kareler çipde "Sentetik ERP · fake" yazan bir dünyada
çekiliyordu ve cevaplar STOK_KODU / TBLSTHAR kodlarıyla geliyordu
(ask-golden-answer-chart-answer-with-chart-1366.png), aynı sayfanın 390px karesi ise
WideWorldImporters'da "Juniper Scented Candle"ı gösteriyordu. O yüzden küme değiştiren her sayfa, bitmeden
koşunun açtığı dünyaya dönmeli.
"""

import json
import re

from bilgin import config

VISUAL_PATH = config.ROOT / ".hybrid" / "visual.json"

# Koşunun açtığı dünya: ``scripts/visual_serve.py`` bugün ``wwi``yi açar, o yüzden geri dönüşün adı bu.
HOME = "wwi"

# Küme adını taşıyan tek tık biçimi: ``#map-activate`` de küme değiştirir ama adı taşımaz, yani
# geri dönüşü o adım değil, kendisinden sonra gelen ``data-dataset-activate`` tığı söyler.
ACTIVATE = re.compile(r"^button\[data-dataset-activate='([^']+)'\]$")


def visual() -> dict:
    return json.loads(VISUAL_PATH.read_text(encoding="utf-8"))


def datasets_switched_to(page: dict) -> list[str]:
    """Sayfanın küme değiştirdiği kümeler, adımlardaki sırayla."""
    names = []
    for step in page["steps"]:
        if not isinstance(step, dict) or "click" not in step:
            continue
        match = ACTIVATE.match(step["click"])
        if match:
            names.append(match.group(1))
    return names


def test_a_page_that_switches_the_dataset_ends_on_the_world_the_run_opened():
    """Son geçiş ``wwi`` değilse sunucu sayfadan başka bir dünyada çıkar: inceleme ERP kodları
    ile dolu kareleri WideWorldImporters sanır, haritanın kurduğu örnek küme ise yerinde durur."""
    switching = [page for page in visual()["pages"] if datasets_switched_to(page)]
    assert switching, "akışta küme değiştiren tek sayfa yok; koruyucu boş listede geçerdi"

    for page in switching:
        names = datasets_switched_to(page)
        assert names[-1] == HOME, (
            f"{page['name']} sunucuyu {names[-1]!r} kümesinde bırakıyor; koşu {HOME!r} ile açılıyor: {names}"
        )
