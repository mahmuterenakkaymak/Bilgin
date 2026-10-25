"""T182: kural API'si + bayat indeks + yeniden kurma (PLAN R5-15, R5-16).

Kural dosyası tmp'ye kopyalanmış mini kümesidir: API onu yazar, imza kayar, indeks bayatlar ve
``rebuild`` tazeler. Model sahte, yollar tmp - ``TestClient`` kurulmuş bir oturumun üstünde koşar.
"""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.app.session import open_session
from nl2sql.cli import main as cli
from nl2sql.web.app import create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"


def _rule(**over):
    rule = {
        "id": "brut_ciro",
        "term": "Brüt ciro",
        "synonyms": ["brüt"],
        "definition": "KDV dahil toplam.",
        "sql_hint": "SUM(l.LineAmount)",
        "tables": ["Sales.OrderLines"],
        "markers": [r"SUM\s*\(\s*(?:\w+\.)?LineAmount"],
    }
    rule.update(over)
    return rule


@pytest.fixture
def project(tmp_path, monkeypatch, capsys):
    """Mini kümesinin tmp kopyası: db ve indeks tmp altında kurulur, asıl fixture'a yazılmaz."""
    root = tmp_path / "datasets"
    shutil.copytree(FIXTURE_ROOT / "mini", root / "mini")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(root))
    cli.build_database(dataset="mini")
    assert cli.build_index("fake", dataset="mini") == 0
    capsys.readouterr()
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
def client(session, project):
    return TestClient(create_app(session, saved_path=project / "bilgin.db", static_dir=project / "static"))


def rules_file(session) -> Path:
    return session.dataset.rules_path


def saved_rules(session) -> list[dict]:
    return json.loads(rules_file(session).read_text(encoding="utf-8"))["rules"]


def golden(session, qid) -> dict:
    return next(item for item in session.dataset.golden() if item["id"] == qid)


# ------------------------------------------------------------------ GET /api/rules


def test_get_lists_the_rules_and_reports_them_fresh(client, session):
    body = client.get("/api/rules").json()

    assert [rule["id"] for rule in body["rules"]] == [rule["id"] for rule in session.rules]
    assert body["index"] == {"fresh": True, "reason": None, "embedder": body["index"]["embedder"]}


# ------------------------------------------------------------------ POST /api/rules


def test_invalid_post_is_422_with_field_messages_and_leaves_the_file(client, session):
    before = rules_file(session).read_text(encoding="utf-8")
    response = client.post("/api/rules", json=_rule(id="Kötü Kimlik", term=""))

    assert response.status_code == 422
    assert {"id", "term"} <= {error["field"] for error in response.json()["errors"]}
    assert rules_file(session).read_text(encoding="utf-8") == before


def test_invalid_post_returns_the_errors_key(client, session):
    before = rules_file(session).read_text(encoding="utf-8")
    response = client.post("/api/rules", json=_rule(id="Kötü Kimlik", term=""))

    assert response.status_code == 422
    assert set(response.json()) == {"errors"}
    errors = response.json()["errors"]
    assert {"id", "term"} <= {error["field"] for error in errors}
    assert all(set(error) == {"field", "message"} for error in errors)
    assert rules_file(session).read_text(encoding="utf-8") == before


def test_duplicate_id_is_409(client, session):
    response = client.post("/api/rules", json=_rule(id=session.rules[0]["id"]))

    assert response.status_code == 409
    assert response.json()["detail"][0]["field"] == "id"


def test_valid_post_writes_the_rule_and_marks_the_index_stale(client, session):
    response = client.post("/api/rules", json=_rule())

    assert response.status_code == 200
    assert response.json()["index"]["fresh"] is False
    assert any(rule["id"] == "brut_ciro" for rule in saved_rules(session))
    assert client.get("/api/health").json()["index"]["fresh"] is False
    assert client.get("/api/rules").json()["index"]["fresh"] is False
    ask = client.post(
        "/api/ask", json={"question": golden(session, "Q01")["question"], "mode": "rag"}
    ).json()
    assert ask["status"] == "failed" and ask["error"]["kind"] == "index"


# ------------------------------------------------------------------ POST /api/index/rebuild


def test_rebuild_clears_the_staleness_and_rag_answers_again(client, session):
    client.post("/api/rules", json=_rule())
    assert client.get("/api/rules").json()["index"]["fresh"] is False

    response = client.post("/api/index/rebuild")

    assert response.status_code == 200
    body = response.json()
    assert body["index"]["fresh"] is True
    assert body["seconds"] >= 0
    assert sum(body["counts"].values()) > 0
    ask = client.post(
        "/api/ask", json={"question": golden(session, "Q01")["question"], "mode": "rag"}
    ).json()
    assert ask["status"] == "answered"


# ------------------------------------------------------------------ PUT /api/rules/{id}


def test_put_replaces_the_rule_with_the_same_id(client, session):
    rid = session.rules[0]["id"]
    response = client.put(f"/api/rules/{rid}", json=_rule(id=rid, term="Değişmiş terim"))

    assert response.status_code == 200
    updated = next(rule for rule in saved_rules(session) if rule["id"] == rid)
    assert updated["term"] == "Değişmiş terim"
    assert client.get("/api/rules").json()["index"]["fresh"] is False


def test_put_an_unknown_id_is_404(client, session):
    assert client.put("/api/rules/olmayan", json=_rule(id="olmayan")).status_code == 404


# ------------------------------------------------------------------ DELETE /api/rules/{id}


def test_delete_removes_the_rule(client, session):
    rid = session.rules[0]["id"]
    response = client.delete(f"/api/rules/{rid}")

    assert response.status_code == 200
    assert all(rule["id"] != rid for rule in saved_rules(session))
    assert client.get("/api/rules").json()["index"]["fresh"] is False


def test_delete_an_unknown_id_is_404(client, session):
    assert client.delete("/api/rules/olmayan").status_code == 404
