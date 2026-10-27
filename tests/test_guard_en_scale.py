"""İngilizce ölçek bekçisi: `fmt.format_compact`'ın yazdığı "12.5K" okunur, uydurma "99.9K" geçmez
(PLAN R8-7 / R8-8). Türkçe tarafın okunuşu aynı metinler için değişmez."""

from __future__ import annotations

import pytest

from nl2sql.report import fmt, guard


def _allowed(*values: float) -> dict:
    return {"values": [float(value) for value in values], "percent": []}


def test_en_attached_scale_passes():
    assert guard.check_text("Sales were 12.5K.", _allowed(12500.0), "en").ok


def test_en_scale_word_passes():
    assert guard.check_text("Sales were 12.5 thousand.", _allowed(12500.0), "en").ok


@pytest.mark.parametrize("text", ["Sales were 99.9K.", "Sales were 99.9M."])
def test_en_invented_scaled_number_is_offending(text):
    result = guard.check_text(text, _allowed(12500.0), "en")
    assert not result.ok
    assert result.offending == [text.split()[2].rstrip(".")]


def test_en_million_scale_passes():
    assert guard.check_text("Total 3.4M rows.", _allowed(3_400_000.0), "en").ok


@pytest.mark.parametrize("value", [12500, 3_400_000, -2_100_000_000])
def test_format_compact_output_always_passes(value):
    text = fmt.format_compact(value, "en")
    assert guard.check_text(f"Total {text}.", _allowed(float(value)), "en").ok


def test_codes_are_still_not_numbers_in_en():
    assert guard.extract_numbers("Order STK001 in Q3", "en") == []


@pytest.mark.parametrize(
    ("text", "offending"),
    [
        ("Sales were 12.5K.", []),
        ("Sales were 99.9K.", []),
        ("Sales were 99.9M.", []),
        ("Total 3.4M rows.", []),
        ("Sales were 12.5 thousand.", ["12.5"]),
    ],
)
def test_turkish_reading_of_the_same_texts_is_unchanged(text, offending):
    result = guard.check_text(text, _allowed(12500.0), "tr")
    assert result.offending == offending


def test_turkish_attached_letter_is_not_a_number():
    assert guard.extract_numbers("12K", "tr") == []
    assert guard.check_text("12,5 bin", _allowed(12500.0), "tr").ok
