"""T168: ``ask_payload`` (PLAN R5-1/R5-2, Contracts AskPayload).

Dünya gerçek, model ``--llm fake``: mini kümesi ve ``build_db`` ile kurulmuş sentetik ERP dosyası.
İddialar payload'ın kendisinde - altın satırla aynı satırlar, okunan tablolar, işaretçisi vuran
kural idleri, maskenin ve uyarısının taşındığı alanlar, her durumda aynı anahtar kümesi ve koşum
başına tek satırlık soru günlüğü.
"""

import json
from pathlib import Path

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.app.ask import ask_payload
from nl2sql.app.session import open_session
from nl2sql.cli import main as cli
from nl2sql.engine.result import Budget
from nl2sql.schema_map import build

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"

# Contracts "AskPayload" satırı: hiçbir durum bu kümeden bir anahtarı eksik bırakamaz.
PAYLOAD_KEYS = {
    "status", "question", "choice", "answer_text", "narration_source", "chart", "facts",
    "columns", "rows", "row_count", "truncated", "sql", "tables_used", "rules_used",
    "masked_columns", "warnings", "notes", "mode", "dataset", "model", "timings",
    "audit_id", "clarification", "error", "steps",
}

PERSONEL_SQL = "SELECT PERSONEL_KODU, AD_SOYAD FROM TBLPERSONEL ORDER BY PERSONEL_KODU"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    return tmp_path


def build_db(tmp):
    path = tmp / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture(scope="module")
def erp_db(tmp_path_factory):
    return build_db(tmp_path_factory.mktemp("app-ask"))


def mini_session(project, capsys):
    """Altın kaydı olan küme: ``--llm fake`` soruyu tanıdığı için altın SQL'i oynatır."""
    cli.build_database(dataset="mini")
    capsys.readouterr()
    return open_session(
        dataset="mini",
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
    )


def scripted_session(db, project, script):
    """Senaryosu elle verilmiş sahte modelle oturum: altın kaydı olmayan senaryolar."""
    return open_session(
        llm="fake",
        db_path=db,
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
        client_factory=lambda mode: fake.FakeLLM(script),
    )


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ------------------------------------------------------------------ answered: altın soru


def test_a_golden_question_is_answered_with_the_golden_rows(project, capsys):
    session = mini_session(project, capsys)
    line = next(item for item in session.dataset.golden() if item["id"] == "Q01")
    payload = ask_payload(session, line["question"])
    golden = session.executor.execute(line["sql"], Budget(max_rows=config.UI_MAX_ROWS), "test")

    assert payload["status"] == "answered"
    assert payload["columns"] == golden.columns
    assert payload["rows"] == [list(row) for row in golden.rows]
    assert payload["row_count"] == golden.row_count and payload["truncated"] is golden.truncated
    assert payload["tables_used"] == sorted(table.upper() for table in line["requires_tables"])
    assert set(payload["rules_used"]) <= set(line["rules"])
    assert payload["rules_used"] == ["ciro"]
    # mode=None auto demektir: payload'a çözülmüş hali yazılır, "auto" asla düşmez.
    assert payload["mode"] in config.MODES
    assert payload["dataset"] == "mini" and payload["model"] == "fake"
    # Since T180 an answered payload carries the narrated sentence (PLAN R5-9/R5-14); this line pinned the pre-narration
    # empty text. Updated 2026-10-24 with Eren's approval.
    assert payload["error"] is None and payload["answer_text"] and payload["narration_source"] == "llm"
    assert payload["audit_id"] and payload["timings"]["agent_s"] > 0
    assert sorted(payload) == sorted(PAYLOAD_KEYS)


# ------------------------------------------------------------------ answered: maske ve uyarı


def test_a_personnel_question_comes_back_masked_with_a_warning(project, erp_db):
    session = scripted_session(erp_db, project, fake.wrong_sql(PERSONEL_SQL))
    payload = ask_payload(session, "Kimler personel, adlarıyla?", mode="full")

    assert payload["status"] == "answered"
    assert payload["masked_columns"] == ["AD_SOYAD"]
    assert [warning["code"] for warning in payload["warnings"]] == ["masked"]
    assert all(row[1].endswith(".") for row in payload["rows"]), "ad değil, baş harf gösterilir"
    assert payload["tables_used"] == ["TBLPERSONEL"]
    assert [step["tool"] for step in payload["steps"]] == ["get_schema", "run_sql", "submit_sql"]
    assert sorted(payload) == sorted(PAYLOAD_KEYS)


# ------------------------------------------------------------------ failed: her haliyle


def test_a_script_that_never_submits_fails_without_rows(project, erp_db):
    session = scripted_session(erp_db, project, fake.never_submit())
    payload = ask_payload(session, "Ürünlerin listesi?", mode="full")

    assert payload["status"] == "failed"
    assert payload["error"]["kind"] == "no_submission"
    assert payload["answer_text"] == payload["error"]["message"]
    assert payload["sql"] == "" and payload["rules_used"] == []
    assert payload["rows"] == [] and payload["columns"] == [] and payload["row_count"] == 0
    assert payload["steps"], "adımlar hatayı okumayı kolaylaştırır"
    assert sorted(payload) == sorted(PAYLOAD_KEYS)


def test_rag_without_an_index_fails_as_index(project, capsys):
    session = mini_session(project, capsys)
    payload = ask_payload(session, "Toplam ciro ne kadardır?", mode="rag")

    assert payload["status"] == "failed"
    assert payload["error"]["kind"] == "index"
    assert payload["answer_text"] == payload["error"]["message"]
    assert payload["rows"] == [] and payload["steps"] == []
    assert sorted(payload) == sorted(PAYLOAD_KEYS)


# ------------------------------------------------------------------ soru günlüğü


def test_every_call_leaves_exactly_one_ask_record(project, erp_db):
    session = scripted_session(erp_db, project, fake.wrong_sql(PERSONEL_SQL))
    payload = ask_payload(session, "Kimler personel?", mode="full", source="cli")

    lines = records(project / "asks.jsonl")
    assert len(lines) == 1
    record = lines[0]
    assert record["audit_id"] == payload["audit_id"]
    assert record["source"] == "cli"
    assert record["status"] == payload["status"]
    assert record["sql"] == payload["sql"]
    assert record["row_count"] == payload["row_count"]
    assert record["error"] is None and record["ts"] and "rows" not in record
    # Denetim satırları aynı kimlikle döner: iki log audit_id ile birleşir (R5-4).
    audit = records(project / "audit.jsonl")
    assert {line["source"] for line in audit} == {f"cli:{payload['audit_id']}"}
