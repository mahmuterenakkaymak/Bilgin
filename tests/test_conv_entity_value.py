# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T365: seçilen şıkkın değeri şıkkın içinden geri okunmaz (PLAN R7-12).

``_chosen`` varlığı ``"<değer> (ad)"`` biçimindeki şıkkı ilk " ("e keserek buluyordu; oysa değerin
kendisi de " (" taşıyabilir - WWI müşteri adlarının hepsi taşır ("Tailspin Toys (Peeples Valley,
AZ)") - ve kısalan değer ``validate_note``ın kanıt kapısından geçemediği için not düşüyor,
kullanıcı yeni seçtiği varlığın kanıt satırını kaybediyordu. Artık ``ambiguous_entity`` şıklarla
hizalı hücre değerlerini taşıyor, seçim oradan okunuyor. Burada tek tur elle kurulur: veritabanı
yok, model yok.
"""

from nl2sql.agent import refine
from nl2sql.app.ask import _chosen

WWI = ["Tailspin Toys (Peeples Valley, AZ)", "Wingtip Toys (Aleutian, AK)"]


def answered_turn(columns, rows):
    """``ambiguous_entity``nin okuduğu alanlar: yanıtlanmış bir turun sql'i ve summary'si."""
    return {
        "sql": "SELECT * FROM MUSTERI",
        "status": "answered",
        "summary": {"columns": list(columns), "rows": [list(row) for row in rows]},
    }


def asked_about(columns, rows):
    return refine.ambiguous_entity("Bu müşteri kaç sipariş verdi?", [answered_turn(columns, rows)], None)


def test_a_value_holding_a_parenthesis_keeps_its_full_self():
    asked = asked_about(["MUSTERI_ADI"], [(name,) for name in WWI])

    assert asked["options"] == WWI
    assert asked["values"] == WWI
    assert _chosen(asked, asked["options"][0]) == {"column": "MUSTERI_ADI", "value": WWI[0]}
    assert _chosen(asked, asked["options"][1])["value"] == WWI[1]


def test_a_coded_option_gives_the_code_not_the_record_name():
    asked = asked_about(["CARI_KOD", "CARI_ISIM"], [("C1", "A"), ("C2", "B")])

    assert asked["options"] == ["C1 (A)", "C2 (B)"]
    assert _chosen(asked, "C1 (A)") == {"column": "CARI_KOD", "value": "C1"}


def test_a_clarification_stored_without_the_values_key_keeps_todays_split():
    asked = asked_about(["CARI_KOD", "CARI_ISIM"], [("C1", "A"), ("C2", "B")])
    stored_before_this_change = {key: value for key, value in asked.items() if key != "values"}

    assert _chosen(stored_before_this_change, "C2 (B)") == {"column": "CARI_KOD", "value": "C2"}


def test_a_choice_that_is_not_one_of_the_options_chooses_nothing():
    asked = asked_about(["CARI_KOD", "CARI_ISIM"], [("C1", "A"), ("C2", "B")])

    assert _chosen(asked, "C9 (Z)") is None
