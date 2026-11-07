# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T464: düşmüş veritabanında sorulan soru bir konuşma turudur (PLAN R7-8, R7-25).

Dünya ``tests/test_health_db.py`` ile aynı - kopya, import değil: gerçek mini küme, tmp yollar,
gerçek ``create_app``. Canlı sunucu yoktur: bekçinin yeri, durumu her okumada ``down`` diyen bir
sapla tutulur. Ölçülen şey ekranın açtığı adres - ``App.jsx`` ``payload.conversation_id``den
``#/c/<id>`` yazıyor, yani arıza sırasındaki ilk soru konuşma doğurmazsa kullanıcının bağlanacağı
bir yer olmaz, konuşmanın içindeki soru da yeniden yüklemede kaybolur ve numara boşluğa düşer.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from nl2sql import config
from nl2sql.app.ask import DB_DOWN_MESSAGE
from nl2sql.app.session import open_session
from nl2sql.cli import main as cli
from nl2sql.web.app import create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
SORU = "Personel kodları?"


class SayanIstemci:
    """Modelin koştuğunu yakalayan istemci: bir kez bile çağrılsa test düşer."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        raise AssertionError("veritabanı düşmüşken model koştu")


def dusmus_sap() -> SimpleNamespace:
    """Bekçinin yeri: her okumada ``down`` diyen, bekletmeyi saymayan sap."""
    return SimpleNamespace(state=lambda _dataset: {"state": "down"}, kick=lambda: None)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Bir kez kurulan dünya: mini kümenin veritabanı, sahte modeli sayan oturum, tek kapı."""
    root = tmp_path_factory.mktemp("down")
    mp = MonkeyPatch()
    mp.delenv("NL2SQL_MSSQL_CONN", raising=False)
    mp.delenv("NL2SQL_BACKEND", raising=False)
    mp.setattr(config, "ROOT", root)
    mp.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    cli.build_database(dataset="mini")
    sayan = SayanIstemci()
    oturum = open_session(
        dataset="mini",
        llm="fake",
        audit_path=root / "audit.jsonl",
        ask_log=root / "asks.jsonl",
        client_factory=lambda mod: sayan,
    )
    app = create_app(
        oturum,
        saved_path=root / "bilgin.db",
        static_dir=root / "static",
        dbstatus=dusmus_sap(),
    )
    try:
        yield SimpleNamespace(app=app, store=app.state.conversations, sayan=sayan)
    finally:
        mp.undo()


def sor(client: TestClient, conversation_id: str | None = None):
    body = {"question": SORU}
    if conversation_id is not None:
        body["conversation_id"] = conversation_id
    return client.post("/api/ask", json=body)


def test_a_question_while_down_opens_its_own_conversation(world):
    cevap = sor(TestClient(world.app)).json()
    kimlik = cevap["conversation_id"]

    assert kimlik, "ekranın #/c/<id> yazacağı kimlik payload'da yok"
    assert cevap["status"] == "failed" and cevap["error"]["kind"] == "db_down"
    assert cevap["answer_text"] == DB_DOWN_MESSAGE and cevap["turn"] == 1

    tur = world.store.get(kimlik)["turns"][0]
    assert world.store.get(kimlik)["conversation"]["dataset"] == "mini"
    assert tur["status"] == "failed" and tur["answer_text"] == DB_DOWN_MESSAGE
    assert tur["question"] == SORU and tur["sql"] is None


def test_a_follow_up_while_down_is_the_next_turn(world):
    client = TestClient(world.app)
    kimlik = sor(client).json()["conversation_id"]

    cevap = sor(client, kimlik).json()
    turlar = world.store.get(kimlik)["turns"]

    assert cevap["conversation_id"] == kimlik and cevap["turn"] == 2
    assert [t["n"] for t in turlar] == [1, 2]
    assert [t["status"] for t in turlar] == ["failed", "failed"]
    assert [i["turns"] for i in world.store.list() if i["id"] == kimlik] == [2]


def test_a_foreign_conversation_id_is_still_no_conversation(world):
    baskasinin = world.store.create(username="baskasi", dataset="mini", title=SORU)

    cevap = sor(TestClient(world.app), baskasinin)

    assert cevap.status_code == 404
    assert world.store.get(baskasinin)["turns"] == []


def test_the_model_never_runs(world):
    assert sor(TestClient(world.app)).json()["error"]["kind"] == "db_down"
    assert world.sayan.calls == 0
