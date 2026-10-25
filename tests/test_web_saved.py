"""T171: kayıtlı sorular ve geçmiş (PLAN R5-16).

Dünya ``test_web_api`` ile aynı: gerçek mini küme, sahte model, tmp yollar. Kayıtların dosyası
kendi, soru günlüğü kendi: kenar çubuğu ile geçmiş aynı oturumun üstünden okunur, ama ne
``bilgin.db`` ne de ``asks.jsonl`` ölçülen veritabanının içine karışmaz.
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.app.session import open_session
from nl2sql.cli import main as cli
from nl2sql.web.app import create_app
from nl2sql.web.saved import SavedStore

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"

# Contracts "saved question": kenar çubuğunun satırında fazlası olmaz.
SAVED_KEYS = {"id", "question", "mode", "sql", "dataset", "created_at"}


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    cli.build_database(dataset="mini")
    return tmp_path


@pytest.fixture
def session(project, capsys):
    """Altın kayıtları olan küme ve sahte model: iki soru sorulursa ikisi de cevaplanır."""
    capsys.readouterr()
    return open_session(
        dataset="mini",
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
    )


@pytest.fixture
def client(session, project):
    return TestClient(create_app(session, saved_path=project / "bilgin.db", static_dir=project / "static"))


def golden(session, qid):
    return next(item for item in session.dataset.golden() if item["id"] == qid)


def tables(path):
    conn = sqlite3.connect(path)
    try:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    finally:
        conn.close()


# ------------------------------------------------------------------ POST /api/saved


def test_a_saved_item_carries_only_the_contract_keys(client):
    response = client.post(
        "/api/saved", json={"question": "Ankara carileri", "mode": "full", "sql": "SELECT 1"}
    )

    assert response.status_code == 200
    item = response.json()["saved"]
    assert sorted(item) == sorted(SAVED_KEYS)
    assert (item["question"], item["mode"], item["sql"], item["dataset"]) == (
        "Ankara carileri", "full", "SELECT 1", "mini",
    )
    assert isinstance(item["id"], int) and item["created_at"]


def test_mode_and_sql_may_be_left_out(client):
    item = client.post("/api/saved", json={"question": "Kaç fatura?"}).json()["saved"]

    assert item["mode"] is None and item["sql"] is None


@pytest.mark.parametrize("body", [{"question": "   "}, {"question": ""}, {}])
def test_a_blank_question_is_not_saved(client, body):
    response = client.post("/api/saved", json=body)

    assert response.status_code == 400
    assert response.json() == {"detail": "Soru boş."}
    assert client.get("/api/saved").json()["saved"] == []


# ------------------------------------------------------------------ GET /api/saved, DELETE


def test_list_is_newest_first_and_delete_removes(client):
    first = client.post("/api/saved", json={"question": "Bir"}).json()["saved"]
    second = client.post("/api/saved", json={"question": "İki"}).json()["saved"]

    assert [item["id"] for item in client.get("/api/saved").json()["saved"]] == [second["id"], first["id"]]
    assert client.delete(f"/api/saved/{first['id']}").status_code == 200
    assert [item["id"] for item in client.get("/api/saved").json()["saved"]] == [second["id"]]


def test_deleting_an_unknown_id_is_404(client):
    response = client.delete("/api/saved/424242")

    assert response.status_code == 404
    assert response.json() == {"detail": "Kayıtlı soru bulunamadı."}


def test_a_store_lists_only_the_dataset_it_is_asked_for(project):
    store = SavedStore(project / "bilgin.db")
    store.add("Mini sorusu", dataset="mini")
    store.add("Başka kümenin sorusu", dataset="wwi")

    assert [item["question"] for item in store.list("mini")] == ["Mini sorusu"]
    assert {item["dataset"] for item in store.list()} == {"mini", "wwi"}


# ------------------------------------------------------------------ GET /api/history


def test_history_is_empty_before_the_first_ask(client):
    assert client.get("/api/history").json()["history"] == []


def test_history_lists_both_asks_newest_first_and_never_rows(client, session):
    first, second = golden(session, "Q01")["question"], golden(session, "Q02")["question"]
    client.post("/api/ask", json={"question": first})
    client.post("/api/ask", json={"question": second})

    items = client.get("/api/history").json()["history"]
    assert [item["question"] for item in items] == [second, first]
    assert all(item["status"] == "answered" and item["sql"] for item in items)
    assert all("rows" not in item and "source" not in item for item in items)


# ------------------------------------------------------------------ ayrı dosya, ayrı hayat


def test_saving_never_touches_the_analysed_database(client, session):
    before = tables(session.db_path)

    client.post("/api/saved", json={"question": "Kayıt DByi değiştirmez", "sql": "SELECT 1"})
    client.get("/api/saved")
    client.delete("/api/saved/1")

    assert tables(session.db_path) == before
    assert "saved" not in before
