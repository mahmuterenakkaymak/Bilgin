"""T212: soru ekranının ilk açılışı - yatay taşma ve simge (M17 görsel incelemesi).

Görsel incelemede her ``ask-*.png`` 660px genişlikteydi (390px'te), oysa açılış ekranı 390'dı:
``.ask-box`` ızgarasının çocukları ``min-width: auto`` kaldığı için nowrap örnek çipin metni
taban oluyor ve kutu ekranın dışına taşıyordu. Konsolda ayrıca yüklenemeyen bir adres vardı:
sayfa ``rel="icon"`` söylemediğinden her ziyaret olmayan bir /favicon.ico istiyordu. İddialar
derlenmiş çıktı üstünde kurulur - küçültücü bir kuralı yutabilir, asıl soru "tarayıcı onu
görüyor mu"; simge de sayfanın gerçekten çağırdığı adresten okunur, sabit ad yazılmaz.
"""

import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.app.session import open_session
from nl2sql.cli import main as cli
from nl2sql.web.app import BUILD_COMMAND, create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"

# Izgaranın çocukları ve çipin kendi tavanı: küçültülmüş CSS'te boşluk olmadığı için seçiciler de boşluksuz.
ASK_CHILDREN = ".ask-box>*"
CHIP = ".example-chip"


def run_npm(*argv: str) -> subprocess.CompletedProcess:
    """Depo kökünde npm; Windows'ta ``npm`` bir .cmd, o yüzden tam yolla çağrılır."""
    return subprocess.run(
        [shutil.which("npm") or "npm", *argv],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture(scope="module")
def build() -> None:
    """Ekran bir kez derlenir: iddialar sunucunun gerçekten sunduğu dosyaların üstünde."""
    result = run_npm("--prefix", "web", "run", "build")
    assert result.returncode == 0, f"{BUILD_COMMAND}: {result.stdout}{result.stderr}"
    if not (config.STATIC_DIR / "index.html").is_file():
        pytest.fail(f"derleme sayfa üretmedi: {config.STATIC_DIR}")


@pytest.fixture(scope="module")
def built_css(build) -> str:
    """Derlemenin tek stil dosyası: soru kutusunu taşıyan o, çünkü iddia onun üstünde."""
    sheets = sorted((config.STATIC_DIR / "assets").glob("*.css"))
    assert sheets, f"derlemede CSS yok: {config.STATIC_DIR / 'assets'}"
    for sheet in sheets:
        text = sheet.read_text(encoding="utf-8")
        if ".ask-box" in text:
            return text
    pytest.fail(f"derlenmiş CSS'te .ask-box yok: {[s.name for s in sheets]}")


@pytest.fixture
def client(build, tmp_path, monkeypatch, capsys) -> TestClient:
    """Gerçek oturumun üstünde gerçek uygulama: ``/`` ve ``/assets`` oradan geliyor."""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    cli.build_database(dataset="mini")
    capsys.readouterr()
    session = open_session(
        dataset="mini",
        llm="fake",
        audit_path=tmp_path / "audit.jsonl",
        ask_log=tmp_path / "asks.jsonl",
    )
    return TestClient(
        create_app(session, saved_path=tmp_path / "bilgin.db", static_dir=config.STATIC_DIR)
    )


class _IconLinks(HTMLParser):
    """Sayfadaki simge bağlantıları: ``rel``inde ``icon`` geçen her ``href``."""

    def __init__(self):
        super().__init__()
        self.hrefs = []

    def handle_starttag(self, tag, attrs):
        fields = {name: value for name, value in attrs if value}
        if tag != "link" or "icon" not in fields.get("rel", "").lower().split():
            return
        if fields.get("href"):
            self.hrefs.append(fields["href"])


def icon_links(page: str) -> list[str]:
    parser = _IconLinks()
    parser.feed(page)
    return parser.hrefs


def flat(value: str) -> str:
    """Boşluklardan arınmış metin: kaynak ve küçültülmüş çıktı aynı şekilde karşılaştırılır."""
    return re.sub(r"\s+", "", value)


def end_of_block(css: str, brace: int) -> int:
    """``brace`` konumundaki '{' ile açılan kümenin kapanışından sonraki konum."""
    depth = 0
    for index in range(brace, len(css)):
        if css[index] == "{":
            depth += 1
        elif css[index] == "}":
            depth -= 1
            if depth == 0:
                return index + 1
    pytest.fail("derlenmiş CSS'te süslü parantezler eşleşmiyor")


def base(css: str) -> str:
    """Media sorgularından arınmış kısım: ekran genişliğinden bağımsız kuralar."""
    keep, cursor = [], 0
    for match in re.finditer(r"@media([^{]*)\{", css):
        keep.append(css[cursor : match.start()])
        cursor = end_of_block(css, match.end() - 1)
    keep.append(css[cursor:])
    return "".join(keep)


def declarations(css: str, selector: str) -> list[str]:
    """``css`` kümesindeki ``selector`` kuralarının bildirimleri; seçiciler boşluksuz ölçülür."""
    out = []
    for chunk in flat(css).split("}"):
        head, brace, decls = chunk.partition("{")
        if brace and selector in head.split(","):
            out.append(decls)
    return out


# ------------------------------------------------------------------ simge


def test_the_page_names_its_own_icon(client):
    page = client.get("/").text

    hrefs = icon_links(page)
    assert hrefs, 'sayfada rel="icon" yok: tarayıcı /favicon.ico ister, 404 yer'
    for href in hrefs:
        # Yerel-öncelik: adresin sunucusu yok; ya satır içi veri ya da bu makineden gelen dosya.
        assert not href.startswith("//"), href
        assert urlparse(href).netloc == "", href
        if urlparse(href).scheme == "data":
            continue
        response = client.get(href)
        assert response.status_code == 200, f"{href} sayfada var, sunucuda yok"
        assert response.text.strip(), f"{href} boş geldi"
        assert response.headers["content-type"].startswith("image/"), href


# ------------------------------------------------------------------ ilk açılışın genişliği


def test_the_ask_box_children_can_shrink(built_css):
    """Çocuklar küçülemezse nowrap çipin metni kutuyu 390px'in dışına çıkarıyor."""
    rules = declarations(base(built_css), ASK_CHILDREN)
    assert rules, f"derlenmiş CSS'te {ASK_CHILDREN} kuralı yok"
    assert any("min-width:0" in decls for decls in rules), rules

    # min-width:0 tek başına yetmez: çipin kendi tavanı işin öbür yarısı, yoksa çip yine taşar.
    chip = declarations(base(built_css), CHIP)
    assert chip, "derlenmiş CSS'te .example-chip kuralı yok"
    assert all("max-width:100%" in decls for decls in chip), chip
    assert all("text-overflow:ellipsis" in decls for decls in chip), chip
