# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Derlenmiş arayüzde Türkçe yazı kalmadı mı (PLAN R8-18)?

``vite build`` çeviriyi iki chunk'a yazıyor: ``tr-*.js`` ve ``en-*.js``. Ana paket bunlardan
hiçbirini gömmezse ekrana kendi sözü çıkar - yani İngilizce arayüz Türkçe bir cümle gösterir.
Tarama bu yüzden kaynağı değil derlenmiş çıktıyı okur: kaynak dosyadaki yorum Türkçe kalabilir,
pakete giren yazı kalamaz. Kaynağın Türkçesi ``tr-*.js``te durur; ``index.html`` taramanın
dışındadır - onun ``lang`` niteliği çalışma zamanında yazılıyor ve içindeki yorum arayüze çıkmıyor.
Derleme yoksa (temiz klon) testler atlanır: API o durumda neyin eksik olduğunu söyleyen sayfayı
sunuyor, ki onun kendi testi ``test_web_static.py``de.
"""

import re

import pytest

from bilgin import config
from bilgin.web.app import BUILD_COMMAND

TURKISH = re.compile(r"[çğıöşüÇĞİÖŞÜ]")

# Kataloğun bir satırı: ana pakete sızsa ilk test onu yakalar, burası da tr chunk'ında durduğunu
# söyler - yani tarama "hiçbir şey yok" diye değil, "yazı yerinde" diye geçiyor.
TR_VALUE = "Soru okunuyor"


@pytest.fixture
def assets():
    """Derlenmiş ``.js`` ve ``.css`` dosyaları; derlenmemişse iddianın anlamı yok."""
    if not (config.STATIC_DIR / "index.html").is_file():
        pytest.skip(f"arayüz derlenmemiş: {BUILD_COMMAND}")
    found = sorted(p for p in (config.STATIC_DIR / "assets").glob("*") if p.suffix in (".js", ".css"))
    assert found, f"{config.STATIC_DIR / 'assets'} altında derlenmiş dosya yok"
    return found


def catalogs(assets, code):
    return [path for path in assets if path.name.startswith(f"{code}-")]


def test_no_turkish_letter_outside_the_tr_catalog(assets):
    for path in assets:
        if path.name.startswith("tr-"):
            continue
        left = TURKISH.findall(path.read_text(encoding="utf-8"))
        assert not left, f"{path.name}: {len(left)} Türkçe harf kalmış - yazı kataloğun satırı olmalı"


def test_the_english_catalog_is_its_own_chunk(assets):
    english = catalogs(assets, "en")
    assert len(english) == 1, f"tek bir en-*.js chunk bekleniyordu, {[p.name for p in english]} geldi"


def test_the_turkish_catalog_chunk_holds_its_own_text(assets):
    turkish = catalogs(assets, "tr")
    assert len(turkish) == 1, f"tek bir tr-*.js chunk bekleniyordu, {[p.name for p in turkish]} geldi"
    assert TR_VALUE in turkish[0].read_text(encoding="utf-8")
