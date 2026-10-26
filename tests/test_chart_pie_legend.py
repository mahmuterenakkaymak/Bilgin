"""T368: pastanın dilimleri telefon genişliğinde adını yitiriyor (M23 görsel inceleme 3).

İddia: pasta seçeneğinde adlar dilimin dışında değil, kutunun altında kaydırılabilir bir
açıklamada durur — ``legend`` altta (`bottom`) ve uzun kategori listesi kutuyu taşırmasın diye
``type: "scroll"``; seri de dış etiketini ve çizgisini kapatır, adı açıklama ile tooltip söyler.
Sütunda açıklama yoktur: orada adlar zaten eksenin altında tam okunur.
"""

from nl2sql.report import chart

COLUMNS = ["STOK_ADI", "CIRO"]
ROWS = [
    ("Domates Salçası", 12500.0),
    ("Kakao Tozu", 9800.0),
    ("Toz Şeker", 7400.0),
    ("Nohut 1 kg", 5100.0),
    ("Zeytinyağı 1 L", 3200.0),
]
QUESTION = "Ürünlerin ciro içindeki payı nasıl?"


def _pie_option():
    spec = chart.chart_spec(COLUMNS, ROWS, QUESTION, kind="pie")

    assert spec["type"] == "pie"
    return spec["option"]


def test_the_pie_names_its_slices_in_a_scrolled_legend_at_the_bottom():
    legend = _pie_option()["legend"]

    assert legend["bottom"] is not None, "açıklama kutunun altında durur"
    assert legend["type"] == "scroll", "uzun kategori listesi kutu içinde kayar"


def test_the_pie_stops_drawing_the_outside_labels_the_legend_already_names():
    series = _pie_option()["series"][0]

    assert series["label"]["show"] is False
    assert series["labelLine"]["show"] is False
    assert series["data"] == [{"name": name, "value": value} for name, value in ROWS], "dilimler durur"


def test_a_bar_keeps_its_names_on_the_axis_and_carries_no_legend():
    spec = chart.chart_spec(COLUMNS, ROWS, "Ürünlere göre ciro ne?", kind="bar")

    assert spec["type"] == "bar"
    assert "legend" not in spec["option"]
