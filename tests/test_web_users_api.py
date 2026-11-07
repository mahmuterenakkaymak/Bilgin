# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T240: yöneticinin kullanıcı defteri API'si (PLAN R6-3, R6-5; Contracts "users API").

Dünya ``tests/test_web_auth.py`` ile aynı - kopya, import değil: gerçek mini küme, sahte model,
tmp yollar. Red cümleleri buraya yazıyla geçer: ekranda okunan satırın kendisi değişmesin.
Kırmızı çizgi hash: hiçbir cevabın metninde ``password_hash`` ya da ``scrypt$`` izi aranır.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.web.app import create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"

PAROLA = "Bilgin2026!erp"
YENI = "YeniParola2026!"
KISA = "Kisa26!"

AUTH_OFF = "Kimlik doğrulama kapalı."
LAST_ADMIN = "Son etkin yönetici pasifleştirilemez ya da rolü düşürülemez."
DUPLICATE = "Bu kullanıcı adı zaten var."
NOT_FOUND = "Kullanıcı bulunamadı."
NO_SESSION = "Oturum açmanız gerekiyor."
NOT_ADMIN = "Bu işlem yalnız yöneticiye açık."

# Sözleşme "User (public)": alan adları burada sabit, fazlası sızarsa test kırılır.
FIELDS = ["active", "business_role", "created_at", "id", "lang", "last_login_at", "role", "username"]


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


@pytest.fixture
def users(project) -> UserStore:
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
    """Yöneticinin olduğu bir dünya; giriş testin kendisine bırakılır, çerez böylece görünür."""
    users.add_user("yonetici", PAROLA, "admin")
    return build(session, project, users)


def login(client, username, password=PAROLA):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def as_user(app, username, password=PAROLA) -> TestClient:
    """Aynı uygulamanın ayrı çerez kavanozu olan ikinci tarayıcısı, girişi yapılmış hâli."""
    client = TestClient(app)
    assert login(client, username, password).status_code == 200
    return client


def add(client, username="kullanici", password=PAROLA, role="user") -> dict:
    response = client.post(
        "/api/users", json={"username": username, "password": password, "role": role}
    )
    assert response.status_code == 200, response.text
    return response.json()["user"]


# ------------------------------------------------------------------------------ liste, ek


def test_the_list_answers_the_public_fields_in_username_order(client, users):
    users.add_user("ayse", PAROLA, "user")
    login(client, "yonetici")

    response = client.get("/api/users")

    assert response.status_code == 200
    listed = response.json()["users"]
    assert [user["username"] for user in listed] == ["ayse", "yonetici"]
    assert [sorted(user) for user in listed] == [FIELDS, FIELDS]


def test_the_admin_creates_a_user_who_can_then_log_in(client):
    login(client, "yonetici")

    created = client.post(
        "/api/users", json={"username": "Kullanici", "password": PAROLA, "role": "user"}
    )

    assert created.status_code == 200
    user = created.json()["user"]
    assert user["username"] == "kullanici"  # ad küçük harfe katlanır
    assert user["role"] == "user" and user["active"] is True
    assert user["last_login_at"] is None
    assert login(TestClient(client.app), "kullanici").status_code == 200


def test_a_username_that_is_taken_is_refused_with_the_stores_sentence(client):
    login(client, "yonetici")
    add(client)

    refused = client.post(
        "/api/users", json={"username": "KULLANICI", "password": PAROLA, "role": "user"}
    )

    assert refused.status_code == 409
    assert refused.json() == {"detail": DUPLICATE}


def test_a_short_password_is_refused_before_anything_is_written(client, users):
    login(client, "yonetici")

    refused = client.post(
        "/api/users", json={"username": "kisa", "password": KISA, "role": "user"}
    )

    assert refused.status_code == 422
    assert refused.json() == {"detail": f"Parola en az {config.PASSWORD_MIN_LEN} karakter olmalı."}
    assert [user["username"] for user in users.list_users()] == ["yonetici"]


# ------------------------------------------------------------------------ rol, etkinlik


def test_the_role_and_the_activity_of_a_user_can_be_changed(client, users):
    login(client, "yonetici")
    user = add(client)

    response = client.put(f"/api/users/{user['id']}", json={"role": "admin", "active": False})

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "admin"
    assert response.json()["user"]["active"] is False


@pytest.mark.parametrize("body", [{"role": "user"}, {"active": False}])
def test_the_last_active_admin_cannot_be_demoted_or_deactivated(client, users, body):
    login(client, "yonetici")
    admin_id = users.get_user("yonetici")["id"]

    refused = client.put(f"/api/users/{admin_id}", json=body)

    assert refused.status_code == 409
    assert refused.json() == {"detail": LAST_ADMIN}
    assert users.get_user("yonetici")["role"] == "admin"
    assert users.get_user("yonetici")["active"] is True


def test_when_two_admins_are_active_one_of_them_can_step_down(client, users):
    users.add_user("ikinci", PAROLA, "admin")
    login(client, "yonetici")
    admin_id = users.get_user("yonetici")["id"]

    response = client.put(f"/api/users/{admin_id}", json={"role": "user"})

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "user"


def test_an_unknown_id_is_the_stores_404(client):
    login(client, "yonetici")

    refused = client.put("/api/users/9999", json={"role": "user"})

    assert refused.status_code == 404
    assert refused.json() == {"detail": NOT_FOUND}


# ---------------------------------------------------------------------- oturumun sonu


def test_deactivating_a_user_ends_their_session(client):
    login(client, "yonetici")
    user = add(client)
    worker = as_user(client.app, "kullanici")

    refused = client.put(f"/api/users/{user['id']}", json={"active": False})

    assert refused.status_code == 200
    stale = worker.get("/api/auth/me")
    assert stale.status_code == 401
    assert stale.json() == {"detail": NO_SESSION}


def test_a_password_reset_leaves_only_the_new_password_working(client):
    login(client, "yonetici")
    user = add(client)
    worker = as_user(client.app, "kullanici")

    assert client.put(f"/api/users/{user['id']}", json={"password": YENI}).status_code == 200

    assert worker.get("/api/auth/me").status_code == 401  # eski oturum da kapandı
    assert login(TestClient(client.app), "kullanici", PAROLA).status_code == 401
    assert login(TestClient(client.app), "kullanici", YENI).status_code == 200


# ----------------------------------------------------------------- yetki, kapalı mod, sızma


def test_a_user_is_refused_every_users_route(client, users):
    users.add_user("kullanici", PAROLA, "user")
    worker = as_user(client.app, "kullanici")
    admin_id = users.get_user("yonetici")["id"]

    responses = [
        worker.get("/api/users"),
        worker.post("/api/users", json={"username": "birisi", "password": PAROLA, "role": "user"}),
        worker.put(f"/api/users/{admin_id}", json={"role": "user"}),
    ]

    assert [response.status_code for response in responses] == [403, 403, 403]
    for response in responses:
        assert response.json() == {"detail": NOT_ADMIN}
    assert users.get_user("yonetici")["role"] == "admin"


def test_an_app_without_users_keeps_the_users_routes_closed(session, project):
    client = build(session, project)

    responses = [
        client.get("/api/users"),
        client.post("/api/users", json={"username": "kim", "password": PAROLA, "role": "user"}),
        client.put("/api/users/1", json={"active": False}),
    ]

    assert [response.status_code for response in responses] == [404, 404, 404]
    for response in responses:
        assert response.json() == {"detail": AUTH_OFF}


def test_no_answer_carries_a_hash_or_the_password(client):
    login(client, "yonetici")
    created = client.post(
        "/api/users", json={"username": "kullanici", "password": PAROLA, "role": "user"}
    )
    user_id = created.json()["user"]["id"]
    responses = [
        created,
        client.get("/api/users"),
        client.put(f"/api/users/{user_id}", json={"active": True}),
    ]

    assert [response.status_code for response in responses] == [200, 200, 200]
    for response in responses:
        assert "password_hash" not in response.text
        assert "scrypt$" not in response.text
        assert PAROLA not in response.text
