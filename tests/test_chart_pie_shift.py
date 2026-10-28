"""T483: pastanın dış etiketleri birbirinin üstüne basıyor (M28 görsel inceleme 2).

Beş kategorinin beşi de dilimin dışında etiket alıyor ama çakışma kuralı yok: telefon ve laptop
karelerinde adlar tek yığına basıp son sayıyı ("62") yetim bırakıyor — grafiğin kendi sayısı
okunmuyor. İddia: seri çakışanı düşeyde kaydıran bir ``labelLayout`` taşır; açıklama geri gelmez
(T377: kaydırmalı açıklama adları sayfalayıcının arkasına atıyordu) ve ızgaranın altı, aynı beş
kategorinin sütun grafiğinde aldığı alt boşluk kadar yer.
"""

from nl2sql.report import chart

COLUMNS = ["STOK_ADI", "CIRO"]
ROWS = [
    ("Emberly Steel Bottle", 1086.59),
    ("Ironbark Cast Iron Pan", 1654.24),
    ("Crestline Wool Scarf", 1743.28),
    ("Beacon Ceramic Mug", 3764.00),
    ("Hollow Oak Cutting Board", 2110.75),
]
PIE_QUESTION = "Ürünlerin ciro içindeki payı nasıl?"
BAR_QUESTION = "Ürünlere göre ciro ne kadar?"


def _option(kind: str, question: str) -> dict:
    spec = chart.chart_spec(COLUMNS, ROWS, question, kind=kind)

    assert spec["type"] == kind
    return spec["option"]


def test_a_colliding_pie_label_shifts_down_the_side_instead_of_printing_over_its_neighbour():
    option = _option("pie", PIE_QUESTION)
    series = option["series"][0]

    assert series["labelLayout"]["moveOverlap"] == "shiftY"
    assert series["label"]["show"] is True, "ad yine dilimin kendi çizgisinde okunur"
    assert chart.validate_option(option) == []


def test_the_shifted_labels_do_not_bring_the_legend_back():
    option = _option("pie", PIE_QUESTION)

    assert "legend" not in option, "adlar açıklamada değil (tests/test_chart_pie_legend.py)"
    assert option["tooltip"]["trigger"] == "item", "ad ve değer tooltip'te de durur"


def test_the_pie_bottom_grows_by_the_room_the_shifted_labels_need():
    pie = _option("pie", PIE_QUESTION)
    bar = _option("bar", BAR_QUESTION)

    assert pie["grid"]["bottom"] >= bar["grid"]["bottom"], (
        f"{len(ROWS)} kategori sütunda {bar['grid']['bottom']}px alt boşluk alıyor, "
        f"pastada {pie['grid']['bottom']}px"
    )
