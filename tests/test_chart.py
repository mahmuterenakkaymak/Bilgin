"""T176: sonucun grafiği ve seçeneğin doğrulanması (PLAN R5-6, Contracts ChartSpec).

İddia şurada: çizilecek bir şey yoksa uydurma grafik yoktur — None döner. Tür kolonlardan okunur
(tarih + sayılar çizgi, kategori + tek sayı sütun/pay), sorunun sözcüğü yalnız pay ve saçılımda
söz sahibidir; sütun azalan, çizginin x ekseni artan sıralanır. Seçenek düz JSON kalmak
zorundadır, o yüzden validate_option her üretimin ardından temiz çıkar. Yol tarafında Q02'nin
gerçek cevabı 5 dilimli bir sütun grafiğidir.
"""

import json
import math

import pytest

from nl2sql import config, datasets
from nl2sql.engine.executor import LocalExecutor
from nl2sql.report import chart
from nl2sql.schema_map import build

DATE_COLUMNS = ["TARIH", "CIRO", "MIKTAR"]
DATE_ROWS = [
    ("2026-09-02", 200.0, 4),
    ("2026-09-01", 100.0, 2),
    ("2026-09-03", 300.0, 7),
]

BAR_COLUMNS = ["STOK_ADI", "SATIS_MIKTARI"]
BAR_ROWS = [("Çay", 40.0), ("Şeker", 90.0), ("Su", 65.0)]

SCATTER_COLUMNS = ["FIYAT", "MIKTAR"]
SCATTER_ROWS = [(1.5, 10.0), (2.5, 4.0), (3.0, 8.0)]


@pytest.fixture
def db(tmp_path):
    """Sentetik ERP'nin gerçek dünyası: Q02'nin koşabileceği SQLite dosyası."""
    path = tmp_path / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


# ------------------------------------------------------------------ biçimler


def test_one_date_and_numbers_become_a_line_with_an_ascending_axis():
    spec = chart.chart_spec(DATE_COLUMNS, DATE_ROWS, "Günlük ciro ne kadar?")

    assert spec["type"] == "line"
    option = spec["option"]
    assert [item["type"] for item in option["series"]] == ["line", "line"]
    assert option["xAxis"]["data"] == ["2026-09-01", "2026-09-02", "2026-09-03"], "x artan sıralanır"
    assert option["series"][0]["data"] == [100.0, 200.0, 300.0], "seri aynı sırayı izler"
    assert option["tooltip"]["trigger"] == "axis"
    assert chart.validate_option(option) == []


def test_a_category_and_one_number_become_a_bar_sorted_descending():
    spec = chart.chart_spec(BAR_COLUMNS, BAR_ROWS, "Ürüne göre satış miktarı ne?")

    assert spec["type"] == "bar"
    option = spec["option"]
    assert option["xAxis"]["data"] == ["Şeker", "Su", "Çay"], "azalan sıralanır"
    assert option["series"][0]["data"] == [90.0, 65.0, 40.0]
    assert option["series"][0]["name"] == "SATIS_MIKTARI"
    assert chart.validate_option(option) == []


def test_a_share_question_turns_a_small_result_into_a_pie():
    spec = chart.chart_spec(BAR_COLUMNS, BAR_ROWS, "Ürünlerin satış içindeki payı nasıl?")

    assert spec["type"] == "pie"
    option = spec["option"]
    assert option["series"][0]["data"] == [
        {"name": "Çay", "value": 40.0},
        {"name": "Şeker", "value": 90.0},
        {"name": "Su", "value": 65.0},
    ], "pasta dilimleri ad + değer taşır ve sırası bozulmaz"
    assert option["tooltip"]["trigger"] == "item"
    assert "xAxis" not in option, "pastada eksen yok"
    assert chart.validate_option(option) == []


def test_scatter_appears_only_when_the_relationship_is_asked():
    assert chart.chart_spec(SCATTER_COLUMNS, SCATTER_ROWS, "Fiyat ve miktar arasındaki ilişki ne?")["type"] == "scatter"
    assert chart.chart_spec(SCATTER_COLUMNS, SCATTER_ROWS, "Fiyat ve miktar ne kadar?") is None


def test_the_scatter_series_carries_point_pairs_on_value_axes():
    spec = chart.chart_spec(SCATTER_COLUMNS, SCATTER_ROWS, "Fiyat ile miktarın korelasyonu?")

    option = spec["option"]
    assert option["series"][0]["data"] == [[1.5, 10.0], [2.5, 4.0], [3.0, 8.0]]
    assert option["xAxis"]["type"] == "value" and option["yAxis"]["type"] == "value"
    assert option["bilgin"] == {"value_format": "number", "value_column": "MIKTAR", "label_column": None}
    assert chart.validate_option(option) == []


def test_the_bilgin_block_names_the_columns_and_the_number_format():
    spec = chart.chart_spec(["BOLGE", "ORAN"], [("Kuzey", 12.5), ("Güney", 30.0)], "Bölgelerin dağılımı?")

    assert spec["option"]["bilgin"] == {
        "value_format": "percent",
        "value_column": "ORAN",
        "label_column": "BOLGE",
    }


# ------------------------------------------------------------------ grafik çıkmayan haller


def test_a_result_of_one_row_has_no_chart():
    assert chart.chart_spec(BAR_COLUMNS, [("Çay", 40.0)], "Ürüne göre satış?") is None
    assert chart.chart_spec(BAR_COLUMNS, [], "Ürüne göre satış?") is None


def test_a_bar_over_the_readable_row_cap_has_no_chart():
    rows = [(f"URUN{i}", float(i)) for i in range(config.CHART_BAR_MAX_ROWS + 1)]

    assert chart.chart_spec(BAR_COLUMNS, rows, "Ürüne göre satış?") is None


def test_a_result_that_mixes_shapes_has_no_chart():
    columns = ["TARIH", "A", "B", "C", "D"]
    rows = [("2026-09-01", 1.0, 2.0, 3.0, 4.0), ("2026-09-02", 2.0, 3.0, 4.0, 5.0)]

    assert chart.chart_spec(columns, rows, "Hepsinin günlük seyri ne?") is None


def test_a_result_without_a_number_column_has_no_chart():
    columns = ["STOK_ADI", "STOK_KODU"]
    rows = [("Çay", "STK0001"), ("Şeker", "STK0002")]

    assert chart.chart_spec(columns, rows, "Ürünler hangileri?") is None


def test_a_masked_number_column_has_no_chart():
    """Maske yürütücünün işi: maskeli hücre metne döndüğü için sayı değildir, eksen de olmaz."""
    columns = ["STOK_ADI", "MAAS"]
    rows = [("Çay", "***"), ("Şeker", "***")]

    assert chart.chart_spec(columns, rows, "Kişi başı maaş ne kadar?") is None


# ------------------------------------------------------------------ paydan sütuna geri dönüş


def test_more_parts_than_the_pie_holds_fall_back_to_a_bar():
    columns = ["BOLGE", "PAY"]
    rows = [(f"B{i}", float(i + 1)) for i in range(config.CHART_PIE_MAX_PARTS + 1)]

    assert chart.chart_spec(columns, rows, "Bölgelerin payı nasıl?")["type"] == "bar"


def test_a_pie_refuses_a_non_positive_part_and_falls_back_to_a_bar():
    spec = chart.chart_spec(BAR_COLUMNS, [("Çay", 40.0), ("Şeker", -90.0), ("Su", 65.0)], "Ürünlerin payı dağılımı?")

    assert spec["type"] == "bar"


# ------------------------------------------------------------------ seçeneğin doğrulanması


def test_an_unknown_series_type_is_a_problem():
    option = {"xAxis": {"type": "category", "data": ["a"]}, "yAxis": {}, "series": [{"type": "funnel", "data": [1]}]}

    assert chart.validate_option(option) == ["Bilinmeyen seri türü: funnel"]


def test_a_cartesian_series_without_axes_is_a_problem():
    option = {"series": [{"type": "bar", "data": [1, 2]}]}

    assert "Eksik eksen: xAxis" in chart.validate_option(option)
    assert "Eksik eksen: yAxis" in chart.validate_option(option)


def test_a_series_longer_than_the_categories_is_a_problem():
    option = {
        "xAxis": {"type": "category", "data": ["a", "b"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [1, 2, 3]}],
    }

    assert chart.validate_option(option) == ["Kategori sayısı 2, seri uzunluğu 3"]


def test_a_pie_part_without_name_or_value_is_a_problem():
    option = {"series": [{"type": "pie", "data": [{"name": "Çay"}]}]}

    assert chart.validate_option(option) == ["Pasta diliminde ad ya da değer eksik"]


def test_a_number_that_is_not_finite_is_a_problem():
    option = {
        "xAxis": {"type": "category", "data": ["a"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [math.nan]}],
    }

    problems = chart.validate_option(option)

    assert problems[0] == "Sonlu olmayan sayı: nan"
    assert "Seçenek düz JSON olarak yazılıp okunamıyor" in problems, "nan düz JSON da değildir"


def test_an_option_that_is_not_plain_json_is_a_problem():
    option = {
        "xAxis": {"type": "category", "data": ["a"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [1], "name": {"bir nesne"}}],
    }

    assert chart.validate_option(option) == ["Seçenek düz JSON olarak yazılıp okunamıyor"]


def test_a_missing_series_or_a_non_object_option_is_a_problem():
    assert chart.validate_option({}) == ["Seri yok: çizilecek bir veri dizisi bulunmuyor."]
    assert chart.validate_option(None) == ["Seçenek bir nesne değil."]


# ------------------------------------------------------------------ yol: gerçek cevap


def test_the_q02_answer_is_a_bar_with_five_bars(db, tmp_path):
    line = next(item for item in datasets.load_dataset("synthetic_erp").golden() if item["id"] == "Q02")
    executor = LocalExecutor(backend="sqlite", db_path=db, audit_path=tmp_path / "audit.jsonl")
    result = executor.execute(line["sql"], None, "test")

    assert not result.error, result.error
    spec = chart.chart_spec(result.columns, result.rows, line["question"])

    assert spec["type"] == "bar"
    option = spec["option"]
    assert len(option["series"][0]["data"]) == 5
    assert option["series"][0]["data"] == sorted(option["series"][0]["data"], reverse=True)
    assert option["bilgin"]["value_column"] == "SATIS_MIKTARI"
    assert option["bilgin"]["label_column"] == "STOK_ADI"
    assert chart.validate_option(option) == []
    assert json.loads(json.dumps(spec))["type"] == "bar", "seçenek düz JSON kalır"
