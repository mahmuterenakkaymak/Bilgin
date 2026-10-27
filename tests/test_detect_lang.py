"""T392: sorunun hangi dille yazıldığının ayırt edilmesi (PLAN R8-6).

Ölçülen iki im var: Türkçe harfler ikişer, duran kelimeler birer puan. Türkçe harfin iki sayılmasının
sebebi, Türkçe bir cümlenin arasına karışan tek İngilizce kelimenin yönü çevirmemesi. İmi olmayan metin
- boş, salt sayı, çıplak stok kodu - tahmin edilmez; çağıranın varsayılanı döner, yani test hem ``tr``
hem ``en`` varsayılanıyla koşulur. Altın soruların tamamı Türkçe yazıldığı için kümenin kendi cümleleri
birinci sınamadır.
"""

import pytest

from nl2sql import datasets
from nl2sql.i18n.detect import detect_lang

GOLDEN_DATASETS = ("wwi", "synthetic_erp")

# ASSUMPTION: config.DETECT_EN_WORDS'te "Top 5 products by sales in 2016" cümlesinin tek kelimesi yok;
# imi olmayan o çıplak ad öbeği sözleşme gereği beraberelemedir, o yüzden soru burada fiiliyle duruyor.
ENGLISH_QUESTIONS = (
    "How many customers are there?",
    "What is the total sales amount for 2016?",
    "Show the top 5 products by sales in 2016",
    "Show it as a bar chart",
    "List all orders from Berlin",
    "Which city has the most orders?",
    "Tell me the total quantity of each product",
    "Give me the list of customers with no invoice",
    "How much was the invoice total in September?",
    "What are the five best selling products?",
    "Show the number of orders per country",
    "Who are the top customers by total sales?",
    "Where were the orders delivered last month?",
    "How many products are in each warehouse?",
    "What is the average order value?",
    "List the customers from Germany with their total",
    "Show me only the cancelled invoices",
    "What is the total number of lines per invoice?",
    "How many orders were placed for each customer?",
    "Which supplier has the largest total?",
    "Tell me how many invoices are still open",
    "Give me the total for each month of 2016",
    "What is the sum of the invoice amounts?",
    "List products with no sales in the last quarter",
    "How many users are in the system?",
    "Show me the chart of monthly sales",
    "What was the total revenue and how many lines were shipped?",
)

# Türkçe harf yazılmadan kurulan cümleler: harf puanı sıfır, yönü yalnız katlanmış kelime çeviriyor.
TURKISH_WITHOUT_TURKISH_LETTERS = (
    "Kac musteri var?",
    "En cok satan urun hangisi?",
    "Bu ayki satis miktari ne kadar?",
)

NO_SIGNAL = ("", "   ", "12345", "2026-09-01", "ABC-123", "STK001")


def golden_questions(name: str) -> list[str]:
    return [line["question"] for line in datasets.load_dataset(name).golden()]


@pytest.mark.parametrize("name", GOLDEN_DATASETS)
def test_every_golden_question_reads_as_turkish(name):
    questions = golden_questions(name)
    assert questions, f"{name}: altın soru okunamadı"

    for question in questions:
        assert detect_lang(question) == "tr", f"{name} {question[:40]}: tr olmalı"


@pytest.mark.parametrize("question", ENGLISH_QUESTIONS)
def test_english_business_questions_read_as_english(question):
    assert detect_lang(question) == "en"


@pytest.mark.parametrize("question", TURKISH_WITHOUT_TURKISH_LETTERS)
def test_turkish_written_without_turkish_letters_stays_turkish(question):
    assert detect_lang(question) == "tr"


def test_a_stray_english_word_does_not_flip_a_turkish_question():
    # "iş" katlanınca "is" oluyor: bir İngilizce kelime, iki Türkçe harf ve üç Türkçe kelimeye yeniliyor.
    assert detect_lang("Bu iş için toplam tutar nedir?") == "tr"


@pytest.mark.parametrize("text", NO_SIGNAL)
def test_text_without_signal_uses_the_fallback(text):
    assert detect_lang(text) == "tr"
    assert detect_lang(text, fallback="en") == "en"


def test_an_even_score_uses_the_fallback():
    assert detect_lang("ne the") == "tr"
    assert detect_lang("ne the", fallback="en") == "en"
