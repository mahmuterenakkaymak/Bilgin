# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T363: ``ambiguous_entity`` ASCII yazılmış kolon adlarında da şık sorar (PLAN R7-12).

Eşik, sorunun Türkçe varlık sözcüğünü son turun kolon adlarıyla karşılaştırır; oysa gerçek
şemaların adları ASCII'dir - MUSTERI_ID, URUN_ADI, TEDARIKCI_ADI. Katlama Türkçe harfleri ASCII'ye
indirmedikçe "müşteri" ile "MUSTERI_ADI" aynı alfabede buluşmuyor, şık yalnız İngilizce takma
adlarla çalışıyordu. Burada tek tur elle kurulur: veritabanı yok, model yok.
"""

from nl2sql.agent import refine


def answered_turn(columns, rows):
    """``ambiguous_entity``nin okuduğu alanlar: yanıtlanmış bir turun sql'i ve summary'si."""
    return {
        "sql": "SELECT * FROM MUSTERI",
        "status": "answered",
        "summary": {"columns": list(columns), "rows": [list(row) for row in rows]},
    }


def test_ascii_customer_columns_ask_which_customer():
    turns = [answered_turn(
        ["MUSTERI_ID", "MUSTERI_ADI"],
        [("1001", "Anadolu Gıda"), ("1002", "Marmara Market")],
    )]

    asked = refine.ambiguous_entity("Bu müşteri kaç sipariş verdi?", turns, None)

    assert asked["question"] == "Hangi müşteriyi kastediyorsunuz?"
    assert asked["column"] == "MUSTERI_ID"
    assert asked["options"] == ["1001 (Anadolu Gıda)", "1002 (Marmara Market)"]


def test_ascii_product_columns_ask_which_product():
    turns = [answered_turn(
        ["URUN_KODU", "URUN_ADI"],
        [("U-10", "Kakaolu Bisküvi"), ("U-11", "Limonlu Şeker")],
    )]

    asked = refine.ambiguous_entity("Bu ürün hangi gruplarda?", turns, None)

    assert asked["question"] == "Hangi ürünü kastediyorsunuz?"
    assert asked["column"] == "URUN_KODU"
    assert asked["options"] == ["U-10 (Kakaolu Bisküvi)", "U-11 (Limonlu Şeker)"]


def test_ascii_supplier_column_asks_which_supplier():
    turns = [answered_turn(["TEDARIKCI_ADI"], [("Batı Cam",), ("Ege Kâğıt",)])]

    asked = refine.ambiguous_entity("Bu tedarikçinin kaç kalemi var?", turns, None)

    assert asked["question"] == "Hangi tedarikçiyi kastediyorsunuz?"
    assert asked["column"] == "TEDARIKCI_ADI"
    assert asked["options"] == ["Batı Cam", "Ege Kâğıt"]


def test_a_single_value_needs_no_choice():
    turns = [answered_turn(["MUSTERI_ID", "MUSTERI_ADI"], [("1001", "Anadolu Gıda")])]

    assert refine.ambiguous_entity("Bu müşteri kaç sipariş verdi?", turns, None) is None
