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


# T377 (M24 görsel inceleme 2): kaydırmalı açıklama beş adın ikisini "1/5" sayfalayıcısının
# arkasına atıyordu — adlar artık dilimin kendi çizgisinde, dilim onlara yer açacak kadar küçük.
NARROW_CHART_PX = 330  # 390px'lik telefonda .chart'ın ölçtüğü genişlik


def test_the_pie_names_every_category_at_once_without_a_scrolling_legend():
    option = _pie_option()

    assert option.get("legend", {}).get("type") != "scroll", "adlar sayfalayıcının arkasına düşmez"
    series = option["series"][0]
    assert series["label"]["show"] is True, "ad dilimin yanında okunur"
    assert series["label"]["overflow"] == "break", "uzun ad sarar"
    assert series["labelLine"]["show"] is True, "ad dilimine çizgiyle bağlıdır"
    assert [point["name"] for point in series["data"]] == [name for name, _ in ROWS]


def test_the_pie_leaves_its_narrow_card_room_for_the_labels():
    series = _pie_option()["series"][0]
    line = series["labelLine"]
    reach = float(series["radius"].rstrip("%")) / 100 * NARROW_CHART_PX / 2
    reach += line["length"] + line["length2"] + series["label"]["width"]

    assert reach <= NARROW_CHART_PX / 2, f"etiket {reach:.0f}px'e uzanır, kartın yarısı {NARROW_CHART_PX // 2}px"
