"""Opening a history entry without the model (2026-10-25, Eren: "geçmişteki her soruyu baştan sorup cevap
oluşturuyor gibi"). The stored SQL runs again through the same policy and executor; the agent is never called.
An entry without an answer is asked again, an entry of another dataset is refused, an unknown id fails.
"""

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.app import asklog
from nl2sql.app.ask import ask_payload, replay_payload
from nl2sql.app.session import open_session
from nl2sql.schema_map import build

SQL = "SELECT PERSONEL_KODU FROM TBLPERSONEL ORDER BY PERSONEL_KODU"


@pytest.fixture
def session(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    db = tmp_path / "test.db"
    build.build_db(config.SEED, db, db.with_suffix(".sql"))
    calls = []

    def factory(mode):
        calls.append(mode)
        return fake.FakeLLM(fake.wrong_sql(SQL))

    s = open_session(llm="fake", db_path=db, audit_path=tmp_path / "audit.jsonl",
                     ask_log=tmp_path / "asks.jsonl", client_factory=factory)
    s.agent_calls = calls
    return s


def test_a_history_entry_reopens_without_the_agent(session):
    first = ask_payload(session, "Personel kodları?", mode="full")
    assert first["status"] == "answered"
    calls = len(session.agent_calls)

    again = replay_payload(session, first["audit_id"])

    assert len(session.agent_calls) == calls, "the agent must not run again"
    assert again["status"] == "answered" and again["sql"] == first["sql"]
    assert again["rows"] == first["rows"] and again["audit_id"] != first["audit_id"]
    assert [step["tool"] for step in again["steps"]] == ["replay"]
    assert any("Geçmişten" in note for note in again["notes"])
    assert len(list(asklog.history(session.ask_log))) == 2   # the reopening is a history line too


def test_unknown_id_fails_and_other_dataset_is_refused(session):
    assert replay_payload(session, "nope")["error"]["kind"] == "not_found"
    asklog.record_ask({"audit_id": "x1", "dataset": "wwi_real", "question": "q", "status": "answered",
                       "sql": SQL}, session.ask_log)
    assert replay_payload(session, "x1")["error"]["kind"] == "dataset"


def test_an_entry_without_an_answer_is_asked_again(session):
    asklog.record_ask({"audit_id": "f1", "question": "Personel kodları?", "status": "failed", "sql": ""},
                      session.ask_log)
    calls = len(session.agent_calls)
    payload = replay_payload(session, "f1")
    assert len(session.agent_calls) > calls and payload["status"] == "answered"
