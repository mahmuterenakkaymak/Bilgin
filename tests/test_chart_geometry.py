"""T276: telefon genişliğinde grafiğin çizim alanı kutunun içinde çökmesin (M20 görsel inceleme 2).

``containLabel: True`` dönen kategori adlarını ``grid.bottom``'un İÇİNE yerleştirir: 72px'lik alt
boşluğun payını adlar yiyince 260px'lik ``.chart`` kutusundan plot'a ~40px kalıyor, beş y ekseni
etiketi (150/120/90/60/30) üst üste basıyordu. Boşluklar artık plot'un kendi payı, o yüzden iki
taraf birden doğru olmalı: option'da containLabel kapalı, kutu da üst + alt payı düştükten sonra
en az 120px plot bırakacak kadar yüksek. İddia kaynaklarda kurulur --- ızgarayı Python, kutuyu CSS
yazar --- ölçünün öteki yarısı stil dosyasında yaşadığı için.
"""

import ast
import re

from nl2sql import config
from nl2sql.report import chart

CHART_PY = config.ROOT / "nl2sql" / "report" / "chart.py"
STYLES = config.WEB_DIR / "src" / "styles.css"

MIN_PLOT_PX = 120

CHART_SRC = CHART_PY.read_text(encoding="utf-8")
CSS = re.sub(r"/\*.*?\*/", "", STYLES.read_text(encoding="utf-8"), flags=re.S)


def _const(name: str):
    tree = ast.parse(CHART_SRC)
    for node in tree.body:
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", "") == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{CHART_PY.name} içinde {name} yok")


def cartesian_grid() -> dict:
    """_cartesian'ın kurduğu ızgara: _GRID + dönen adların aldığı alt boşluk."""
    return dict(_const("_GRID"), bottom=_const("_CATEGORY_BOTTOM"))


def containlabel_writes() -> list[bool]:
    """Kaynaktaki her ``containLabel`` yazımı: dict anahtarı ya da keyword, yorumlar sayılmaz."""
    flags = []
    for node in ast.walk(ast.parse(CHART_SRC)):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "containLabel":
                    flags.append(ast.literal_eval(value))
        elif isinstance(node, ast.keyword) and node.arg == "containLabel":
            flags.append(ast.literal_eval(node.value))
    return flags


def test_no_cartesian_option_lets_the_labels_eat_the_plot():
    assert cartesian_grid()["containLabel"] is False, "containLabel dönen adları plot'un içine alır"
    # option'un ızgaraları _GRID'den türer, ama bir yardımcı sonradan açabilir: hepsi kapalı olmalı
    assert containlabel_writes() and all(flag is False for flag in containlabel_writes())

    spec = chart.chart_spec(["STOK_ADI", "SATIS_MIKTARI"], [("Çay", 40.0), ("Şeker", 90.0)], "Ürüne göre satış?")
    assert spec["option"]["grid"] == cartesian_grid(), "çizilen option başka bir ızgara taşıyor"


def test_every_chart_box_leaves_room_for_the_plot():
    heights = [int(match) for match in re.findall(r"\.chart\s*\{[^}]*?height:\s*(\d+)px", CSS)]
    assert heights, f"{STYLES.name} içinde .chart yüksekliği yok"

    grid = cartesian_grid()
    for height in heights:
        plot = height - grid["top"] - grid["bottom"]
        assert plot >= MIN_PLOT_PX, f"{height}px kutudan plot'a {plot}px kalıyor"
