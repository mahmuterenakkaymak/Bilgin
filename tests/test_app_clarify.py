# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T186: netleştirme her yüzeyde (PLAN R5-11, R5-14).

Dünya gerçek (``build_db`` ile kurulmuş sentetik ERP), model ``--llm fake``, belirsiz satır ise
testten gelir: API soruyu şıklarıyla geri verir, şıkkın kendisi o okunuşun SQL'ini getirir, soru
günlüğü soruyu ve seçimi ayrı tutar. Ekranın üç yolu da aynı hali görür - insan çıkışı,
``ask --json`` ve ``POST /api/ask`` - ve altın soru şıklar açıldığı için cevaplanmaz kalmaz.
"""

import json

import pytest
from fastapi.testclient import TestClient

from bilgin import config
from bilgin.agent import fake
from bilgin.app.session import open_session
from bilgin.cli import main as cli
from bilgin.engine.result import Budget
from bilgin.eval import runner
from bilgin.schema_map import build
from bilgin.web.app import create_app

GOLDEN = runner.load_golden()
BY_ID = {line["id"]: line for line in GOLDEN}

# Contracts "AskPayload": hiçbir durum bu kümeden bir anahtarı eksik bırakamaz.
PAYLOAD_KEYS = {
    "status", "question", "choice", "answer_lang", "answer_text", "narration_source", "chart", "facts",
    "columns", "rows", "row_count", "truncated", "sql", "tables_used", "rules_used",
    "masked_columns", "warnings", "notes", "mode", "dataset", "model", "timings",
    "audit_id", "clarification", "error", "steps",
}

BRUT_SQL = "SELECT TOP 5 STOK_KODU, STOK_ADI FROM TBLSTSABIT ORDER BY STOK_KODU"
NET_SQL = "SELECT TOP 5 STOK_KODU, STOK_ADI FROM TBLSTSABIT ORDER BY STOK_KODU DESC"

# R5-12'nin satır biçimi; sete dosya T187'de ekleniyor, o yüzden burada test veriyor. İki okunuş
# farklı sayı veriyor ki sorunun sorması gereken hal bu olsun.
QUESTION = "Geçen ayın satışı ne kadar?"
AMBIGUOUS = [
    {
        "id": "A01",
        "question": QUESTION,
        "expect": "clarify",
        "term": "satış",
        "readings": [{"label": "Brüt", "sql": BRUT_SQL}, {"label": "Net", "sql": NET_SQL}],
    }
]
CLARIFY_QUESTION = "'satış' ile neyi kastediyorsunuz?"
OPTIONS = ["Brüt", "Net"]


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Dört yüz de tmp'ye çevrilir: ``--json`` ve oturum yolları çağrı anında config'den okur."""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(config, "AUDIT_LOG", tmp_path / "audit.jsonl")
    monkeypatch.setattr(config, "ASK_LOG", tmp_path / "asks.jsonl")
    build.build_db(config.SEED, tmp_path / "test.db", tmp_path / "test.sql")
    return tmp_path


def make_client(mode: str = "full"):
    """Belirsiz satırı testten alan sahte model: soruyu sorar, şıkkı oynatır."""
    return fake.for_golden(GOLDEN, fake.FALLBACK_SQL, mode=mode, ambiguous=AMBIGUOUS)


@pytest.fixture
def session(project):
    return open_session(
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
        client_factory=lambda mode: make_client(mode),
    )


@pytest.fixture
def api(session, project):
    return TestClient(
        create_app(session, saved_path=project / "bilgin.db", static_dir=project / "static")
    )


def ask_api(api, **body):
    response = api.post("/api/ask", json={"question": QUESTION, "mode": "full", **body})
    assert response.status_code == 200
    return response.json()


def rows_of(session, sql):
    """Okunuşun beklentisi: aynı SQL, arayüzün bütçesiyle yürütülmüş haliyle."""
    result = session.executor.execute(sql, Budget(max_rows=config.UI_MAX_ROWS), "test")
    return [list(row) for row in result.rows]


# ------------------------------------------------------------------ API: soru ve şıkkı


def test_an_ambiguous_question_comes_back_with_its_options(api):
    body = ask_api(api)

    assert body["status"] == "needs_clarification"
    assert body["clarification"] == {"question": CLARIFY_QUESTION, "options": OPTIONS}
    assert body["question"] == QUESTION and body["choice"] is None
    assert body["sql"] == "" and body["rows"] == [] and body["row_count"] == 0
    assert body["error"] is None and body["answer_text"] == "" and body["chart"] is None
    assert [step["tool"] for step in body["steps"]] == ["ask_clarification"]
    # The API payload is a conversation turn since Run 7 (PLAN R7-8): conversation_id, turn and context come on top
    # of the AskPayload keys. Updated 2026-10-26 with Eren's approval.
    assert sorted(body) == sorted(PAYLOAD_KEYS | {"conversation_id", "turn", "context"})


def test_a_choice_answers_with_that_readings_rows(api, session):
    first = ask_api(api)
    options = first["clarification"]["options"]

    brut = ask_api(api, choice=options[0])
    net = ask_api(api, choice=options[1])

    assert brut["status"] == net["status"] == "answered"
    assert brut["question"] == QUESTION and brut["choice"] == "Brüt"
    assert brut["sql"] == BRUT_SQL and brut["rows"] == rows_of(session, BRUT_SQL)
    assert net["sql"] == NET_SQL and net["rows"] == rows_of(session, NET_SQL)
    assert net["rows"] != brut["rows"], "şıkkın bir anlamı olması için okunuşlar ayrılmalı"
    assert brut["clarification"] is None, "devam eden tur yeniden sormaz"


def test_the_history_keeps_the_question_and_the_choice_apart(api):
    ask_api(api)
    ask_api(api, choice="Brüt")
    history = api.get("/api/history").json()["history"]

    assert [item["status"] for item in history] == ["answered", "needs_clarification"]
    assert history[0]["choice"] == "Brüt" and history[0]["sql"] == BRUT_SQL
    assert history[1]["choice"] is None and history[1]["question"] == QUESTION
    assert history[1]["error"] is None and history[1]["row_count"] == 0


def test_a_golden_question_is_still_answered(api):
    body = api.post(
        "/api/ask", json={"question": BY_ID["Q02"]["question"], "mode": "full"}
    ).json()

    assert body["status"] == "answered"
    assert body["clarification"] is None and body["rows"] and body["error"] is None


# ------------------------------------------------------------------ insan ekranı


def test_the_human_screen_prints_the_options_and_exits_0(project, capsys):
    code = cli.ask(
        QUESTION,
        make_client(),
        mode="full",
        db_path=project / "test.db",
        audit_path=project / "audit.jsonl",
    )
    out = capsys.readouterr().out

    assert code == 0
    assert f"Netleştirme: {CLARIFY_QUESTION}" in out
    assert "  1. Brüt" in out and "  2. Net" in out
    assert f'ask "{QUESTION}" --choice "Brüt"' in out
    assert "Cevap SQL:" not in out and "Sonuç:" not in out


def test_the_human_screen_answers_the_choice_it_was_given(project, capsys):
    code = cli.ask(
        QUESTION,
        make_client(),
        mode="full",
        db_path=project / "test.db",
        audit_path=project / "audit.jsonl",
        choice="Net",
    )
    out = capsys.readouterr().out

    assert code == 0
    assert f"Soru: {QUESTION}\nSeçilen anlam: Net" in out
    assert NET_SQL in out and "Netleştirme:" not in out


# ------------------------------------------------------------------ --json


def test_the_json_carries_the_clarification(project, capsys, monkeypatch):
    monkeypatch.setattr(cli, "make_client", lambda *args, **kwargs: make_client())

    code = cli.main(["ask", QUESTION, "--llm", "fake", "--mode", "full", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0, "netleştirme bir hata değil, çıkış kodu durumun kendisidir"
    assert payload["status"] == "needs_clarification"
    assert payload["clarification"] == {"question": CLARIFY_QUESTION, "options": OPTIONS}
    assert payload["rows"] == [] and payload["error"] is None
    assert sorted(payload) == sorted(PAYLOAD_KEYS)


def test_the_json_runs_the_choice(project, capsys, monkeypatch):
    monkeypatch.setattr(cli, "make_client", lambda *args, **kwargs: make_client())

    code = cli.main(
        ["ask", QUESTION, "--llm", "fake", "--mode", "full", "--choice", "Brüt", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["status"] == "answered" and payload["choice"] == "Brüt"
    assert payload["sql"] == BRUT_SQL and payload["rows"]
