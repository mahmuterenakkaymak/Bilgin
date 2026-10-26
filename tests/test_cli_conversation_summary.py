"""T353: ``ask --new/--conversation`` turunun özeti yürütülen satır sayısını da taşır (M21 review 1).

Özet columns/rows/facts/clarificationdan kurulduğu için ``summary.row_count`` varsayılan 0'da
kalıyor, oysa ``CONV_KEEP_ROWS`` kadar satır duruyor; sonraki turun bloğu bu yüzden
``Tur 1 satırlar (1 / 0)`` diyordu. Beklenen sayı burada da yürütücünün kendisinden alınır: ekranın
yürüttüğü altın SQL, aynı bütçe ve aynı maskeyle. Model ``--llm fake``.
"""

import re

import pytest

from nl2sql import config
from nl2sql.agent.context import context_block
from nl2sql.app.conversations import ConversationStore
from nl2sql.cli import main as cli
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.eval import runner
from nl2sql.schema_map import build, doc

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


def ask_argv(question, *extra):
    return ["ask", question, "--llm", "fake", "--mode", "full", *extra]


def open_conversation(argv, capsys) -> str:
    """Ekranı koşar ve ``Konuşma: <id> · tur n`` satırındaki kimliği döndürür."""
    code = cli.main(argv)
    out = capsys.readouterr().out

    assert code == 0
    match = re.search(r"Konuşma: ([0-9a-f]+) · tur", out)
    assert match, out
    return match.group(1)


def stored_summary(conversation_id) -> dict:
    """Konuşmanın 1. turunun konuşma deposundaki özeti."""
    return ConversationStore(config.app_db_path()).get(conversation_id)["turns"][0]["summary"]


def executed_rows(sql) -> int:
    """Ekranın yürüttüğü sorgunun satır sayısı: aynı yürütücü, aynı bütçe, aynı şema."""
    schema = doc.load_schema()
    executor = LocalExecutor(
        db_path=config.DB_PATH,
        allowlist=doc.allowlist(schema),
        audit_path=config.AUDIT_LOG,
        pii_schema=schema,
    )
    return len(executor.execute(sql, Budget(), "ask").rows)


# ------------------------------------------------------------------ tur konuşmaya yazılırken


def test_new_turn_stores_the_row_count(project, capsys):
    build_db(project)
    expected = executed_rows(BY_ID["Q01"]["sql"])
    assert expected >= 1  # boş bir sonuç 0 ile ayrışmaz; hatanın görüldüğü durum bu değil

    conversation_id = open_conversation(ask_argv(BY_ID["Q01"]["question"], "--new"), capsys)
    summary = stored_summary(conversation_id)

    assert summary["row_count"] == expected
    assert summary["row_count"] >= len(summary["rows"])


# ------------------------------------------------------------------ sonraki turun bloğu


def test_next_turn_block_divides_by_the_row_count(project, capsys, monkeypatch):
    build_db(project)
    conversation_id = open_conversation(ask_argv(BY_ID["Q01"]["question"], "--new"), capsys)

    handed = []
    real = cli.run_agent

    def recording(*args, **kwargs):
        handed.append(kwargs.get("history"))
        return real(*args, **kwargs)

    monkeypatch.setattr(cli, "run_agent", recording)
    code = cli.main(ask_argv(BY_ID["Q02"]["question"], "--conversation", conversation_id))
    capsys.readouterr()

    assert code == 0
    block = context_block(handed[0], None)
    match = re.search(r"Tur 1 satırlar \((\d+) / (\d+)\)", block)
    assert match, block
    shown, total = (int(value) for value in match.groups())
    assert total >= shown
    assert total > 0  # 0 / 0: satırlar varken paydanın 0 kalması, yani hatanın kendisi
