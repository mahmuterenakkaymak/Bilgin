# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T396: olgular ve grafiğin cümlesi cevabın dilinde (PLAN R8-3, Contracts Fact/chart_spec).

İddia: aynı satırlar her iki dilde aynı olguları verir — ad, değer, kolon ve yüzde işareti
değişmez; yalnız etiket catalog'dan, sayının yazımı ``fmt``in o dilinden gelir. Grafiğin reddi de
cevabın dilini konuşur: aynı eksiklik İngilizce anlatılır, uyan türde zaten hiçbir metin yoktur.
İki modülde de kullanıcıya Türkçe söyleyen satır kalmaz; guard'ın havuzu etiket değil değer okur.
"""

import json
from pathlib import Path

import pytest

from nl2sql.i18n import CATALOG_DIR, scan
from nl2sql.report import chart, facts, guard

CATEGORY_COLUMNS = ["STOK_ADI", "SATIS_MIKTARI"]
CATEGORY_ROWS = [("Çay", 1234567.89), ("Kahve", 100000.0), ("Şeker", 50000.0)]

PERIOD_COLUMNS = ["DONEM", "NET_TUTAR"]
PERIOD_ROWS = [("2026-08", 1200.0), ("2026-09", 1800.0)]

MONTH_COLUMNS = ["AY", "CIRO"]
MONTH_ROWS = [(f"2026-{month:02d}", 1000.0 + 100.0 * month) for month in range(1, 7)]
NEGATIVE_ROWS = [("2026-01", 800.0), ("2026-02", -200.0), ("2026-03", 300.0)]

SHAPES = [(CATEGORY_COLUMNS, CATEGORY_ROWS), (PERIOD_COLUMNS, PERIOD_ROWS)]


def by_name(columns, rows, lang):
    return {fact.name: fact for fact in facts.compute_facts(columns, rows, lang=lang)}


def catalog(lang: str) -> dict[str, str]:
    return json.loads((CATALOG_DIR / f"{lang}.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ olgular


@pytest.mark.parametrize("columns, rows", SHAPES)
def test_both_languages_describe_the_same_numbers(columns, rows):
    tr = facts.compute_facts(columns, rows, lang="tr")
    en = facts.compute_facts(columns, rows, lang="en")

    assert [fact.name for fact in tr] == [fact.name for fact in en]
    assert [(f.value, f.column, f.percent) for f in tr] == [(f.value, f.column, f.percent) for f in en]


def test_labels_come_from_the_language_catalog():
    texts, en = catalog("en"), by_name(PERIOD_COLUMNS, PERIOD_ROWS, "en")

    assert en["row_count"].label == texts["facts.row_count"] == "Row count"
    assert en["total"].label == texts["facts.total"] == "Total"
    assert en["change_pct"].label == texts["facts.change_pct"]
    assert en["last_period"].label == texts["facts.last_period"].format(period="2026-09")
    assert en["max"].label == f"{texts['facts.max']} (2026-09)", "ucun adı satırın hücresiyle kurulur"


def test_the_turkish_labels_are_the_ones_of_today():
    category, periods = by_name(CATEGORY_COLUMNS, CATEGORY_ROWS, "tr"), by_name(PERIOD_COLUMNS, PERIOD_ROWS, "tr")

    assert category["row_count"].label == "Satır sayısı"
    assert category["min"].label == "En düşük"
    assert category["top_item"].label == "Öne çıkan"
    assert category["top_share"].label == "En yüksek pay"
    assert category["max"].label == "En yüksek (Çay)"
    assert periods["last_period"].label == "Son dönem (2026-09)"
    assert periods["previous_period"].label == "Önceki dönem (2026-08)"
    assert periods["change"].label == "Değişim"
    assert periods["change_pct"].label == "Değişim oranı"


def test_an_english_display_is_written_the_english_way():
    en, tr = by_name(CATEGORY_COLUMNS, CATEGORY_ROWS, "en"), by_name(CATEGORY_COLUMNS, CATEGORY_ROWS, "tr")

    assert en["total"].display == "1,384,567.89"
    assert en["min"].display == "50,000"
    assert en["mean"].display == "461,522.63"
    assert en["top_share"].display == "89.2%"
    assert tr["total"].display == "1.384.567,89"
    assert tr["top_share"].display == "%89,2"


def test_a_change_is_a_percent_in_the_language_of_the_answer():
    en, tr = by_name(PERIOD_COLUMNS, PERIOD_ROWS, "en"), by_name(PERIOD_COLUMNS, PERIOD_ROWS, "tr")

    assert en["change"].display == "600"
    assert en["change_pct"].display == "50.0%"
    assert tr["change"].display == "600"
    assert tr["change_pct"].display == "%50,0"


def test_the_payload_dict_carries_the_language_of_its_labels():
    fact = facts.compute_facts(CATEGORY_COLUMNS, CATEGORY_ROWS, lang="en")[0]

    assert fact.to_dict() == {
        "name": "row_count",
        "label": "Row count",
        "column": None,
        "value": 3,
        "display": "3",
        "percent": False,
    }


def test_the_guard_pool_reads_values_and_not_labels():
    tr = facts.compute_facts(CATEGORY_COLUMNS, CATEGORY_ROWS, lang="tr")
    en = facts.compute_facts(CATEGORY_COLUMNS, CATEGORY_ROWS, lang="en")

    assert guard.allowed_values(CATEGORY_COLUMNS, CATEGORY_ROWS, tr, "") == guard.allowed_values(
        CATEGORY_COLUMNS, CATEGORY_ROWS, en, ""
    )


# ------------------------------------------------------------------ grafik


def test_a_forced_kind_that_does_not_fit_refuses_in_english():
    refused = chart.chart_spec(CATEGORY_COLUMNS, CATEGORY_ROWS, "Ürüne göre satış?", kind="line", lang="en")

    assert refused["type"] == "bar", "kendi grafiği yerinde durur"
    assert refused["reason"] == "This result does not fit a line chart: there is no date or ordered column."


def test_a_pie_refused_for_its_values_names_the_missing_in_english():
    refused = chart.chart_spec(MONTH_COLUMNS, NEGATIVE_ROWS, "Aylık ciro ne kadar?", kind="pie", lang="en")

    assert refused["type"] == "line"
    assert refused["reason"] == "This result does not fit a pie chart: slice values must be positive."


def test_the_turkish_refusal_is_the_sentence_of_today():
    refused = chart.chart_spec(CATEGORY_COLUMNS, CATEGORY_ROWS, "Ürüne göre satış?", kind="line")

    assert refused["reason"] == "Bu sonuç çizgi grafiğe uygun değil: tarih ya da sıralı bir kolon yok."


def test_a_chart_that_fits_carries_no_text_at_all():
    tr = chart.chart_spec(CATEGORY_COLUMNS, CATEGORY_ROWS, "Ürüne göre satış?", kind="bar")
    en = chart.chart_spec(CATEGORY_COLUMNS, CATEGORY_ROWS, "Ürüne göre satış?", kind="bar", lang="en")

    assert en == tr and "reason" not in en


# ------------------------------------------------------------------ tarama


def test_the_two_modules_have_no_turkish_literals_left():
    assert scan.user_literals(Path(facts.__file__)) == []
    # ASSUMPTION: _FOLD bir eşleştirme tablosudur (R8-3 "Stay"): kullanıcıya hiç görünmez, o yüzden
    # catalog'a taşınmaz; scan onu yalnız allow ile bilir.
    assert scan.user_literals(Path(chart.__file__), allow=("_FOLD",)) == []
