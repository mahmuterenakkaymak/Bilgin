# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Tablonun ekranda duruşu: hizalı kolonlar, Türkçe sayılar, dostane uyarılar.

Sınanan şey verinin kendisi değil nasıl göründüğü: sayılar 1.234,56 gibi yazılır ve sağa
yaslanır, NULL "-" olur, boş sonuç tek satırlık bir cümledir, kesilmiş sonuç kaç satır
gösterildiğini söyler. Biçimlendirme hiçbir değeri değiştirmez; metin hanesi sayıya benzese
bile olduğu gibi kalır.
"""

from decimal import Decimal

from bilgin.cli.table import format_table
from bilgin.engine.result import Result


def make(columns, rows, row_count=None, truncated=False):
    """Yürütücünün döndürdüğü Result biçimi; row_count verilmezse gösterilen satır sayısı kadar."""
    rows = [tuple(row) for row in rows]
    return Result(
        columns=list(columns),
        rows=rows,
        row_count=len(rows) if row_count is None else row_count,
        truncated=truncated,
    )


def lines(text):
    return text.splitlines()


# ------------------------------------------------------------------ sayılar


def test_amounts_read_the_turkish_way():
    out = format_table(make(["TOPLAM"], [(1234.5,), (9876543.219,)]))
    assert "1.234,50" in out
    assert "9.876.543,22" in out


def test_whole_numbers_keep_their_grouping_and_no_decimals():
    out = format_table(make(["ADET"], [(1234500,), (42,)]))
    assert "1.234.500" in out
    assert " 42" in out


def test_decimal_amounts_from_a_driver_format_too():
    assert "1.234,56" in format_table(make(["TUTAR"], [(Decimal("1234.56"),)]))


def test_negative_amounts_keep_their_sign():
    assert "-1.234,50" in format_table(make(["FARK"], [(-1234.5,)]))


def test_zero_stays_zero():
    out = format_table(make(["T"], [(0.0,), (0,)]))
    assert "0,00" in out
    assert "nan" not in out.lower()


def test_text_that_looks_like_a_number_is_left_alone():
    out = format_table(make(["KOD"], [("1234.56",), ("A",)]))
    assert "1234.56" in out
    assert "1.234,56" not in out


# ------------------------------------------------------------------ hizalama


def test_numbers_hug_the_right_edge_and_text_the_left():
    out = lines(format_table(make(["KOD", "TOPLAM"], [("A001", 12.5), ("B002", 1234.5)])))
    assert out[0] == "KOD  |   TOPLAM"
    assert out[1] == "---- + --------"
    assert out[2] == "A001 |    12,50"
    assert out[3] == "B002 | 1.234,50"


def test_every_line_of_a_table_is_the_same_width():
    out = lines(format_table(make(["KOD", "TOPLAM"], [("A001", 12.5), ("B00222", 1234.5)])))
    assert len({len(line) for line in out}) == 1


def test_a_column_of_mixed_values_stays_text():
    out = lines(format_table(make(["DEGER"], [("12,5",), (None,), ("A",)])))
    assert out[2].strip() == "12,5"
    assert out[3].strip() == "-"


# ------------------------------------------------------------------ NULL


def test_null_is_a_dash():
    out = lines(format_table(make(["KOD"], [(None,)])))
    assert out[-1].strip() == "-"


def test_a_null_does_not_make_a_number_column_text():
    out = lines(format_table(make(["TOPLAM"], [(1000.0,), (None,)])))
    assert out[2] == "1.000,00"
    assert out[3] == "       -"


# ------------------------------------------------------------------ uyarılar


def test_empty_result_is_a_sentence_not_an_empty_screen():
    assert format_table(make(["KOD", "TOPLAM"], [])) == "Sonuç boş (0 satır)"


def test_a_cut_result_says_what_was_left_out():
    out = format_table(
        make(["KOD"], [(f"A{i}",) for i in range(3)], row_count=312, truncated=True)
    )
    assert out.endswith("İlk 3 satır gösteriliyor (toplam 312)")


def test_a_whole_result_adds_no_notice():
    out = format_table(make(["KOD"], [("A001",)], row_count=1))
    assert "gösteriliyor" not in out
    assert "boş" not in out
