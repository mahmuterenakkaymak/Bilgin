"""T293: konuşmalar API'si (PLAN R7-8, Contracts "conversation item", "StoredTurn",
"history item (ext.)", "ask body (ext.)").

Dünya ``tests/test_web_api.py`` ile aynı - kurulmuş mini küme, sahte model, tmp günlükler - ama
burada uygulamanın kendi konuşma deposu da vardır: ``create_app`` onu kayıtlarla aynı SQLite
dosyasına kurar. İki kimlik R6-9'un yoluyla ölçülür: başkasının konuşması bu kapıdan hiç yoktur,
yani yanıt 403 değil 404. Konuşmayı açmak hiçbir SQL koşmaz - yürütücünün denetim günlüğü bunu
kendisi söyler.
"""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.app import asklog
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.web.app import create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
PAROLA = "Bilgin2026!erp"
OWNER, OTHER = "ayse", "ali"

# Contracts "conversation item" ve "StoredTurn": ekranın okuduğu kümeler bunlardır.
ITEM_KEYS = {"id", "title", "dataset", "created_at", "updated_at", "turns"}
TURN_KEYS = {"n", "question", "choice", "status", "sql", "answer_text", "audit_id", "created_at",
             "summary"}
# Sözleşme cümlesi: olmayanla başkasınınki aynı şeyi söyler.
NOT_FOUND = {"detail": "Konuşma bulunamadı."}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    cli.build_database(dataset="mini")
    return tmp_path


@pytest.fixture
def session(project, capsys):
    """Altın kaydı olan küme ve sahte model: sorular tanındığı için cevaplanır."""
    capsys.readouterr()
    return open_session(
        dataset="mini",
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
    )


@pytest.fixture
def users(project):
    store = UserStore(project / "bilgin.db")
    store.add_user(OWNER, PAROLA, "user")
    store.add_user(OTHER, PAROLA, "user")
    return store


@pytest.fixture
def app(session, project, users):
    """İki kullanıcılı sunucu: sahipliğin 404'ü ancak iki kimlikle ölçülür."""
    return create_app(
        session, saved_path=project / "bilgin.db", static_dir=project / "static", users=users
    )


@pytest.fixture
def single(session, project):
    """Run 5'in tek kullanıcısı: kapı yok, konuşmanın sahibi NULL."""
    return create_app(session, saved_path=project / "bilgin.db", static_dir=project / "static")


def login(app, username):
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": username, "password": PAROLA})
    assert response.status_code == 200, f"{username} giriş yapamadı: {response.status_code}"
    return client


def question(session, qid):
    return next(item for item in session.dataset.golden() if item["id"] == qid)["question"]


def ask(client, text, conversation_id=None):
    response = client.post(
        "/api/ask", json={"question": text, "conversation_id": conversation_id}
    )
    assert response.status_code == 200, response.text
    return response.json()


def two_turns(client, text):
    """Aynı konuşmanın iki turu: ``(birinci, ikinci)`` payload'ları."""
    first = ask(client, text)
    return first, ask(client, text, first["conversation_id"])


def audit_lines(project):
    return len((project / "audit.jsonl").read_text(encoding="utf-8").splitlines())


# ------------------------------------------------------------------ GET /api/conversations


def test_two_turns_are_one_conversation_and_the_list_is_newest_first(app, session):
    client = login(app, OWNER)
    first, second = two_turns(client, question(session, "Q01"))

    assert first["conversation_id"] == second["conversation_id"]
    assert (first["turn"], second["turn"]) == (1, 2)

    time.sleep(1.05)  # updated_at saniye çözünürlüklü: sıralama ancak öyle ölçülebilir
    newer = ask(client, question(session, "Q02"))

    items = client.get("/api/conversations").json()["conversations"]
    assert [item["id"] for item in items] == [newer["conversation_id"], first["conversation_id"]]
    assert all(set(item) == ITEM_KEYS for item in items)
    oldest = items[-1]
    assert oldest["title"] == question(session, "Q01"), "başlık ilk sorunun kendisidir"
    assert (oldest["turns"], oldest["dataset"]) == (2, "mini")


# ------------------------------------------------------------------ GET /api/conversations/{id}


def test_opening_a_conversation_reads_the_store_and_runs_no_sql(app, session, project):
    client = login(app, OWNER)
    first, _ = two_turns(client, question(session, "Q01"))
    cid = first["conversation_id"]
    before = audit_lines(project)

    body = client.get(f"/api/conversations/{cid}").json()

    assert set(body) == {"conversation", "turns"}
    assert body["conversation"]["id"] == cid
    assert body["conversation"]["title"] == question(session, "Q01")
    assert [turn["n"] for turn in body["turns"]] == [1, 2]
    assert all(set(turn) == TURN_KEYS for turn in body["turns"])
    assert [turn["status"] for turn in body["turns"]] == ["answered", "answered"]
    assert body["turns"][0]["audit_id"] == first["audit_id"]
    assert body["turns"][0]["answer_text"] == first["answer_text"]
    assert body["turns"][0]["summary"]["columns"] == first["columns"]
    assert audit_lines(project) == before, "konuşmayı açmak SQL koşmaz"
    client.get(f"/api/conversations/{cid}")
    assert audit_lines(project) == before, "ikinci açış da koşmadı"


# ------------------------------------------------------------------ GET /api/history


def test_history_items_carry_the_conversation_and_the_turn(app, session, project):
    # Konuşma devrede değilken yazılmış bir satır: iki alanı da yoktur, ekran None okur.
    asklog.record_ask(
        {"audit_id": "eski00000001", "source": "cli", "dataset": "mini", "mode": "full",
         "question": "Eski soru", "status": "answered", "sql": "SELECT 1", "row_count": 1,
         "username": OWNER},
        project / "asks.jsonl",
    )
    client = login(app, OWNER)
    first, second = two_turns(client, question(session, "Q01"))

    items = client.get("/api/history").json()["history"]

    assert [item["audit_id"] for item in items] == [
        second["audit_id"], first["audit_id"], "eski00000001"
    ]
    assert [item["conversation_id"] for item in items[:2]] == [first["conversation_id"]] * 2
    assert [item["turn"] for item in items[:2]] == [2, 1]
    assert (items[2]["conversation_id"], items[2]["turn"]) == (None, None)


# ------------------------------------------------------------------ sahiplik


def test_another_users_conversation_is_not_there(app, session):
    client = login(app, OWNER)
    first, _ = two_turns(client, question(session, "Q01"))
    cid = first["conversation_id"]
    stranger = login(app, OTHER)

    assert stranger.get("/api/conversations").json()["conversations"] == []
    assert stranger.get(f"/api/conversations/{cid}").json() == NOT_FOUND
    assert stranger.delete(f"/api/conversations/{cid}").json() == NOT_FOUND
    assert stranger.post(
        "/api/ask", json={"question": question(session, "Q02"), "conversation_id": cid}
    ).status_code == 404, "yabancı kimlikle soru da konuşmaya düşmez"
    assert client.get(f"/api/conversations/{cid}").status_code == 200, "sahibi için yerinde"
    assert client.get(f"/api/conversations/{'0' * 32}").status_code == 404


# ------------------------------------------------------------------ DELETE


def test_delete_removes_the_conversation(app, session):
    client = login(app, OWNER)
    first, _ = two_turns(client, question(session, "Q01"))
    cid = first["conversation_id"]

    assert client.delete(f"/api/conversations/{cid}").json() == {"deleted": True}

    assert client.get(f"/api/conversations/{cid}").json() == NOT_FOUND
    assert client.get("/api/conversations").json()["conversations"] == []
    assert client.delete(f"/api/conversations/{cid}").status_code == 404, "bir kere silinir"


# ------------------------------------------------------------------ tek kullanıcı


def test_the_single_user_app_has_conversations_too(single, session):
    client = TestClient(single)
    first = ask(client, question(session, "Q01"))
    second = ask(client, question(session, "Q02"), first["conversation_id"])
    cid = first["conversation_id"]

    assert (first["turn"], second["turn"]) == (1, 2)
    body = client.get(f"/api/conversations/{cid}").json()
    assert body["conversation"]["username"] is None, "tek kullanıcının konuşması adsızdır"
    assert [turn["n"] for turn in body["turns"]] == [1, 2]
    assert [(item["title"], item["turns"]) for item in
            client.get("/api/conversations").json()["conversations"]] == [
        (question(session, "Q01"), 2)
    ]
    assert client.delete(f"/api/conversations/{cid}").json() == {"deleted": True}
