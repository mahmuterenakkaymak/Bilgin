# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Golden sonuç ile tahminin karşılaştırılması: aynı veri mi, başka bir cevap mı?

Burada sınanan karar, karşılaştırmanın neyi önemsediği: satırlar çok küme olarak eşleşir
(ordered=True ise sıra da şarttır); kolon adları ve kolon sırası hiç önemli değildir, kolonlar
değerleriyle tanınır. Sayılar iki haneye indirilir, metinler kırpılır, modelin eklediği kolonlar
cezalandırılmayıp listelenir.
"""

from decimal import Decimal

from nl2sql.engine.result import Result
from nl2sql.eval.compare import compare


def make(columns, rows):
    """Yürütücünün döndürdüğü Result biçimi: satırlar tuple, row_count toplam satır sayısı."""
    rows = [tuple(row) for row in rows]
    return Result(columns=list(columns), rows=rows, row_count=len(rows))


GOLDEN = make(["CARI_KOD", "TOPLAM"], [("A001", 100.0), ("A002", 250.5)])


# ------------------------------------------------------------------ satırlar


def test_the_same_rows_in_another_order_are_the_same_answer():
    pred = make(["CARI_KOD", "TOPLAM"], [("A002", 250.5), ("A001", 100.0)])
    outcome = compare(GOLDEN, pred, ordered=False)
    assert outcome.match
    assert outcome.reason == ""


def test_ordered_demands_the_rows_in_their_own_order():
    pred = make(["CARI_KOD", "TOPLAM"], [("A002", 250.5), ("A001", 100.0)])
    outcome = compare(GOLDEN, pred, ordered=True)
    assert not outcome.match
    assert "sıra" in outcome.reason


def test_rows_written_in_their_order_pass_the_ordered_check():
    assert compare(GOLDEN, GOLDEN, ordered=True).match


def test_a_row_appearing_twice_is_not_the_same_as_appearing_once():
    golden = make(["K"], [(1,), (1,), (2,)])
    pred = make(["K"], [(1,), (2,), (2,)])
    assert not compare(golden, pred, ordered=False).match


def test_a_row_that_only_swaps_its_columns_is_not_a_match():
    """Kolonlar tek başına aynı değerleri taşıyor diye satırlar eşleşmiş sayılmaz."""
    golden = make(["SAYI", "YAZI"], [(1, "a"), (2, "b")])
    pred = make(["SAYI", "YAZI"], [(1, "b"), (2, "a")])
    assert not compare(golden, pred, ordered=False).match


def test_a_row_count_mismatch_names_both_counts():
    outcome = compare(make(["K"], [(1,), (2,), (3,)]), make(["K"], [(1,), (2,)]), ordered=False)
    assert not outcome.match
    assert "beklenen 3" in outcome.reason and "gelen 2" in outcome.reason


def test_two_empty_results_match():
    outcome = compare(make(["K"], []), make(["K"], []), ordered=False)
    assert outcome.match
    assert outcome.column_map == {0: 0}


def test_an_empty_result_and_a_result_with_rows_do_not_match():
    assert not compare(make(["K"], []), make(["K"], [(1,)]), ordered=False).match


# ------------------------------------------------------------------ kolonlar


def test_column_names_carry_no_meaning():
    pred = make(["KOD", "GENEL_TOPLAM"], GOLDEN.rows)
    outcome = compare(GOLDEN, pred, ordered=False)
    assert outcome.match
    assert outcome.column_map == {0: 0, 1: 1}


def test_columns_are_found_by_their_values_not_their_place():
    pred = make(["TOPLAM", "CARI_KOD"], [(100.0, "A001"), (250.5, "A002")])
    outcome = compare(GOLDEN, pred, ordered=False)
    assert outcome.match
    assert outcome.column_map == {0: 1, 1: 0}


def test_a_column_the_golden_result_lacks_is_listed_not_punished():
    pred = make(
        ["CARI_KOD", "TOPLAM", "IL"], [("A001", 100.0, "ANKARA"), ("A002", 250.5, "ANKARA")]
    )
    outcome = compare(GOLDEN, pred, ordered=False)
    assert outcome.match
    assert outcome.extra_columns == ["IL"]
    assert outcome.column_map == {0: 0, 1: 1}


def test_extra_columns_are_listed_even_when_the_answer_is_wrong():
    golden = make(["SAYI", "YAZI"], [(1, "a"), (2, "b")])
    pred = make(["SAYI", "YAZI", "IL"], [(1, "b", "ANKARA"), (2, "a", "ANKARA")])
    outcome = compare(golden, pred, ordered=False)
    assert not outcome.match
    assert outcome.extra_columns == ["IL"]


def test_two_golden_columns_cannot_share_one_predicted_column():
    golden = make(["SAYI", "KAT"], [(1, 2), (3, 4)])
    outcome = compare(golden, make(["SAYI"], [(1,), (3,)]), ordered=False)
    assert not outcome.match
    assert "KAT" in outcome.reason


def test_identical_golden_columns_need_identical_predicted_ones():
    golden = make(["SAYI", "AYNI"], [(1, 1), (2, 2)])
    pred = make(["SAYI", "SABIT"], [(1, 0), (2, 0)])
    assert not compare(golden, pred, ordered=False).match


# ------------------------------------------------------------------ değerler


def test_amounts_meet_at_two_decimals():
    golden = make(["TOPLAM"], [(1234.56789,)])
    assert compare(golden, make(["TOPLAM"], [(1234.57,)]), ordered=False).match
    assert not compare(golden, make(["TOPLAM"], [(1234.56,)]), ordered=False).match


def test_a_whole_number_and_the_same_amount_as_a_decimal_are_equal():
    golden = make(["TOPLAM"], [(99.0,)])
    assert compare(golden, make(["TOPLAM"], [(99,)]), ordered=False).match
    assert compare(golden, make(["TOPLAM"], [(Decimal("99.00"),)]), ordered=False).match


def test_text_is_compared_without_its_padding():
    assert compare(make(["IL"], [("  ANKARA  ",)]), make(["IL"], [("ANKARA",)]), ordered=False).match


def test_a_missing_value_is_not_an_empty_text():
    assert not compare(make(["NOT"], [(None,)]), make(["NOT"], [("",)]), ordered=False).match
    assert compare(make(["NOT"], [(None,)]), make(["NOT"], [(None,)]), ordered=False).match


def test_a_different_total_is_the_wrong_answer():
    outcome = compare(make(["TOPLAM"], [(100.0,)]), make(["TOPLAM"], [(99.99,)]), ordered=False)
    assert not outcome.match
    assert "Satırlar farklı" in outcome.reason


def test_a_row_the_predicted_result_invented_is_the_wrong_answer():
    golden = make(["K", "V"], [(1, "a"), (2, "b")])
    pred = make(["K", "V"], [(1, "a"), (2, "c")])
    outcome = compare(golden, pred, ordered=False)
    assert not outcome.match
    assert "1 satır" in outcome.reason
