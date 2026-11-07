# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T317: iş rolünün API kapıları (PLAN R7-16, Contracts "me / login 200" ve "users API").

Dünya ``tests/test_web_users_api.py`` ile aynı - kopya, import değil: gerçek mini küme, sahte
model, tmp yollar. İş rolü yetki rolünün yerine geçmez: satışçı da yönetici olabilir. Kırmızı
çizgi kendi üstünde: yönetici kendi iş rolünü kendi seçmez, çünkü başlangıç ekranı ondan açılır.
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

REFUSED = "Geçersiz iş rolü."
OWN = "Kendi iş rolünüzü değiştiremezsiniz."
NOT_ADMIN = "Bu işlem yalnız yöneticiye açık."


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(FIXTURE_ROOT))
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
    """Run 6'dan yazılmış bir hesap: iş rolü kolonu sonradan gelen dosyanın hâli de ölçülsün."""
    users.add_user("yonetici", PAROLA, "admin")
    return build(session, project, users)


def login(client, username, password=PAROLA):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def as_user(app, username, password=PAROLA) -> TestClient:
    """Aynı uygulamanın ayrı çerez kavanozu olan ikinci tarayıcısı, girişi yapılmış hâli."""
    client = TestClient(app)
    assert login(client, username, password).status_code == 200
    return client


def add(client, username="kullanici", role="user", business_role=None) -> dict:
    body = {"username": username, "password": PAROLA, "role": role}
    if business_role is not None:
        body["business_role"] = business_role
    response = client.post("/api/users", json=body)
    assert response.status_code == 200, response.text
    return response.json()["user"]


# ------------------------------------------------------------------ me, login


def test_login_and_me_carry_the_business_role_alongside_the_role(client):
    signed_in = login(client, "yonetici")

    assert signed_in.status_code == 200
    assert signed_in.json() == {
        "username": "yonetici",
        "role": "admin",
        "business_role": config.DEFAULT_BUSINESS_ROLE,
    }
    assert client.get("/api/auth/me").json() == signed_in.json()


def test_a_business_role_a_user_gets_comes_back_on_their_own_login(client):
    login(client, "yonetici")

    created = client.post(
        "/api/users",
        json={"username": "Ayse", "password": PAROLA, "role": "admin", "business_role": "satis"},
    )

    assert created.status_code == 200
    assert created.json()["user"]["business_role"] == "satis"
    assert created.json()["user"]["role"] == "admin", "iş rolü yetki rolünün yerine geçmez"
    worker = as_user(client.app, "ayse")
    assert worker.get("/api/auth/me").json() == {
        "username": "ayse",
        "role": "admin",
        "business_role": "satis",
    }


def test_a_user_created_without_a_business_role_reads_genel(client):
    login(client, "yonetici")

    assert add(client)["business_role"] == "genel"


# ------------------------------------------------------------------------------ ek, set


def test_an_unknown_business_role_is_refused_on_add_and_writes_nothing(client, users):
    login(client, "yonetici")

    refused = client.post(
        "/api/users",
        json={"username": "ayse", "password": PAROLA, "role": "user", "business_role": "Satis"},
    )

    assert refused.status_code == 422
    assert refused.json() == {"detail": REFUSED}
    assert [user["username"] for user in users.list_users()] == ["yonetici"]


def test_an_admin_moves_another_user_to_a_business_role(client, users):
    login(client, "yonetici")
    user = add(client, business_role="muhasebe")

    response = client.put(f"/api/users/{user['id']}", json={"business_role": "yonetim"})

    assert response.status_code == 200
    assert response.json()["user"]["business_role"] == "yonetim"
    assert response.json()["user"]["role"] == "user", "ötekileri olduğu gibi kaldı"
    assert users.get_user("kullanici")["business_role"] == "yonetim"


def test_a_business_role_an_untouched_put_leaves_alone_stays(client, users):
    login(client, "yonetici")
    user = add(client, business_role="muhasebe")

    response = client.put(f"/api/users/{user['id']}", json={"active": False})

    assert response.status_code == 200
    assert response.json()["user"]["business_role"] == "muhasebe"


def test_an_unknown_business_role_on_a_put_is_the_stores_422(client, users):
    login(client, "yonetici")
    user = add(client)

    refused = client.put(f"/api/users/{user['id']}", json={"business_role": "satici"})

    assert refused.status_code == 422
    assert refused.json() == {"detail": REFUSED}
    assert users.get_user("kullanici")["business_role"] == "genel"


# ------------------------------------------------------------------- kendi üstü


def test_no_one_changes_their_own_business_role(client, users):
    login(client, "yonetici")
    own_id = users.get_user("yonetici")["id"]

    refused = client.put(f"/api/users/{own_id}", json={"business_role": "satis"})

    assert refused.status_code == 403
    assert refused.json() == {"detail": OWN}
    assert users.get_user("yonetici")["business_role"] == "genel"


def test_a_refused_own_put_applies_neither_its_role_nor_its_business_role(client, users):
    """Tek gövde bölünmez: iş rolü geçersizse yanındaki rol de uygulanmaz, sıra reddededir."""
    login(client, "yonetici")
    own_id = users.get_user("yonetici")["id"]

    refused = client.put(f"/api/users/{own_id}", json={"role": "user", "business_role": "satis"})

    assert refused.status_code == 403
    assert refused.json() == {"detail": OWN}
    assert users.get_user("yonetici")["role"] == "admin"
    assert users.get_user("yonetici")["business_role"] == "genel"


def test_an_admin_still_changes_their_own_role_and_activity(client, users):
    users.add_user("ikinci", PAROLA, "admin")
    login(client, "yonetici")
    own_id = users.get_user("yonetici")["id"]

    response = client.put(f"/api/users/{own_id}", json={"role": "user"})

    assert response.status_code == 200
    assert response.json()["user"]["role"] == "user"


def test_a_plain_user_hits_the_admin_gate_before_the_own_id_one(client, users):
    users.add_user("kullanici", PAROLA, "user")
    worker = as_user(client.app, "kullanici")
    own_id = users.get_user("kullanici")["id"]

    refused = worker.put(f"/api/users/{own_id}", json={"business_role": "yonetim"})

    assert refused.status_code == 403
    assert refused.json() == {"detail": NOT_ADMIN}
    assert users.get_user("kullanici")["business_role"] == "genel"
