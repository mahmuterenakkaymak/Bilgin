"""T294: ``ask --new`` / ``ask --conversation`` (PLAN R7-9).

Ekran ``ask``ı bir konuşmanın turu olabilir: ``--new`` konuşmayı açar, ``--conversation <id>``
devam ettirir; son satır ``Konuşma: <id> · tur <n>`` olur. ``--json`` aynı konuşmayı AskPayload'ın
``conversation_id``/``turn``/``context`` anahtarlarıyla taşır. Bilinmeyen kimlik tek cümle ve kod 2.
Bayraksız düz ``ask`` konuşma deposuna hiçbir satır yazmaz; model burada da ``--llm fake``.
"""

import json
import re

import pytest

from nl2sql import config
from nl2sql.app.conversations import ConversationStore
from nl2sql.cli import main as cli
from nl2sql.eval import runner
from nl2sql.schema_map import build

GOLDEN = runner.load_golden()
BY_ID = {line["id"]: line for line in GOLDEN}


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Veritabanı, günlükler ve uygulamanın kendi dosyası tmp'ye çevrilir (config çağrı anında okunur)."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(config, "AUDIT_LOG", tmp_path / "audit.jsonl")
    monkeypatch.setattr(config, "ASK_LOG", tmp_path / "asks.jsonl")
    monkeypatch.setenv("NL2SQL_APP_DB", str(tmp_path / "app.db"))
    return tmp_path


def build_db(tmp):
    build.build_db(config.SEED, tmp / "test.db", tmp / "test.sql")


# ------------------------------------------------------------------ ekran: --new sonra --conversation


def test_new_then_conversation_is_the_second_turn(project, capsys):
    build_db(project)
    code = cli.main(["ask", BY_ID["Q01"]["question"], "--llm", "fake", "--mode", "full", "--new"])
    out = capsys.readouterr().out

    assert code == 0
    match = re.search(r"Konuşma: ([0-9a-f]+) · tur 1", out)
    assert match, out
    conversation_id = match.group(1)

    code = cli.main(
        ["ask", BY_ID["Q02"]["question"], "--llm", "fake", "--mode", "full", "--conversation", conversation_id]
    )
    out = capsys.readouterr().out

    assert code == 0
    assert f"Konuşma: {conversation_id} · tur 2" in out


# ------------------------------------------------------------------ --json: payload anahtarları


def test_json_carries_the_conversation_keys(project, capsys):
    build_db(project)
    code = cli.main(
        ["ask", BY_ID["Q01"]["question"], "--llm", "fake", "--mode", "full", "--new", "--json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["status"] == "answered"
    assert payload["conversation_id"] and payload["turn"] == 1
    assert "context" in payload


# ------------------------------------------------------------------ bilinmeyen kimlik: kod 2


def test_unknown_conversation_is_one_sentence_and_code_two(project, capsys):
    build_db(project)
    code = cli.main(
        ["ask", BY_ID["Q01"]["question"], "--llm", "fake", "--mode", "full", "--conversation", "nope"]
    )
    out = capsys.readouterr().out

    assert code == 2
    assert out.strip() == "Konuşma bulunamadı."


# ------------------------------------------------------------------ bayraksız düz ask: depo boş


def test_plain_ask_writes_no_conversation(project, capsys):
    build_db(project)
    code = cli.main(["ask", BY_ID["Q01"]["question"], "--llm", "fake", "--mode", "full"])
    capsys.readouterr()

    assert code == 0
    assert ConversationStore(config.app_db_path()).list() == []
