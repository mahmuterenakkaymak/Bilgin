# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T202: derlenmiş arayüzün sunulması (PLAN R5-15).

Ekran ``npm --prefix web run build`` ile ``nl2sql/web/static``e yazılıyor; API onu olduğu gibi
sunuyor. Testler derlenmiş çıktıyı okur: hangi hashli dosyaların üretildiği burada yazılı
değil, ``index.html``den okunur, yani derleme adı değişirse test de kendini toplar. Yerel
öncelik de burada denetlenir - sayfada dışarı giden tek bir adres yoktur, Bilgin açılmak için
internete ihtiyaç duymaz. Derleme yoksa (temiz klon) testler atlanır: API o durumda zaten neyin
eksik olduğunu söyleyen sayfayı sunuyor, ki onun kendi testi aşağıda.
"""

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

# Uzantının doğru türle inmesi gereken yer: ``text/plain`` gelen bir modül tarayıcıda sessizce
# reddedilir, yani ekran boş kalır.
MEDIA_TYPES = {
    ".js": ("text/javascript", "application/javascript", "text/ecmascript", "application/ecmascript"),
    ".css": ("text/css",),
}


class _References(HTMLParser):
    """Sayfanın yükledikleri: ``src`` ve ``href`` değerlerinin hepsi, sırayla."""

    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        self.urls += [value for name, value in attrs if name in ("src", "href") and value]


def references(page: str) -> list[str]:
    parser = _References()
    parser.feed(page)
    return parser.urls


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    cli.build_database(dataset="mini")
    return tmp_path


@pytest.fixture
def session(project, capsys):
    capsys.readouterr()
    return open_session(
        dataset="mini",
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
    )


def _client(session, project, static_dir: Path) -> TestClient:
    return TestClient(create_app(session, saved_path=project / "bilgin.db", static_dir=static_dir))


@pytest.fixture
def built(session, project):
    """Gerçek derlemenin üstünde kurulu istemci; derlenmemişse iddianın anlamı yok."""
    if not (config.STATIC_DIR / "index.html").is_file():
        pytest.skip(f"arayüz derlenmemiş: {BUILD_COMMAND}")
    return _client(session, project, config.STATIC_DIR)


@pytest.fixture
def empty(session, project):
    """Derlemenin olmadığı dizin: ``serve``in tek başına da çalıştığının karşılığı."""
    return _client(session, project, project / "static")


# ------------------------------------------------------------------ / ve /assets


def test_root_serves_the_built_page(built):
    response = built.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Bilgin" in response.text


def test_the_page_loads_a_script_and_a_stylesheet(built):
    urls = references(built.get("/").text)

    assert any(url.endswith(".js") for url in urls), urls
    assert any(url.endswith(".css") for url in urls), urls


def test_everything_the_page_references_is_served(built):
    for url in references(built.get("/").text):
        response = built.get(url)
        assert response.status_code == 200, f"{url} sayfada var, sunucuda yok"
        assert response.text, f"{url} boş geldi"


def test_assets_arrive_with_their_own_media_type(built):
    for url in references(built.get("/").text):
        expected = MEDIA_TYPES.get(Path(url).suffix)
        if expected is None:
            continue
        served = built.get(url).headers["content-type"].split(";")[0].strip()
        assert served in expected, f"{url} {served} olarak geldi, {expected} bekleniyordu"


def test_the_page_references_nothing_outside_the_machine(built):
    for url in references(built.get("/").text):
        # Şeması ve sunucusu olmayan adres ya göreli ya da /assets altında: yerel-öncelik.
        assert not url.startswith("//"), url
        assert urlparse(url).scheme == "", url
        assert urlparse(url).netloc == "", url


# ------------------------------------------------------------------ derleme yokken


def test_an_empty_static_dir_still_answers_with_the_build_hint(empty):
    response = empty.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Arayüz derlenmemiş" in response.text
    assert BUILD_COMMAND in response.text


def test_an_asset_that_was_never_built_is_not_invented(empty):
    assert empty.get("/assets/index-olmayan.js").status_code == 404
