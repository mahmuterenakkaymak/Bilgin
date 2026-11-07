# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T177: Cevabın sayıları koddan çıkar (PLAN R5-7, Contracts Fact).

İddia: anlatının kullanabileceği her özet burada elle hesaplanmış değerlerle bulunur — toplam,
ucun hangi kalem olduğu, ortalama, en kalemin payı, son iki dönemin değişimi. Boş hücre toplama
girmez ama satır sayısı satırdır; maskeli kolon hiç olgu vermez. Pay ve yüzde uydurulmaz: negatif
toplamda pay, sıfır önceki dönemde yüzde yoktur. Ekrana çıkan her sayı Türkçe yazılır.
"""

from nl2sql.policy import pii
from nl2sql.report import facts

CATEGORY_COLUMNS = ["STOK_ADI", "SATIS_MIKTARI"]
CATEGORY_ROWS = [("Çay", 120.0), ("Kahve", 80.0), ("Şeker", 50.0)]

PERIOD_COLUMNS = ["DONEM", "NET_TUTAR"]
PERIOD_ROWS = [("2026-08", 1200.0), ("2026-06", 1000.0), ("2026-09", 1800.0), ("2026-07", 1500.0)]


def by_name(result):
    return {fact.name: fact for fact in result}


# ------------------------------------------------------------------ kategori sonucu


def test_a_category_result_gives_its_total_extremes_and_share():
    result = facts.compute_facts(CATEGORY_COLUMNS, CATEGORY_ROWS)

    assert [fact.name for fact in result] == [
        "row_count",
        "total",
        "max",
        "min",
        "mean",
        "top_item",
        "top_share",
    ]
    got = by_name(result)
    assert got["row_count"].value == 3
    assert got["row_count"].column is None, "satır sayısı bir kolona ait değildir"
    assert got["total"].value == 250.0
    assert got["total"].column == "SATIS_MIKTARI"
    assert got["max"].value == 120.0
    assert got["max"].label == "En yüksek (Çay)", "ucun adı satırın kategori hücresidir"
    assert got["min"].value == 50.0
    assert got["mean"].value == 83.33, "250 / 3 iki basamağa indirgenir"
    assert got["top_item"].value == "Çay"
    assert got["top_share"].value == 48.0
    assert got["top_share"].percent is True


def test_every_display_is_the_turkish_writing_of_its_value():
    got = by_name(
        facts.compute_facts(["STOK_ADI", "TUTAR"], [("Çay", 1234567.89), ("Kahve", 100000.0), ("Şeker", 50000.0)])
    )

    assert got["total"].display == "1.384.567,89"
    assert got["max"].display == "1.234.567,89"
    assert got["min"].display == "50.000"
    assert got["mean"].display == "461.522,63"
    assert got["top_item"].display == "Çay"
    assert got["top_share"].display == "%89,2"


def test_a_column_with_a_negative_value_or_a_zero_total_has_no_share():
    negative = by_name(facts.compute_facts(["STOK_ADI", "MIKTAR"], [("Çay", 30.0), ("İade", -40.0)]))
    zero = by_name(facts.compute_facts(["STOK_ADI", "MIKTAR"], [("Durdu", 0.0), ("İade", 0.0)]))

    assert negative["total"].value == -10.0
    assert negative["max"].value == 30.0
    assert "top_item" not in negative and "top_share" not in negative
    assert "top_item" not in zero and "top_share" not in zero, "toplam sıfırsa pay tanımsız"


def test_null_cells_are_skipped_but_rows_are_still_counted():
    got = by_name(facts.compute_facts(["STOK_ADI", "MIKTAR"], [("Çay", 10.0), ("Kahve", None), ("Şeker", 30.0)]))

    assert got["row_count"].value == 3
    assert got["total"].value == 40.0
    assert got["mean"].value == 20.0, "boş hücre ortalamaya ortak koşmaz"
    assert got["max"].label == "En yüksek (Şeker)"
    assert got["min"].value == 10.0
    assert got["top_share"].value == 75.0


# ------------------------------------------------------------------ dönem sonucu


def test_periods_are_the_last_two_rows_sorted_by_date():
    result = facts.compute_facts(PERIOD_COLUMNS, PERIOD_ROWS)

    assert [fact.name for fact in result] == [
        "row_count",
        "total",
        "max",
        "min",
        "mean",
        "last_period",
        "previous_period",
        "change",
        "change_pct",
    ]
    got = by_name(result)
    assert got["total"].display == "5.500"
    assert got["mean"].display == "1.375,00"
    assert got["max"].label == "En yüksek (2026-09)", "kategori yoksa ad tarih hücresidir"
    assert got["last_period"].value == 1800.0
    assert got["last_period"].label == "Son dönem (2026-09)"
    assert got["previous_period"].value == 1200.0
    assert got["previous_period"].label == "Önceki dönem (2026-08)"
    assert got["change"].value == 600.0
    assert got["change"].display == "600"
    assert got["change_pct"].value == 50.0
    assert got["change_pct"].display == "%50,0"
    assert got["change_pct"].percent is True
    assert "top_item" not in got, "tarih kolonu kategori değildir"


def test_a_fall_is_shown_as_a_negative_change():
    got = by_name(facts.compute_facts(PERIOD_COLUMNS, [("2026-06", 1200.0), ("2026-07", 900.0)]))

    assert got["change"].value == -300.0
    assert got["change"].display == "-300"
    assert got["change_pct"].value == -25.0
    assert got["change_pct"].display == "-%25,0"


def test_a_zero_previous_period_gives_the_change_but_no_percentage():
    got = by_name(facts.compute_facts(PERIOD_COLUMNS, [("2026-06", 0.0), ("2026-07", 250.0)]))

    assert got["change"].value == 250.0
    assert "change_pct" not in got, "sıfırın yüzdesi uydurulmaz"


def test_a_single_period_cannot_change():
    got = by_name(facts.compute_facts(PERIOD_COLUMNS, [("2026-09", 1800.0)]))

    assert "last_period" not in got and "change" not in got


# ------------------------------------------------------------------ tek satır, boş, maskeli


def test_a_single_row_gives_its_total_but_no_share_or_change():
    result = facts.compute_facts(["NET_HASILAT"], [(45230.5,)])

    assert [fact.name for fact in result] == ["row_count", "total", "max", "min", "mean"]
    got = by_name(result)
    assert got["total"].value == 45230.5
    assert got["total"].display == "45.230,5"
    assert got["max"].label == "En yüksek", "adlandırılacak hücre yok"


def test_an_empty_result_says_only_how_many_rows_it_has():
    assert [fact.to_dict() for fact in facts.compute_facts(CATEGORY_COLUMNS, [])] == [
        {"name": "row_count", "label": "Satır sayısı", "column": None, "value": 0, "display": "0", "percent": False}
    ]


def test_a_masked_column_yields_no_facts():
    salary = pii.mask("salary", 45230.5)
    result = facts.compute_facts(["DEPARTMAN", "NET_TUTAR"], [("Bilgi İşlem", salary), ("Üretim", salary)])

    assert [fact.name for fact in result] == ["row_count"]
    assert all(fact.column != "NET_TUTAR" for fact in result), "maskeli kolon toplanmaz"


# ------------------------------------------------------------------ sözleşme


def test_a_fact_serializes_to_the_contract_dict():
    top_share = by_name(facts.compute_facts(CATEGORY_COLUMNS, CATEGORY_ROWS))["top_share"]

    assert top_share.to_dict() == {
        "name": "top_share",
        "label": "En yüksek pay",
        "column": "SATIS_MIKTARI",
        "value": 48.0,
        "display": "%48,0",
        "percent": True,
    }
