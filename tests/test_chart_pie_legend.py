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


def test_the_pie_has_no_legend_to_scroll():
    """T377: kaydırmalı açıklama adları sayfalayıcının arkasına atıyordu — açıklama artık hiç yok."""
    option = _pie_option()

    assert "legend" not in option, "adlar açıklamada değil, dilimin yanında okunur"
    assert option["tooltip"]["trigger"] == "item", "ad ve değer tooltip'te de durur"


def test_the_pie_draws_every_slice_label_on_its_own_line():
    """T377: dış etiket ve çizgesi geri geldi; dilimlerin ad + değer listesi olduğu gibi kalır."""
    series = _pie_option()["series"][0]

    assert series["label"]["show"] is True
    assert series["labelLine"]["show"] is True
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
