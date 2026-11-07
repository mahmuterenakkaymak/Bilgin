# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T297: kullanıcının istediği grafik türü (PLAN R7-10, Contracts "chart_spec (ext.)").

İddia: istenen tür sonucun biçimine uyuyorsa mevcut üreticiyle o tür çizilir ve ek bir şey
taşımaz; uymuyorsa kendiliğinden seçilen grafik aynen kalır, yanına neyin eksik olduğunu söyleyen
bir ``reason`` eklenir — cümle kolon adı taşımaz. "table" grafik değildir: None. Aylık bir sonuç
etiket olarak tek tarih kolonunu kullandığı için hem çizgi hem sütun, değerleri pozitifse pastadır;
1x1'lik sonuç hiçbir türü kaldırmaz. kind=None Run 5'in kendisidir (test_chart.py).
"""

import pytest

from bilgin.report import chart

MONTH_COLUMNS = ["AY", "CIRO"]
MONTH_ROWS = [(f"2026-{month:02d}", 1000.0 + 100.0 * month) for month in range(1, 7)]
MONTH_LABELS = [row[0] for row in MONTH_ROWS]

BAR_COLUMNS = ["STOK_ADI", "SATIS_MIKTARI"]
BAR_ROWS = [("Çay", 40.0), ("Şeker", 90.0), ("Su", 65.0)]

# Sayısı var, etiketi yok: hiçbir türü kaldırmayan bir sonuç.
BARE_COLUMNS = ["FIYAT", "MIKTAR"]
BARE_ROWS = [(1.5, 10.0), (2.5, 4.0), (3.0, 8.0)]

NEGATIVE_ROWS = [("2026-01", 800.0), ("2026-02", -200.0), ("2026-03", 300.0)]
MANY_ROWS = [(f"2026-{month:02d}", float(month)) for month in range(1, 13)]

SHAPES = [(MONTH_COLUMNS, MONTH_ROWS), (BAR_COLUMNS, BAR_ROWS), (BARE_COLUMNS, BARE_ROWS), (["CIRO"], [(1200.0,)])]

# Red cümlesinin tür adları: cümlenin kendisi de sözleşmenin bir parçası.
LABELS = {"line": "çizgi", "bar": "sütun", "pie": "pasta"}


def test_monthly_rows_take_both_a_line_and_a_bar():
    line = chart.chart_spec(MONTH_COLUMNS, MONTH_ROWS, "Aylık ciro ne kadar?", kind="line")
    bar = chart.chart_spec(MONTH_COLUMNS, MONTH_ROWS, "Aylık ciro ne kadar?", kind="bar")

    assert line["type"] == "line" and "reason" not in line
    assert line["option"]["xAxis"]["data"] == sorted(MONTH_LABELS)
    assert bar["type"] == "bar" and "reason" not in bar
    assert bar["option"]["xAxis"]["data"] == list(reversed(MONTH_LABELS)), "sütun azalan sıralanır"
    assert bar["option"]["bilgin"] == {"value_format": "number", "value_column": "CIRO", "label_column": "AY"}


def test_the_pie_is_forced_only_when_every_value_is_positive():
    pie = chart.chart_spec(MONTH_COLUMNS, MONTH_ROWS, "Aylık ciro ne kadar?", kind="pie")

    assert pie["type"] == "pie" and "reason" not in pie
    assert pie["option"]["series"][0]["data"] == [
        {"name": name, "value": value} for name, value in MONTH_ROWS
    ], "dilimler ad + değer taşır ve sırası bozulmaz"

    refused = chart.chart_spec(MONTH_COLUMNS, NEGATIVE_ROWS, "Aylık ciro ne kadar?", kind="pie")

    assert refused["type"] == "line", "pasta kalkmayan bir sonuçta kendi grafiği durur"
    assert refused["reason"] == "Bu sonuç pasta grafiğe uygun değil: dilimlerin değerleri pozitif olmalı."


def test_a_single_cell_result_refuses_a_forced_line_and_keeps_the_auto_none():
    spec = chart.chart_spec(["CIRO"], [(1200.0,)], "Toplam ciro ne kadar?", kind="line")

    assert spec["type"] is None and spec["option"] is None
    assert spec["reason"].startswith("Bu sonuç çizgi grafiğe uygun değil: ")
    assert spec["reason"].endswith(".")


def test_a_table_wish_has_no_chart():
    assert chart.chart_spec(MONTH_COLUMNS, MONTH_ROWS, "Aylık ciro ne kadar?", kind="table") is None
    assert chart.chart_spec(["CIRO"], [(1200.0,)], "Toplam ciro ne kadar?", kind="table") is None


def test_forcing_the_kind_the_result_already_gives_adds_no_reason():
    auto = chart.chart_spec(BAR_COLUMNS, BAR_ROWS, "Ürüne göre satış miktarı ne?")
    forced = chart.chart_spec(BAR_COLUMNS, BAR_ROWS, "Ürüne göre satış miktarı ne?", kind="bar")

    assert forced == auto


@pytest.mark.parametrize(
    "kind, columns, rows",
    [
        ("line", BAR_COLUMNS, BAR_ROWS),
        ("line", BARE_COLUMNS, BARE_ROWS),
        ("bar", BARE_COLUMNS, BARE_ROWS),
        ("pie", MONTH_COLUMNS, MANY_ROWS),
        ("pie", MONTH_COLUMNS, NEGATIVE_ROWS),
        ("line", ["CIRO"], [(1200.0,)]),
    ],
)
def test_a_reason_names_what_is_missing_and_never_a_column(kind, columns, rows):
    reason = chart.chart_spec(columns, rows, "Sonuç ne?", kind=kind)["reason"]

    assert reason.startswith(f"Bu sonuç {LABELS[kind]} grafiğe uygun değil: ")
    assert reason.endswith(".")
    for name in columns:
        assert name not in reason, "cümle kolon adı taşımaz"


@pytest.mark.parametrize("kind", ["line", "bar", "pie", "table"])
@pytest.mark.parametrize("columns, rows", SHAPES)
def test_every_forced_kind_returns_an_option_echarts_accepts(kind, columns, rows):
    spec = chart.chart_spec(columns, rows, "Sonuç ne?", kind=kind)

    if spec is None or spec["type"] is None:
        return
    assert chart.validate_option(spec["option"]) == []
