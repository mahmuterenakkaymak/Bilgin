# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Run 8 README'leri (R8-14): README.md İngilizce, README.tr.md Türkçe, ikisi aynı şeyi anlatıyor.

Üç denetim: iki dosya **aynı komut kümesini** taşıyor - bir dilde yazılmayan komut o dildeki
kullanıcı için yoktur; iki dosya **birbirine bakıyor**, yani kimse tek dilde mahsur kalmıyor; ve
İngilizce dosyanın **nesri İngilizcedir** - Türkçe harf yalnız ``Türkçe`` bağlantısında, kod
alıntısında ve tırnak içindeki örnek soruda/cümlede kalabilir. Run 8'in işaretleri iki dosyada da
aranıyor: dil yüzeyi bir dilde belgelenip öbüründe kaybolmasın. Burada hiçbir komut koşulmaz;
yalnız metin denetlenir.
"""

import re

import pytest

from bilgin import config

EN_FILE = "README.md"
TR_FILE = "README.tr.md"

# Run 8'in yüzeyi: dil seçimi, şablon, İngilizce altın küme ve kuralın İngilizce eş anlamlıları.
README_MARKS = (
    "--lang en",
    "BILGIN_LANG",
    "template --lang en",
    "eval --lang en",
    "golden_en.jsonl",
    "synonyms_en",
)

# Türkçeye özgü harfler: İngilizce dosyada bunlar yalnız aşağıdaki alıntılarda kalabilir.
TURKISH_LETTERS = set("çÇğĞıİöÖşŞüÜ")

_FENCE = re.compile(r"```.*?```", re.S)
_CODE = re.compile(r"`[^`]*`")
_QUOTED = re.compile(r'"[^"]*"', re.S)


def _readme(name: str) -> str:
    return (config.ROOT / name).read_text(encoding="utf-8")


def _commands(text: str) -> set[str]:
    """Metinde geçen ``python -m bilgin <komut>`` çağrılarının komut adları.

    Bayraklar atlanır: ``--lang`` değerini de yuttuğu için ``--lang en ask`` ``ask`` sayılır;
    ``python -m eval.review`` gibi öteki modüller hiç bu kümeye girmez.
    """
    found = set()
    for match in re.finditer(r"python -m bilgin([^\n]*)", text):
        tokens = match.group(1).split()
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if token.startswith("-"):
                index += 1 if "=" in token else 2
                continue
            found.add(token)
            break
    return found


def _prose(text: str) -> str:
    """Düz nesir: ilk satır (``Türkçe`` bağlantısı), örnek bloklar, satır içi kod ve tırnaklı alıntı
    çıkarıldıktan sonra kalan - İngilizce dosyada bunda Türkçe harf olmamalı."""
    body = "".join(text.splitlines(keepends=True)[1:])
    body = _FENCE.sub("", body)
    body = _CODE.sub("", body)
    return _QUOTED.sub("", body)


@pytest.mark.parametrize("mark", README_MARKS)
def test_both_readmes_document_the_run8_mark(mark):
    for name in (EN_FILE, TR_FILE):
        assert mark in _readme(name), f"{mark} {name} içinde yok"


def test_both_readmes_document_the_same_commands():
    en, tr = _commands(_readme(EN_FILE)), _commands(_readme(TR_FILE))
    assert en == tr, f"yalnız bir dosyada geçen komutlar: {sorted(en ^ tr)}"


def test_the_english_readme_links_the_turkish_one_on_its_first_line():
    first = _readme(EN_FILE).splitlines()[0]
    assert "Türkçe" in first and TR_FILE in first, f"ilk satır bağlantı taşımıyor: {first}"


def test_the_turkish_readme_links_the_english_one():
    assert f"]({EN_FILE})" in _readme(TR_FILE), f"{TR_FILE} README.md'ye bakmıyor"


def test_the_english_readme_writes_english_prose():
    offenders = []
    for line in _prose(_readme(EN_FILE)).splitlines():
        letters = sorted({char for char in line if char in TURKISH_LETTERS})
        if letters:
            offenders.append(f"{line.strip()[:70]} ({''.join(letters)})")
    assert offenders == [], "İngilizce README'nin nesrinde Türkçe harf: " + "; ".join(offenders)
