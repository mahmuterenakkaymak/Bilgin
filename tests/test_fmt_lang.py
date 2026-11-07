# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T394: sayıların dile göre yazımı (PLAN R8-7).

fmt tek kaynak kalır: aynı sayı, dil anahtarıyla iki okunuşla yazılır. İngilizcede binlik ayıraç
virgül, ondalık nokta, yüzde sonda, ölçek K/M/B'dir; Türkçe tarafı bugünkü yazının aynısıdır —
`tr_*` sarmalayıcıları `format_*("tr")` ile bayt bayt aynı çıktıyı vermeli. Yokluk iki dilde de "–".
"""

import pytest

from bilgin.report import fmt

NULL = "–"

VALUES = [
    1234.56,
    12345,
    -1234.5,
    0,
    -0,
    1234.0,
    1234567890,
    12.3,
    -1.5,
    9999,
    12500,
    -12500,
    3_200_000,
    1_100_000_000,
    -0.004,
    -0.006,
    None,
]


@pytest.mark.parametrize("value", VALUES)
def test_turkish_wrappers_write_exactly_what_the_language_functions_write(value):
    assert fmt.tr_number(value) == fmt.format_number(value, "tr")
    assert fmt.tr_percent(value) == fmt.format_percent(value, "tr")
    assert fmt.tr_compact(value) == fmt.format_compact(value, "tr")


@pytest.mark.parametrize("value", VALUES)
@pytest.mark.parametrize("decimals", [0, 1, 2, 4])
def test_the_wrapper_and_the_function_agree_for_every_fixed_decimal_count(value, decimals):
    assert fmt.tr_number(value, decimals) == fmt.format_number(value, "tr", decimals)
    assert fmt.tr_percent(value, decimals) == fmt.format_percent(value, "tr", decimals)


def test_the_default_language_is_turkish():
    assert fmt.format_number(1234.56) == "1.234,56"
    assert fmt.format_percent(12.3) == "%12,3"
    assert fmt.format_compact(12500) == "12,5 bin"


# ------------------------------------------------------------------ ingilizce


def test_en_number_groups_with_commas_and_writes_the_decimal_with_a_dot():
    assert fmt.format_number(1234.56, "en") == "1,234.56"
    assert fmt.format_number(12345, "en") == "12,345"
    assert fmt.format_number(-1234.5, "en") == "-1,234.5"
    assert fmt.format_number(1234.0, "en") == "1,234", "gereksiz ondalık yazılmaz"
    assert fmt.format_number(1234567890, "en") == "1,234,567,890"
    assert fmt.format_number(1234.56, "en", 2) == "1,234.56", "basamak verilince sabit yazılır"
    assert fmt.format_number(1234.567, "en", 4) == "1,234.5670"
    assert fmt.format_number(1234.567, "en", 0) == "1,235"


def test_en_number_never_shows_a_negative_zero():
    assert fmt.format_number(-0.001, "en", 2) == "0.00"
    assert fmt.format_number(-0.5, "en", 0) == "0"
    assert fmt.format_number(-0.006, "en", 2) == "-0.01", "gerçek eksi işaretini kaybetmez"


def test_en_percent_writes_the_sign_after_the_number():
    assert fmt.format_percent(12.3, "en") == "12.3%"
    assert fmt.format_percent(12.25, "en", 2) == "12.25%"
    assert fmt.format_percent(-1.5, "en") == "-1.5%"
    assert fmt.format_percent(0, "en") == "0.0%"


def test_en_compact_uses_K_M_B_and_leaves_small_numbers_plain():
    assert fmt.format_compact(12500, "en") == "12.5K"
    assert fmt.format_compact(3_400_000, "en") == "3.4M"
    assert fmt.format_compact(1_200_000_000, "en") == "1.2B"
    assert fmt.format_compact(-12500, "en") == "-12.5K"
    assert fmt.format_compact(10_000, "en") == "10.0K"
    assert fmt.format_compact(9999, "en") == "9,999", "COMPACT_MIN'dan küçüğü ölçeklenmez"


def test_missing_value_is_the_same_dash_in_both_languages():
    assert fmt.format_number(None, "en") == fmt.NULL_TEXT == NULL
    assert fmt.format_percent(None, "en") == fmt.NULL_TEXT == NULL
    assert fmt.format_compact(None, "en") == fmt.NULL_TEXT == NULL
