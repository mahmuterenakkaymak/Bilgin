# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T228: HTTP kimlik doğrulaması (PLAN R6-5).

Dünya ``tests/test_web_api.py`` ile aynı - kopya, import değil: gerçek mini küme, sahte model,
tmp yollar. Uygulamanın SQLite dosyası kayıtlı sorularla paylaşıldığı için production'ın biçimi
ölçülür. Çerezin bayrakları başlıktan okunur; parola ve ham anahtar hiçbir yerde aranır.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bilgin import config
from bilgin.app.session import open_session
from bilgin.auth.store import UserStore
from bilgin.cli import main as cli
from bilgin.web.app import create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"

PAROLA = "Bilgin2026!erp"
YANLIS = "YanlisParola2026!"
BAD_LOGIN = "Kullanıcı adı ya da parola hatalı."
NO_SESSION = "Oturum açmanız gerekiyor."
AUTH_OFF = "Kimlik doğrulama kapalı."


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(FIXTURE_ROOT))
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
def users(project) -> UserStore:
    """Uygulamanın kendi dosyası: kayıtlı soruların yanı, yani production'ın tek dosyası."""
    return UserStore(project / "bilgin.db")


def build(session, project, users=None) -> TestClient:
    return TestClient(
        create_app(
            session,
            saved_path=project / "bilgin.db",
            static_dir=project / "static",
            users=users,
        )
    )


@pytest.fixture
def client(session, project, users) -> TestClient:
    users.add_user("eren", PAROLA, "admin")
    return build(session, project, users)


def login(client, username="eren", password=PAROLA):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def cookie_value(response) -> str:
    return response.headers["set-cookie"].split(";")[0].split("=", 1)[1]


# ------------------------------------------------------------------------------ giriş


def test_login_answers_the_user_and_sets_the_session_cookie_with_every_flag(client):
    response = login(client)

    assert response.status_code == 200
    assert response.json() == {"username": "eren", "role": "admin", "business_role": "genel"}
    cookie = response.headers["set-cookie"].lower()
    assert f"{config.SESSION_COOKIE}=" in cookie
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie
    assert f"max-age={config.SESSION_HOURS * 3600}" in cookie


def test_wrong_password_and_unknown_user_share_one_401_body(client):
    for name, password in (("eren", YANLIS), ("yok.boyle", PAROLA)):
        response = login(client, name, password)

        assert response.status_code == 401
        assert response.json() == {"detail": BAD_LOGIN}


def test_five_failures_lock_the_username_even_with_the_right_password(client):
    for _ in range(config.LOGIN_MAX_FAILURES):
        assert login(client, "eren", YANLIS).status_code == 401

    locked = login(client)
    assert locked.status_code == 429
    assert locked.json() == {
        "detail": f"Çok fazla hatalı deneme. {config.LOCKOUT_MIN} dakika sonra yeniden deneyin."
    }


# ----------------------------------------------------------------------- oturum, çıkış


def test_me_answers_for_the_session_and_401_after_logout(client):
    login(client)

    assert client.get("/api/auth/me").json() == {
        "username": "eren",
        "role": "admin",
        "business_role": "genel",
    }
    assert client.post("/api/auth/logout").status_code == 200

    refused = client.get("/api/auth/me")
    assert refused.status_code == 401
    assert refused.json() == {"detail": NO_SESSION}


def test_logout_without_a_session_is_200(client):
    assert client.post("/api/auth/logout").status_code == 200


def test_a_cookie_the_store_does_not_know_has_no_user(client):
    client.cookies.set(config.SESSION_COOKIE, "uydurma-anahtar")

    assert client.get("/api/auth/me").status_code == 401


# ------------------------------------------------------------------------- sızmama


def test_password_and_token_stay_out_of_bodies_and_logs(session, project, users):
    users.add_user("eren", PAROLA, "user")
    client = build(session, project, users)
    line = next(item for item in session.dataset.golden() if item["id"] == "Q01")

    refused = login(client, "eren", YANLIS)
    granted = login(client)
    token = cookie_value(granted)
    responses = [
        refused,
        granted,
        client.get("/api/auth/me"),
        client.post("/api/ask", json={"question": line["question"]}),
        client.post("/api/auth/logout"),
    ]
    assert [response.status_code for response in responses] == [401, 200, 200, 200, 200]
    logs = [
        path.read_text(encoding="utf-8")
        for path in (project / "asks.jsonl", project / "audit.jsonl")
        if path.exists()
    ]
    assert logs, "sorunun cevabı günlüğe düşmedi"
    for secret in (PAROLA, YANLIS, token):
        assert all(secret not in text for text in logs)
        for response in responses:
            assert secret not in response.text


# --------------------------------------------------------------------- Run 5 modu


def test_an_app_without_users_answers_every_route_and_keeps_auth_closed(session, project):
    client = build(session, project)

    assert client.get("/api/health").status_code == 200
    assert client.get("/").status_code == 200
    for response in (
        client.get("/api/auth/me"),
        client.post("/api/auth/logout"),
        login(client),
    ):
        assert response.status_code == 404
        assert response.json() == {"detail": AUTH_OFF}
