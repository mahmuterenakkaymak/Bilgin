# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T238: kullanıcının adı sorunun her halinde (PLAN R6-9, Contracts "ask record (ext.)", "audit source (ext.)").

Aynı soru üç yerde görünür: soru günlüğünün satırı, o koşumun denetim satırları ve CLI'nin ``ask --json``ı.
Ad söylendiğinde üçü de taşır; söylenmediğinde günlüğün satırında ``username`` anahtarı bile yoktur ve
denetim satırı Run 5'in ``<kaynak>:<audit_id>``sidir. Geçmiş ve ``find_ask`` adı süzer, ``_ALL`` hepsini görür.
"""

import getpass
import json
from pathlib import Path

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.app import asklog
from nl2sql.app.ask import ask_payload, replay_payload
from nl2sql.app.session import open_session
from nl2sql.cli import main as cli
from nl2sql.eval import runner
from nl2sql.schema_map import build

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
BY_ID = {line["id"]: line for line in runner.load_golden()}
PERSONEL_SQL = "SELECT PERSONEL_KODU, AD_SOYAD FROM TBLPERSONEL ORDER BY PERSONEL_KODU"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    return tmp_path


@pytest.fixture(scope="module")
def erp_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("ask-username") / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


def session_for(db, project):
    """Altın kaydı olmayan senaryo: soru cevaplanır, günlükle denetim aynı tmp dosyalara akar."""
    return open_session(
        llm="fake",
        db_path=db,
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
        client_factory=lambda mode: fake.FakeLLM(fake.wrong_sql(PERSONEL_SQL)),
    )


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _entry(**overrides):
    entry = {
        "audit_id": asklog.new_audit_id(),
        "source": "web",
        "dataset": "mini",
        "mode": "full",
        "question": "Geçen ayın net cirosu ne kadar?",
        "status": "answered",
        "sql": "SELECT SUM(MIKTAR) FROM TBLSTHAR",
        "row_count": 1,
    }
    entry.update(overrides)
    return entry


# ------------------------------------------------------------------ ask_payload: ad varsa her yerde


def test_a_username_rides_on_the_record_and_on_every_audit_line(project, erp_db):
    session = session_for(erp_db, project)
    payload = ask_payload(session, "Kimler personel?", mode="full", username="eren")

    record = records(project / "asks.jsonl")[0]
    assert record["username"] == "eren"
    assert record["source"] == "web" and record["audit_id"] == payload["audit_id"]
    assert {line["source"] for line in records(project / "audit.jsonl")} == {
        f"web:eren:{payload['audit_id']}"
    }


def test_without_a_username_the_record_has_no_key_and_the_source_is_run_5(project, erp_db):
    session = session_for(erp_db, project)
    payload = ask_payload(session, "Kimler personel?", mode="full")

    record = records(project / "asks.jsonl")[0]
    assert "username" not in record
    assert {line["source"] for line in records(project / "audit.jsonl")} == {
        f"web:{payload['audit_id']}"
    }


# ------------------------------------------------------------------ replay: yeni satır, aynı ad


def test_replay_carries_the_username_on_its_own_new_record(project, erp_db):
    session = session_for(erp_db, project)
    first = ask_payload(session, "Kimler personel?", mode="full", username="eren")
    again = replay_payload(session, first["audit_id"], username="eren")

    assert again["status"] == "answered" and again["audit_id"] != first["audit_id"]
    lines = records(project / "asks.jsonl")
    assert [line["username"] for line in lines] == ["eren", "eren"]
    assert lines[1]["audit_id"] == again["audit_id"]
    assert {line["source"] for line in records(project / "audit.jsonl")} == {
        f"web:eren:{first['audit_id']}",
        f"web:eren:{again['audit_id']}",
    }


def test_replay_of_another_users_record_is_not_found(project, erp_db):
    session = session_for(erp_db, project)
    first = ask_payload(session, "Kimler personel?", mode="full", username="eren")

    assert replay_payload(session, first["audit_id"], username="ahmet")["error"]["kind"] == "not_found"
    assert replay_payload(session, first["audit_id"])["status"] == "answered"


# ------------------------------------------------------------------ asklog: yazım ve süzme


def test_record_ask_writes_the_username_only_when_it_is_known(tmp_path):
    path = tmp_path / "logs" / "asks.jsonl"
    asklog.record_ask(_entry(username="eren"), path)
    asklog.record_ask(_entry(), path)

    lines = records(path)
    assert lines[0]["username"] == "eren"
    assert "username" not in lines[1]


def test_history_filters_by_username_while_ALL_shows_every_record(tmp_path):
    path = tmp_path / "asks.jsonl"
    asklog.record_ask(_entry(question="erenin sorusu", username="eren"), path)
    asklog.record_ask(_entry(question="kullanıcısız eski soru"), path)

    assert [item["question"] for item in asklog.history(path, username="eren")] == ["erenin sorusu"]
    assert [item["question"] for item in asklog.history(path, username=asklog._ALL)] == [
        "kullanıcısız eski soru",
        "erenin sorusu",
    ]


def test_find_ask_filters_by_username(tmp_path):
    path = tmp_path / "asks.jsonl"
    entry = _entry(username="eren")
    asklog.record_ask(entry, path)

    assert asklog.find_ask(entry["audit_id"], path)["username"] == "eren"
    assert asklog.find_ask(entry["audit_id"], path, username="eren")["audit_id"] == entry["audit_id"]
    assert asklog.find_ask(entry["audit_id"], path, username="ahmet") is None


# ------------------------------------------------------------------ CLI: makinedeki oturumun sahibi


def test_cli_ask_json_stamps_the_os_user(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(config, "AUDIT_LOG", tmp_path / "audit.jsonl")
    monkeypatch.setattr(config, "ASK_LOG", tmp_path / "asks.jsonl")
    build.build_db(config.SEED, tmp_path / "test.db", tmp_path / "test.sql")

    assert cli.main(["ask", BY_ID["Q02"]["question"], "--llm", "fake", "--mode", "full", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)

    entry = records(config.ASK_LOG)[0]
    assert entry["username"] == getpass.getuser() and entry["source"] == "cli"
    # Bekçi sorgularının kendi satırları kendi kaynaklarıyla döner; sorunun satırlarının hepsi aynı başı taşır.
    sources = {line["source"] for line in records(config.AUDIT_LOG)} - {"checks"}
    assert sources == {f"cli:{getpass.getuser()}:{payload['audit_id']}"}
