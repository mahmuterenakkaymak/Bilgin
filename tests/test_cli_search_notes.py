# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Adım notları: arama aracının boş ve hatalı cevabı kendi cümlesiyle çıkar (R2-14).

Adlar yalnız gerçek sonuç satırlarından toplanır; "Eşleşen tablo yok." cümlesinin ilk sözcüğü
tablo adı gibi görünen bir harf, "Hata: ..." ise bir sözcük üretirdi. Boş hal de kullanıcı için
bilgi olduğu için diğer araçların yaptığı gibi cümlenin kendisi gösterilir.
"""

from nl2sql.cli.main import _search_notes


def test_search_schema_bos_hali_kendi_cumlesiyle():
    assert _search_notes("search_schema", "Eşleşen tablo yok.") == ["→ Eşleşen tablo yok."]


def test_search_schema_hata_cumlesi_ad_gibi_okunmaz():
    assert _search_notes("search_schema", "Hata: arama indeksi yok.") == [
        "→ Hata: arama indeksi yok."
    ]


def test_search_schema_adlari_yalniz_vuru_satirlarindan():
    answer = "STOK_HAREKET — x [Stok]: A, B\nHESAP — y: C"
    assert _search_notes("search_schema", answer) == ["→ STOK_HAREKET, HESAP"]


def test_find_join_path_tek_tabloyu_soyler():
    assert _search_notes("find_join_path", "Tek tablo; join gerekmiyor.") == [
        "→ Tek tablo; join gerekmiyor."
    ]


def test_search_rules_bos_hali_kendi_cumlesiyle():
    assert _search_notes("search_rules", "Eşleşen kural yok.") == ["→ Eşleşen kural yok."]
