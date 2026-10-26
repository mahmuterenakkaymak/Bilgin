"""T170: web API'si (PLAN R5-15).

Dünya gerçek, model ``--llm fake``, yollar tmp: ``TestClient`` kurulmuş bir oturumun üstünde koşar,
yani ``/api/ask`` ile ``ask --json`` aynı kapıdır. Sunucu testte ayağa kalkmaz - ``run_server``
yerine geçilir ve hangi adresle hangi portun istendiği oradan okunur.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.web.app import create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"

# Contracts "health" satırı: ekran başlığı bu kümenin dışına çıkmaz.
HEALTH_KEYS = {
    "status", "dataset", "db", "llm", "index", "schema_hash", "rules_hash", "mode", "budget",
}


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
def client(session, project):
    return TestClient(create_app(session, saved_path=project / "bilgin.db", static_dir=project / "static"))


def golden(session, qid):
    return next(item for item in session.dataset.golden() if item["id"] == qid)


# ------------------------------------------------------------------ POST /api/ask


def test_ask_answers_a_golden_question_and_logs_it_as_web(client, session, project):
    line = golden(session, "Q01")
    response = client.post("/api/ask", json={"question": line["question"]})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "answered"
    assert body["columns"] and body["rows"]
    assert body["sql"] and body["error"] is None
    assert body["mode"] in config.MODES and body["dataset"] == "mini" and body["model"] == "fake"
    record = json.loads((project / "asks.jsonl").read_text(encoding="utf-8").strip())
    assert record["source"] == "web" and record["audit_id"] == body["audit_id"]


def test_ask_carries_the_mode_and_the_choice(client, session):
    line = golden(session, "Q02")
    body = client.post(
        "/api/ask", json={"question": line["question"], "mode": "full", "choice": "Brüt"}
    ).json()

    assert body["status"] == "answered"
    assert body["mode"] == "full" and body["choice"] == "Brüt"


@pytest.mark.parametrize("body", [{"question": "   "}, {"question": ""}, {}])
def test_a_blank_question_is_rejected_before_any_run(client, project, body):
    response = client.post("/api/ask", json=body)

    assert response.status_code == 400
    assert response.json() == {"detail": "Soru boş."}
    assert not (project / "asks.jsonl").exists(), "koşum açılmadı, günlüğe satır düşmedi"


# ------------------------------------------------------------------ GET /api/health


def test_health_reports_the_header_state(client):
    body = client.get("/api/health").json()

    assert sorted(body) == sorted(HEALTH_KEYS)
    assert body["status"] == "ok"
    assert body["dataset"] == {"name": "mini", "display_name": "Mini (Satış/Depo)"}
    assert body["llm"] == {
        "kind": "fake", "model": "fake", "url": None, "reachable": True, "reason": None,
    }
    assert body["index"] == {"fresh": False, "reason": body["index"]["reason"], "embedder": None}
    assert body["index"]["reason"] and "build-index" in body["index"]["reason"]
    assert len(body["schema_hash"]) == 64 and body["schema_hash"] != body["rules_hash"]
    assert body["mode"]["default"] == "auto"
    assert body["mode"]["auto_full_max_tokens"] == config.AUTO_FULL_MAX_TOKENS
    assert body["mode"]["estimate"] > 0
    assert body["budget"] is None


# ------------------------------------------------------------------ örnekler ve tablolar


def test_examples_are_the_first_golden_questions(client, session):
    examples = client.get("/api/examples").json()["examples"]
    lines = session.dataset.golden()

    assert len(examples) == min(config.EXAMPLES_N, len(lines))
    assert all(sorted(item) == ["kind", "question"] for item in examples)
    assert {item["kind"] for item in examples} == {"golden"}
    assert [item["question"] for item in examples] == [line["question"] for line in lines[: len(examples)]]


def test_tables_are_the_measured_schema(client, session):
    assert client.get("/api/tables").json()["tables"] == [
        table["name"] for table in session.schema["tables"]
    ]


# ------------------------------------------------------------------ / ve /assets


def test_root_without_a_build_says_the_ui_is_missing(client):
    response = client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "Arayüz derlenmemiş" in response.text
    assert "npm --prefix web run build" in response.text


def test_root_serves_the_built_ui_and_its_assets(session, project):
    static = project / "ui"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text("<!doctype html><title>Bilgin</title>", encoding="utf-8")
    (static / "assets" / "app.js").write_text("console.log(1)", encoding="utf-8")
    client = TestClient(create_app(session, saved_path=project / "bilgin.db", static_dir=static))

    assert client.get("/").text == "<!doctype html><title>Bilgin</title>"
    assert client.get("/assets/app.js").status_code == 200


# ------------------------------------------------------------------ CLI serve


def refuse(app, host, port):
    raise AssertionError("reddedilen bir koşum sunucu açmaz")


def test_serve_refuses_a_host_outside_the_machine(project, capsys, monkeypatch):
    capsys.readouterr()
    monkeypatch.setattr(cli, "run_server", refuse)

    assert cli.serve(host="0.0.0.0", llm_kind="fake", dataset="mini") == 2
    assert "Bilgin yalnız 127.0.0.1 üzerinde çalışır" in capsys.readouterr().out


def test_serve_binds_loopback_and_names_what_it_serves(project, capsys, monkeypatch):
    seen = {}
    capsys.readouterr()
    # R6-7: sunulan uygulama oturum ister, yani koşum ancak bir yönetici varsa dinlemeye başlar.
    monkeypatch.setenv("NL2SQL_APP_DB", str(project / "app.db"))
    UserStore(project / "app.db").add_user("admin", "Bilgin2026!erp", "admin")
    monkeypatch.setattr(cli, "run_server", lambda app, host, port: seen.update(host=host, port=port))

    assert cli.serve(llm_kind="fake", dataset="mini") == 0
    assert (seen["host"], seen["port"]) == ("127.0.0.1", 8777)
    out = capsys.readouterr().out
    assert "Bilgin: http://127.0.0.1:8777" in out
    assert "veri kümesi mini" in out and "llm fake" in out
