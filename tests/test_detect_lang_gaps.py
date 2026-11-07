# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T472: duran kelimesi olmayan ya da Türkçe özel ad taşıyan İngilizce soruların Türkçe yanıtlanması (PLAN R8-6).

İki boşluk ölçülüyor: iş sorusunun günlük kelimeleri (by, per, top, products...) sözlükte olmadığı için
"Top 5 products by revenue" imi kalmayıp varsayılana düşüyordu; "Çay" ya da "Özgür" gibi tek başına bir
özel adın Türkçe harfi ise iki sayılıp İngilizce kelimeleri yeniyordu. Cümle artık iki İngilizce kelime
taşıyorsa harf tek sayılıyor, yani bir ad cümlenin yönünü çeviremiyor. Altın kümenin Türkçe soruları ve
imi olmayan metinler olduğu gibi kalmak zorunda.
"""

import pytest

from bilgin import datasets
from bilgin.i18n.detect import detect_lang

GOLDEN_DATASETS = ("wwi", "synthetic_erp")

ENGLISH_QUESTIONS = (
    "Top 5 products by revenue",
    "Customers by city",
    "Show sales of Çay",
    "how many orders did customer Özgür place?",
    "Revenue by city",
    "Sales per product",
)

TURKISH_QUESTIONS = (
    "Bu ay Çay satışı kaç?",
    "En çok satan ürün",
)

NO_SIGNAL = ("", "STK001")


@pytest.mark.parametrize("question", ENGLISH_QUESTIONS)
def test_an_english_business_question_without_a_stopword_reads_as_english(question):
    assert detect_lang(question) == "en"


@pytest.mark.parametrize("question", TURKISH_QUESTIONS)
def test_a_turkish_question_naming_a_product_stays_turkish(question):
    assert detect_lang(question) == "tr"


@pytest.mark.parametrize("name", GOLDEN_DATASETS)
def test_every_golden_question_still_reads_as_turkish(name):
    questions = [line["question"] for line in datasets.load_dataset(name).golden()]
    assert questions, f"{name}: altın soru okunamadı"

    for question in questions:
        assert detect_lang(question) == "tr", f"{name} {question[:40]}: tr olmalı"


@pytest.mark.parametrize("text", NO_SIGNAL)
def test_text_without_signal_uses_the_fallback(text):
    assert detect_lang(text) == "tr"
    assert detect_lang(text, fallback="en") == "en"
