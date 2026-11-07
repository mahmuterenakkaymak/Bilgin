# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T274: yöneticinin yeniden koşumu yöneticiye yazılır (PLAN R6-9, Contracts "ask record (ext.)").

Dünya ``test_integration_m19`` ile aynı — gerçek ``open_session``, gerçek ``UserStore``, gerçek
``create_app`` — ama her test kendi tmp'sinde koşar: sorular tek günlüğe düşüyor, paylaşılan bir
dünya bir sonraki testi kirletirdi. İddia tek cümle: yeniden soran kimse yeni satırın ve denetim
satırlarının sahibi odur; yönetici başkasının kaydını görür ama adsız soru sormaz.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bilgin import config
from bilgin.app import asklog
from bilgin.app.session import open_session
from bilgin.auth.store import UserStore
from bilgin.cli import main as cli
from bilgin.web.app import create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
PAROLA = "Bilgin2026!t274"
ADMIN, ALI = "admin", "ali"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(FIXTURE_ROOT))
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
    """Depolu uygulama: bir yönetici ve bir kullanıcı, aynı parolayla."""
    users = UserStore(project / "bilgin.db")
    users.add_user(ADMIN, PAROLA, "admin")
    users.add_user(ALI, PAROLA, "user")
    return create_app(
        session, saved_path=project / "bilgin.db", static_dir=project / "static", users=users
    )


def login(app, username) -> TestClient:
    """Giriş yapmış bir tarayıcı: her kullanıcının çerez kavanozu kendi."""
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": username, "password": PAROLA})
    assert response.status_code == 200, f"{username} giriş yapamadı: {response.status_code}"
    return client


def golden(session, qid="Q01") -> str:
    return next(item for item in session.dataset.golden() if item["id"] == qid)["question"]


def ask(client, text) -> str:
    body = client.post("/api/ask", json={"question": text}).json()
    assert body["status"] == "answered", body["error"]
    return body["audit_id"]


def records(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_the_admins_replay_is_written_with_the_admins_name(app, session, project):
    audit_id = ask(login(app, ALI), golden(session))
    admin = login(app, ADMIN)

    body = admin.post(f"/api/replay/{audit_id}").json()

    assert body["status"] == "answered", body["error"]
    newest = records(project / "asks.jsonl")[-1]
    assert (newest["audit_id"], newest["username"]) == (body["audit_id"], ADMIN)
    assert f"web:{ADMIN}:{body['audit_id']}" in {
        line["source"] for line in records(project / "audit.jsonl")
    }


def test_the_replayed_row_stays_out_of_the_who_asks_history(app, session):
    ali = login(app, ALI)
    audit_id = ask(ali, golden(session))
    body = login(app, ADMIN).post(f"/api/replay/{audit_id}").json()

    assert [item["audit_id"] for item in ali.get("/api/history").json()["history"]] == [audit_id]
    admin = login(app, ADMIN).get("/api/history").json()["history"]
    assert body["audit_id"] in [item["audit_id"] for item in admin]


def test_the_admins_replay_of_an_unanswered_record_is_also_named(app, session, project):
    asklog.record_ask(
        {"audit_id": "cevapsiz0001", "question": golden(session), "dataset": "mini", "mode": "full",
         "status": "failed", "sql": "", "error": "llm_error", "username": ALI},
        project / "asks.jsonl",
    )

    assert login(app, ADMIN).post("/api/replay/cevapsiz0001").status_code == 200

    assert records(project / "asks.jsonl")[-1]["username"] == ADMIN


def test_a_users_replay_keeps_their_own_name(app, session, project):
    ali = login(app, ALI)
    audit_id = ask(ali, golden(session))

    body = ali.post(f"/api/replay/{audit_id}").json()

    assert body["status"] == "answered", body["error"]
    newest = records(project / "asks.jsonl")[-1]
    assert (newest["audit_id"], newest["username"]) == (body["audit_id"], ALI)
    assert f"web:{ALI}:{body['audit_id']}" in {
        line["source"] for line in records(project / "audit.jsonl")
    }
