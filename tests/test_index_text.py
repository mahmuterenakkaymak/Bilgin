# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R2-8: katlama tek dünya - doküman ile sorgu aynı harflere inmek zorunda.

Türkçe büyük I iki yere düşer (I -> ı, İ -> i) ve `str.lower()` bunu bilmez; `İ`'yi `i̇`
(noktalı i + birleşik nokta) yapar. Testler tam bu iki tuzağın etrafında: İSTANBUL ile
istanbul aynı token olmalı, ILAÇ ılaç olmalı, yoksa indeks ile sorgu hiç karşılaşmaz.
"""

from nl2sql.index import text


def test_fold_matches_dotted_capital_to_plain_i():
    assert text.fold("İSTANBUL") == "istanbul"
    assert text.fold("İstanbul") == text.fold("istanbul")


def test_fold_maps_capital_i_to_dotless():
    assert text.fold("ILAÇ") == "ılaç"
    assert text.fold("IŞIK") == "ışık"


def test_fold_keeps_the_two_ises_apart():
    assert text.fold("İLAÇ") == "ilaç"
    assert text.fold("İLAÇ") != text.fold("ILAÇ")


def test_fold_leaves_lowercase_and_is_idempotent():
    assert text.fold("satış faturası 2026") == "satış faturası 2026"
    assert text.fold(text.fold("IŞIK İSTANBUL ŞOK")) == text.fold("IŞIK İSTANBUL ŞOK")


def test_tokens_keeps_the_joined_name_and_adds_its_parts():
    assert text.tokens("HESAP_KOD") == ["hesap_kod", "hesap", "kod"]
    # R2-8: büyük I küçük ı olur.
    assert text.tokens("KAYIT_NO") == ["kayıt_no", "kayıt", "no"]
    assert text.tokens("DEPO_KODU") == ["depo_kodu", "depo", "kodu"]


def test_tokens_drops_punctuation():
    assert text.tokens("fiyatı (KDV hariç)?") == ["fiyatı", "kdv", "hariç"]
    assert text.tokens("e-posta; stok.") == ["e", "posta", "stok"]


def test_tokens_keeps_digits():
    assert text.tokens("2026-09 STOKLAR") == ["2026", "09", "stoklar"]


def test_tokens_of_empty_text_is_empty():
    assert text.tokens("") == []
    assert text.tokens("...") == []


def test_shingles_of_a_short_list():
    assert text.shingles(["a", "b", "c"], 2) == {("a", "b"), ("b", "c")}
    assert text.shingles(["a", "b", "c"], 3) == {("a", "b", "c")}
    assert text.shingles(["a", "b"], 3) == set()


def test_shingles_collapse_repeats_and_cover_every_window():
    assert text.shingles(["a", "b", "a", "b"], 2) == {("a", "b"), ("b", "a")}
    words = ["stok", "hareketleri", "satış", "iadesi"]
    assert len(text.shingles(words, 2)) == len(words) - 1
    assert ("satış", "iadesi") in text.shingles(words, 2)


def test_shingles_of_tokens_follow_the_folding():
    assert text.shingles(text.tokens("DEPO_KODU A"), 2) == {
        ("depo_kodu", "depo"),
        ("depo", "kodu"),
        ("kodu", "a"),
    }
