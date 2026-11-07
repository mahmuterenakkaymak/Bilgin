# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T354: konuşmanın sahibi iki uçta da adsızdır (M21 review 2, PLAN R7-2, R7-9).

Ekran ``ask``ı konuşmayı NULL sahibiyle açar, ``--json``ınki ise sahibine makinedeki oturumun adını
yazardı: ``ask --new``ten sonra ``ask --json --conversation`` aynı konuşmayı
``Konuşma bulunamadı.`` ile reddediyordu, tersi de kırık tek kullanıcılı webde 404 oluyordu. İddia:
iki uç da konuşmayı adsız açar ve ötekisinin threadini sürdürür; ad yalnız soru günlüğünün satırında
durur (R6-9). Model ``--llm fake``, dünya kümenin kendi kurulmuş veritabanı.
"""

import getpass
import json
import re

import pytest

from bilgin import config
from bilgin.app.conversations import ConversationStore
from bilgin.cli import main as cli
from bilgin.eval import runner
from bilgin.schema_map import build

BY_ID = {line["id"]: line for line in runner.load_golden()}


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Veritabanı, günlükler ve uygulamanın kendi dosyası tmp'ye çevrilir (config çağrı anında okunur)."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(config, "AUDIT_LOG", tmp_path / "audit.jsonl")
    monkeypatch.setattr(config, "ASK_LOG", tmp_path / "asks.jsonl")
    monkeypatch.setenv("BILGIN_APP_DB", str(tmp_path / "app.db"))
    return tmp_path


def build_db(tmp):
    build.build_db(config.SEED, tmp / "test.db", tmp / "test.sql")


def ask_argv(question, *extra):
    return ["ask", question, "--llm", "fake", "--mode", "full", *extra]


def screen(argv, capsys) -> tuple[str, int]:
    """Ekranı koşar ve son satırından ``(kimlik, tur)``ı döndürür; kodun 0 olduğunu bekler."""
    code = cli.main(argv)
    out = capsys.readouterr().out

    assert code == 0, out
    match = re.search(r"Konuşma: ([0-9a-f]+) · tur (\d+)", out)
    assert match, out
    return match.group(1), int(match.group(2))


def as_json(argv, capsys) -> dict:
    """``--json``ı koşar ve stdout'daki payload'ı döndürür; kodun 0 olduğunu bekler."""
    code = cli.main(argv)
    out = capsys.readouterr().out

    assert code == 0, out
    return json.loads(out)


def stored(conversation_id) -> dict:
    return ConversationStore(config.app_db_path()).get(conversation_id)["conversation"]


def turn_numbers(conversation_id) -> list[int]:
    store = ConversationStore(config.app_db_path())
    return [turn["n"] for turn in store.get(conversation_id)["turns"]]


# ------------------------------------------------------------------ ekranın açtığını --json sürdürür


def test_the_screen_turn_continues_in_json(project, capsys):
    build_db(project)
    conversation_id, _ = screen(ask_argv(BY_ID["Q01"]["question"], "--new"), capsys)

    payload = as_json(ask_argv(BY_ID["Q02"]["question"], "--json", "--conversation", conversation_id), capsys)

    assert payload["status"] == "answered", payload["error"]
    assert (payload["conversation_id"], payload["turn"]) == (conversation_id, 2)
    assert stored(conversation_id)["username"] is None


# ------------------------------------------------------------------ --jsonın açtığını ekran sürdürür


def test_the_json_turn_continues_on_the_screen(project, capsys):
    build_db(project)
    first = as_json(ask_argv(BY_ID["Q01"]["question"], "--json", "--new"), capsys)
    conversation_id = first["conversation_id"]

    assert (first["turn"], first["status"]) == (1, "answered")
    assert stored(conversation_id)["username"] is None, "--json konuşmayı makinenin adına yazamaz"

    assert screen(ask_argv(BY_ID["Q02"]["question"], "--conversation", conversation_id), capsys) == (
        conversation_id,
        2,
    )
    third = as_json(ask_argv(BY_ID["Q03"]["question"], "--json", "--conversation", conversation_id), capsys)

    assert third["turn"] == 3, "üçüncü tur aynı threadin turudur"
    assert turn_numbers(conversation_id) == [1, 2, 3]
    assert stored(conversation_id)["username"] is None


# ------------------------------------------------------------------ ad yine günlüktedir


def test_the_os_user_still_rides_on_the_ask_log(project, capsys):
    build_db(project)
    payload = as_json(ask_argv(BY_ID["Q01"]["question"], "--json", "--new"), capsys)

    line = json.loads(config.ASK_LOG.read_text(encoding="utf-8").splitlines()[-1])

    assert line["username"] == getpass.getuser(), "yalnız konuşmanın sahibi adsızdır (R6-9)"
    assert (line["audit_id"], line["turn"]) == (payload["audit_id"], 1)
