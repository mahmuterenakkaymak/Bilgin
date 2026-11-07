# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T239: geçmiş, yeniden koşum, dışa aktarım ve kayıtlar kişinin kendi (PLAN R6-9).

Dünya ``test_web_route_matrix`` ile aynı ama her test kendi tmp'sinde koşar: sorular tek günlüğe
düşüyor, o yüzden paylaşılan bir dünya bir sonraki testi kirletirdi. İki kullanıcı ve bir yönetici
gerçek bir depodan giriş yapar; beklenti tek cümle: kimse başkasının sorusunu görmez, yönetici
hepsini görür - adı olmayan eski satırlar da yalnız yöneticide kalır.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.app import asklog
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.web.app import NO_ASK, NO_SAVED, create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
PAROLA = "Bilgin2026!erp"
ADMIN, ALI, VELI = "yonetici", "ali", "veli"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    cli.build_database(dataset="mini")
    return tmp_path


@pytest.fixture
def session(project, capsys):
    """Altın kayıtları olan küme ve sahte model: sorulan her soru gerçekten cevaplanır."""
    capsys.readouterr()
    return open_session(
        dataset="mini",
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
    )


@pytest.fixture
def app(session, project):
    """Depolu uygulama: bir yönetici, iki kullanıcı, hepsi aynı parolayla."""
    users = UserStore(project / "bilgin.db")
    for name, role in ((ADMIN, "admin"), (ALI, "user"), (VELI, "user")):
        users.add_user(name, PAROLA, role)
    return create_app(
        session, saved_path=project / "bilgin.db", static_dir=project / "static", users=users
    )


def login(app, username) -> TestClient:
    """Giriş yapmış bir tarayıcı: her kullanıcının çerez kavanozu kendi."""
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": username, "password": PAROLA})
    assert response.status_code == 200, f"{username} giriş yapamadı: {response.status_code}"
    return client


def golden(session, qid) -> str:
    return next(item for item in session.dataset.golden() if item["id"] == qid)["question"]


def ask(app, username, question) -> str:
    """Soruyu o kullanıcıya sorar ve günlüğün kaydının kimliğini döndürür."""
    body = login(app, username).post("/api/ask", json={"question": question}).json()
    assert body["status"] == "answered", body["error"]
    return body["audit_id"]


def questions(client) -> list[str]:
    return [item["question"] for item in client.get("/api/history").json()["history"]]


# ------------------------------------------------------------------ GET /api/history


def test_history_holds_only_the_asks_of_the_one_who_asked(app, session):
    ali, veli, admin = login(app, ALI), login(app, VELI), login(app, ADMIN)
    first, second = golden(session, "Q01"), golden(session, "Q02")
    ask(app, ALI, first)
    ask(app, VELI, second)

    assert questions(ali) == [first]
    assert questions(veli) == [second]
    assert questions(admin) == [second, first]


def test_an_old_username_less_line_is_visible_only_to_the_admin(app, session, project):
    ali, admin = login(app, ALI), login(app, ADMIN)
    first = golden(session, "Q01")
    ask(app, ALI, first)
    asklog.record_ask(
        {"audit_id": "eski00000000", "question": "Eski soru", "dataset": "mini",
         "status": "answered", "sql": "SELECT 1"},
        project / "asks.jsonl",
    )

    assert questions(ali) == [first]
    assert questions(admin) == ["Eski soru", first]


# ------------------------------------------------------------------ replay ve dışa aktarım


def test_another_users_ask_is_not_there_for_replay_or_export(app, session):
    ali, veli = login(app, ALI), login(app, VELI)
    audit_id = ask(app, ALI, golden(session, "Q01"))

    denied = veli.post(f"/api/replay/{audit_id}")
    assert (denied.status_code, denied.json()) == (404, {"detail": NO_ASK})
    for ext in ("csv", "xlsx"):
        response = veli.get(f"/api/export/{audit_id}.{ext}")
        assert (response.status_code, response.json()) == (404, {"detail": NO_ASK})

    assert ali.post(f"/api/replay/{audit_id}").json()["status"] == "answered"
    assert ali.get(f"/api/export/{audit_id}.csv").status_code == 200
    assert ali.get(f"/api/export/{audit_id}.xlsx").status_code == 200


def test_the_admin_replays_and_exports_every_ask(app, session):
    ids = [ask(app, ALI, golden(session, "Q01")), ask(app, VELI, golden(session, "Q02"))]
    admin = login(app, ADMIN)

    for audit_id in ids:
        assert admin.post(f"/api/replay/{audit_id}").json()["status"] == "answered"
        assert admin.get(f"/api/export/{audit_id}.csv").status_code == 200
        assert admin.get(f"/api/export/{audit_id}.xlsx").status_code == 200


# ------------------------------------------------------------------ /api/saved


def test_saved_lists_are_separate_and_delete_stops_at_the_owner(app):
    ali, veli, admin = login(app, ALI), login(app, VELI), login(app, ADMIN)
    mine = ali.post("/api/saved", json={"question": "Ali'nin kaydı"}).json()["saved"]
    theirs = veli.post("/api/saved", json={"question": "Veli'nin kaydı"}).json()["saved"]

    assert [item["question"] for item in ali.get("/api/saved").json()["saved"]] == ["Ali'nin kaydı"]
    assert [item["question"] for item in veli.get("/api/saved").json()["saved"]] == ["Veli'nin kaydı"]
    assert len(admin.get("/api/saved").json()["saved"]) == 2

    denied = veli.delete(f"/api/saved/{mine['id']}")
    assert (denied.status_code, denied.json()) == (404, {"detail": NO_SAVED})
    assert ali.delete(f"/api/saved/{mine['id']}").status_code == 200
    assert [item["id"] for item in admin.get("/api/saved").json()["saved"]] == [theirs["id"]]
