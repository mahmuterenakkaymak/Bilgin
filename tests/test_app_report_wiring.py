# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T180: cevabın raporu her ekranda (PLAN R5-1, R5-9, R5-14).

Dünya gerçek (``build_db`` ile kurulmuş sentetik ERP), model ``--llm fake``: payload'ın grafiği
ECharts'a hazır, olguları Türkçe okunuşlu, cümlesi sayıları bekçiden geçmiş cümledir; uyduran
anlatıcı şablona düşer ama yine bekçiyi geçer. Ekranın üç yolu da aynı cevabı görür: CLI'nin insan
ekranı (tablonun altındaki satırlar), ``ask --json`` ve ``POST /api/ask``.
"""

import json
import re

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.app.ask import ask_payload
from nl2sql.app.session import open_session
from nl2sql.cli import main as cli
from nl2sql.eval import runner
from nl2sql.report.chart import validate_option
from nl2sql.report.guard import allowed_values, check_text
from nl2sql.schema_map import build
from nl2sql.web.app import create_app

GOLDEN = runner.load_golden()
BY_ID = {line["id"]: line for line in GOLDEN}

PERSONEL_SQL = "SELECT PERSONEL_KODU, AD_SOYAD FROM TBLPERSONEL ORDER BY PERSONEL_KODU"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Dünya tmp'de: ``--json`` yolları çağrı anında config'den okur, oturum kendi yolunu alır."""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(config, "AUDIT_LOG", tmp_path / "audit.jsonl")
    monkeypatch.setattr(config, "ASK_LOG", tmp_path / "asks.jsonl")
    build.build_db(config.SEED, tmp_path / "test.db", tmp_path / "test.sql")
    return tmp_path


def make_session(project, client_factory=None):
    """Sahte modelli oturum: altın soru tanındığı için altın SQL'i oynatır, cümleyi kurar."""
    factory = {} if client_factory is None else {"client_factory": client_factory}
    return open_session(
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
        **factory,
    )


def guarded(payload, question):
    """Cümlenin sayıları payload'ın satır ve olgularında olmak zorunda (PLAN R5-8)."""
    allowed = allowed_values(payload["columns"], payload["rows"], payload["facts"], question)
    return check_text(payload["answer_text"], allowed)


# ------------------------------------------------------------------ payload'ın raporu


def test_an_answered_payload_carries_chart_facts_and_a_sentence(project):
    line = BY_ID["Q02"]
    payload = ask_payload(make_session(project), line["question"], mode="full")

    assert payload["status"] == "answered"
    assert payload["chart"]["type"] == "bar"
    assert validate_option(payload["chart"]["option"]) == []
    assert payload["chart"]["option"]["bilgin"]["value_column"] == "SATIS_MIKTARI"
    assert payload["facts"][0] == {
        "name": "row_count", "label": "Satır sayısı", "column": None,
        "value": 5, "display": "5", "percent": False,
    }
    assert all(fact["display"] for fact in payload["facts"])
    total = next(fact for fact in payload["facts"] if fact["name"] == "total")
    assert total["column"] == "SATIS_MIKTARI"
    assert payload["narration_source"] == "llm"
    assert payload["answer_text"] and guarded(payload, line["question"]).ok
    assert payload["timings"]["narrate_s"] <= payload["timings"]["total_s"]


def test_an_inventing_narrator_falls_back_to_the_template(project, monkeypatch):
    line = BY_ID["Q02"]
    session = make_session(project)
    monkeypatch.setattr(session, "narrator", lambda: fake.inventing_narrator())
    payload = ask_payload(session, line["question"], mode="full")

    assert payload["status"] == "answered"
    assert payload["narration_source"] == "template"
    assert fake.INVENTED_NUMBER not in payload["answer_text"]
    assert guarded(payload, line["question"]).ok


def test_a_failed_payload_keeps_the_report_empty(project):
    session = make_session(
        project, client_factory=lambda mode: fake.FakeLLM(fake.never_submit())
    )
    payload = ask_payload(session, "Ürünlerin listesi?", mode="full")

    assert payload["status"] == "failed"
    assert payload["answer_text"] == payload["error"]["message"]
    assert payload["chart"] is None and payload["facts"] == []
    assert payload["narration_source"] is None and payload["timings"]["narrate_s"] == 0.0


# ------------------------------------------------------------------ ekranın üç yolu


def test_the_human_screen_adds_the_warnings_and_the_answer(project, capsys):
    code = cli.ask(
        "Kimler personel, adlarıyla?",
        fake.FakeLLM(fake.wrong_sql(PERSONEL_SQL)),
        mode="full",
        db_path=project / "test.db",
        audit_path=project / "audit.jsonl",
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "⚠ Maskelendi: AD_SOYAD — kişisel veri gösterilmez." in out
    assert out.count("Maskelendi: AD_SOYAD") == 2, "eski satır durur, uyarı ayrıca ⚠ ile basılır"
    assert re.search(r"^Cevap: \S", out, re.MULTILINE)


def test_the_json_and_the_api_carry_the_same_report(project, capsys):
    line = BY_ID["Q02"]
    assert cli.main(["ask", line["question"], "--llm", "fake", "--mode", "full", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    client = TestClient(
        create_app(
            make_session(project),
            saved_path=project / "bilgin.db",
            static_dir=project / "static",
        )
    )
    body = client.post("/api/ask", json={"question": line["question"], "mode": "full"}).json()

    assert body["status"] == payload["status"] == "answered"
    assert body["chart"] == payload["chart"]
    assert body["facts"] == payload["facts"]
    assert body["answer_text"] == payload["answer_text"]
    assert body["narration_source"] == payload["narration_source"] == "llm"
