# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Follow-up ipuçları (PLAN R7-11): ``followup_hints(question, schema)``.

İpucu iki şeyi ayırt eder: soruda önceki tura işaret eden bir kelime var mı, ve soru bir tabloyu
adlandırıyor mu. İşaretler katlanmış tam kelimeyle aranır - "Ortalama" içindeki "o" işaret değildir.
``wwi_real`` şeması gerçek olduğu için ``table_noun`` da gerçek anahtar kelimeler üzerinden ölçülür.
"""

import json
from pathlib import Path

import pytest

from bilgin.agent.context import followup_hints

REPO = Path(__file__).resolve().parents[1]
WWI = REPO / "real_datasets" / "wwi_real"

MINI_SCHEMA = {
    "tables": [
        {
            "name": "Sales.Customers",
            "description": "Müşteri kartları",
            "keywords": ["cari", "müşteri adı"],
            "columns": [],
        },
        {"name": "Stok_Fişler", "description": "Hareket kayıtları", "keywords": [], "columns": []},
    ]
}


@pytest.fixture(scope="module")
def wwi_schema():
    return json.loads((WWI / "schema.json").read_text(encoding="utf-8"))


def golden(question_id):
    for line in (WWI / "golden.jsonl").read_text(encoding="utf-8").splitlines():
        entry = json.loads(line)
        if entry["id"] == question_id:
            return entry["question"]
    raise AssertionError(f"{question_id} golden setde yok")


def test_demonstrative_question_marks_only_its_marker(wwi_schema):
    assert followup_hints("Bu müşteriye başka ne sattık?", wwi_schema)["markers"] == ["bu"]


def test_narrowing_word_is_a_marker(wwi_schema):
    assert followup_hints("Sadece Texas", wwi_schema)["markers"] == ["sadece"]


def test_peki_marks_and_a_customer_word_names_a_table(wwi_schema):
    hints = followup_hints("Peki toplam müşteri sayısı?", wwi_schema)
    assert hints["markers"] == ["peki"]
    assert hints["table_noun"] is True


def test_genitive_demonstrative_is_a_marker(wwi_schema):
    assert followup_hints("Bunların toplamı", wwi_schema)["markers"] == ["bunların"]


def test_o_inside_a_word_is_not_a_marker(wwi_schema):
    assert followup_hints("Ortalama satış tutarı ne kadar?", wwi_schema)["markers"] == []


def test_standalone_o_is_a_marker(wwi_schema):
    assert followup_hints("O ne kadardır?", wwi_schema)["markers"] == ["o"]


def test_markers_come_in_question_order_not_config_order(wwi_schema):
    assert followup_hints("Bunları sadece şu kalem için say", wwi_schema)["markers"] == [
        "bunları",
        "sadece",
        "şu",
    ]


def test_standalone_golden_question_has_no_marker(wwi_schema):
    question = golden("Q03")
    hints = followup_hints(question, wwi_schema)
    assert hints["markers"] == []
    assert hints["table_noun"] is False


@pytest.mark.parametrize("word", ["customers", "cari", "müşteri", "stok", "fişler", "hareket"])
def test_table_noun_reads_name_parts_keywords_and_description_head(word):
    assert followup_hints(f"{word} ne kadar", MINI_SCHEMA)["table_noun"] is True


def test_a_word_that_names_no_table_is_not_a_table_noun():
    assert followup_hints("Toplam tutar ne kadar", MINI_SCHEMA)["table_noun"] is False
