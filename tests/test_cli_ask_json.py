"""T169: ``ask --json`` (PLAN R5-14).

Ekranın yerini tek bir JSON alır: stdout'un tamamı AskPayload'dır, yani ne ``Veri kümesi`` ne
``Mod`` satırı durur orada; auto'nun düşüş notu payload'ın ``notes``undadır. Çıkış kodu durumun
kendisidir — answered/needs_clarification 0, failed 1 —, oturum kurulamıyorsa tek cümle ve kod 2.
``--json`` verilmediğinde ekran Run 1-4'ün halidir; model burada da ``--llm fake``.
"""

import json

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.cli import main as cli
from nl2sql.eval import runner
from nl2sql.schema_map import build

GOLDEN = runner.load_golden()
BY_ID = {line["id"]: line for line in GOLDEN}

# Contracts "AskPayload": hiçbir durum bu kümeden bir anahtarı eksik bırakamaz.
PAYLOAD_KEYS = {
    "status", "question", "choice", "answer_lang", "answer_text", "narration_source", "chart", "facts",
    "columns", "rows", "row_count", "truncated", "sql", "tables_used", "rules_used",
    "masked_columns", "warnings", "notes", "mode", "dataset", "model", "timings",
    "audit_id", "clarification", "error", "steps",
}


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Dört yol da tmp'ye çevrilir: ``_ask_json`` yolları çağrı anında config'den okur."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(config, "AUDIT_LOG", tmp_path / "audit.jsonl")
    monkeypatch.setattr(config, "ASK_LOG", tmp_path / "asks.jsonl")
    return tmp_path


def build_db(tmp):
    build.build_db(config.SEED, tmp / "test.db", tmp / "test.sql")


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


# ------------------------------------------------------------------ yalnız payload


def test_json_stdout_is_the_payload_alone(project, capsys):
    build_db(project)
    line = BY_ID["Q02"]
    code = cli.main(["ask", line["question"], "--llm", "fake", "--mode", "full", "--json"])
    out = capsys.readouterr().out

    assert code == 0
    # Bütün stdout çözümleniyorsa ekranda JSON'dan başka satır yoktur.
    payload = json.loads(out)
    assert sorted(payload) == sorted(PAYLOAD_KEYS)
    assert payload["status"] == "answered" and payload["rows"] and payload["error"] is None
    assert payload["question"] == line["question"] and payload["sql"] == line["sql"]
    assert payload["mode"] == "full" and payload["dataset"] is None and payload["model"] == "fake"
    assert payload["audit_id"] and payload["steps"]

    # Kaynak CLI: soru günlüğünün satırı ve denetim satırları aynı kimlikle döner (R5-4).
    entry = records(config.ASK_LOG)[0]
    assert entry["source"] == "cli" and entry["audit_id"] == payload["audit_id"]
    assert "rows" not in entry


def test_auto_keeps_its_note_inside_the_json(project, capsys, monkeypatch):
    build_db(project)
    monkeypatch.setattr(config, "AUTO_FULL_MAX_TOKENS", 0)
    code = cli.main(["ask", BY_ID["Q03"]["question"], "--llm", "fake", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["mode"] == "full" and cli.NO_INDEX_NOTE in payload["notes"]


# ------------------------------------------------------------------ failed: çıkış kodu 1


def test_a_run_that_never_submits_exits_1_with_its_error(project, capsys, monkeypatch):
    build_db(project)
    monkeypatch.setattr(
        cli, "make_client", lambda *args, **kwargs: fake.FakeLLM(fake.never_submit())
    )
    code = cli.main(["ask", "Ürünlerin listesi?", "--llm", "fake", "--mode", "full", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 1
    assert payload["status"] == "failed" and payload["error"]["kind"] == "no_submission"
    assert payload["answer_text"] == payload["error"]["message"]
    assert payload["rows"] == [] and payload["sql"] == ""
    assert sorted(payload) == sorted(PAYLOAD_KEYS)


# ------------------------------------------------------------------ oturum kurulamadı


def test_a_missing_db_is_the_cli_sentence_and_code_2(project, capsys):
    code = cli.main(["ask", "Ciro ne kadar?", "--llm", "fake", "--mode", "full", "--json"])
    out = capsys.readouterr().out

    assert code == 2
    assert "Veritabanı yok" in out and "build-db" in out
    assert "{" not in out, "kurulum hatası JSON değil tek cümledir"


# ------------------------------------------------------------------ --json yoksa ekran aynı


def test_without_json_the_screen_is_unchanged(project, capsys):
    build_db(project)
    line = BY_ID["Q02"]
    code = cli.main(["ask", line["question"], "--llm", "fake", "--mode", "full"])
    out = capsys.readouterr().out

    assert code == 0
    assert "Mod: full" in out and "Cevap SQL:" in out and line["sql"] in out
    assert '"status"' not in out and "Token:" in out
