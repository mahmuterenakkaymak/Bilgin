# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T229: SPA fallback ve ``/api``nin oturum kapısı (PLAN R6-6, R6-5).

Dünya ``tests/test_web_api.py`` ile aynı - kopya, import değil: gerçek mini küme, sahte model,
tmp yollar. İki şey ölçülür. Birincisi: arayüzün kendi adresleri sunucuda tanımlı değildir, ama
hiçbiri 404 olmaz - hepsi derlenmiş ``index.html``i, bayatlamasın diye ``no-cache`` ile alır;
kararı arayüz verir. İkincisi: depo kurulduğunda ``/api`` altındaki her çağrı, matriste olmayan
bir yol dahil, oturumsuz JSON 401 görür. Sayfa ve asset ise oturum bilmez - giriş ekranı da
onlarla açılır.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.web.app import NO_UI, create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"

PAROLA = "Bilgin2026!erp"
YANLIS = "YanlisParola2026!"
BAD_LOGIN = "Kullanıcı adı ya da parola hatalı."
NO_SESSION = "Oturum açmanız gerekiyor."

# Derlenmiş sayfanın yerine geçen gövde: fallbackin ne döndürdüğü birebir ölçülsün.
PAGE = "<!doctype html><title>Bilgin</title>"

# R6-6: arayüzün adresleri - sunucu bunları bilmez, hepsi aynı sayfayı ister.
DEEP_LINKS = ["/kurallar", "/harita/derin?x=1", "/nereye"]

# R6-5: matriste public yazmayan yolların örneklemi; /api/yok matriste hiç yok, kapı yine kapalı.
GATED = [
    ("GET", "/api/health"),
    ("GET", "/api/history"),
    ("GET", "/api/rules"),
    ("POST", "/api/ask"),
    ("GET", "/api/yok"),
]


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    cli.build_database(dataset="mini")
    return tmp_path


@pytest.fixture
def session(project, capsys):
    """Altın kaydı olan küme, sahte model ve tmp günlükler: sorular tanındığı için cevaplanır."""
    capsys.readouterr()
    return open_session(
        dataset="mini",
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
    )


@pytest.fixture
def static(project):
    """Derlemenin yerine geçen tmp dizin: bir sayfa ve bir asset, tıpkı ``web/static`` gibi."""
    (project / "ui" / "assets").mkdir(parents=True)
    (project / "ui" / "index.html").write_text(PAGE, encoding="utf-8")
    (project / "ui" / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    return project / "ui"


@pytest.fixture
def users(project) -> UserStore:
    """Uygulamanın kendi dosyası: kayıtlı soruların yanı, yani production'ın tek dosyası."""
    return UserStore(project / "bilgin.db")


def build(session, project, static, users=None) -> TestClient:
    return TestClient(
        create_app(session, saved_path=project / "bilgin.db", static_dir=static, users=users)
    )


@pytest.fixture
def client(session, project, static, users) -> TestClient:
    users.add_user("eren", PAROLA, "admin")
    return build(session, project, static, users)


@pytest.fixture
def solo(session, project, static) -> TestClient:
    """Run 5: depo yok, kapı yok - fallbackin eski davranışa hiçbir şey eklemediği dünya."""
    return build(session, project, static)


def login(client, password=PAROLA):
    return client.post("/api/auth/login", json={"username": "eren", "password": password})


def call(client, method, path, body=None):
    if method == "GET":
        return client.get(path)
    return client.post(path, json=body if body is not None else {})


def golden(session) -> str:
    return next(item for item in session.dataset.golden() if item["id"] == "Q01")["question"]


# ------------------------------------------------------------------ derin bağlantı


@pytest.mark.parametrize("path", DEEP_LINKS)
def test_a_typed_deep_link_returns_the_page_and_never_404s(client, path):
    response = client.get(path)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text == PAGE
    # Derleme değişince bayat kopya açılmasın: sayfa her seferinde sunucuya sorulur (R6-6).
    assert response.headers["cache-control"] == "no-cache"


def test_the_root_and_the_asset_are_untouched_by_the_fallback(client):
    assert client.get("/").text == PAGE
    assert client.get("/assets/app.js").status_code == 200


def test_an_asset_that_was_never_built_is_not_the_page(client):
    response = client.get("/assets/missing.js")

    assert response.status_code == 404
    assert not response.headers["content-type"].startswith("text/html")


def test_a_deep_link_without_a_build_shows_the_build_hint(session, project, users):
    client = build(session, project, project / "static", users)

    response = client.get("/nereye")
    assert response.status_code == 200
    assert NO_UI in response.text


# ------------------------------------------------------------------ public olan ne


def test_the_page_the_asset_and_the_login_are_open_without_a_session(client):
    assert client.get("/").status_code == 200
    assert client.get("/kurallar").status_code == 200
    assert client.get("/assets/app.js").status_code == 200

    refused = login(client, YANLIS)
    # Reddi store verdi, kapı değil: cümle kullanıcının ya da parolanın olmadığı cümle.
    assert refused.status_code == 401
    assert refused.json() == {"detail": BAD_LOGIN}


# --------------------------------------------------------------- /api oturum ister


@pytest.mark.parametrize("method,path", GATED)
def test_every_api_route_refuses_a_missing_session(client, method, path):
    response = call(client, method, path)

    assert response.status_code == 401
    assert response.json() == {"detail": NO_SESSION}


@pytest.mark.parametrize("method,path", GATED)
def test_a_session_answers_the_routes_and_leaves_the_unknown_one_404(client, session, method, path):
    assert login(client).status_code == 200

    response = call(client, method, path, {"question": golden(session)})

    assert response.status_code == (404 if path == "/api/yok" else 200)
    assert response.headers["content-type"].startswith("application/json")


# ------------------------------------------------------------------- Run 5 değişmedi


def test_without_a_store_a_deep_link_still_returns_the_page(solo):
    assert solo.get("/kurallar").text == PAGE


def test_without_a_store_an_unknown_api_route_stays_json_404(solo):
    response = solo.get("/api/yok")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
