# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T299: belirsiz ardışık soru (PLAN R7-12).

"Bu müşteriye başka ne sattık?" tek başına çözülmez: son turun satırlarında beş farklı cari varsa
hangisini kastettiğini yalnız kullanıcı bilir. ``refine.ambiguous_entity`` bunu modelden önce
ayırt eder ve şıklarını konuşmanın kendi satırlarından kurar; seçilen şık turu tamamlar ve bağlam
notunun varlığı olur. Dünya gerçek (``build_db`` ile kurulmuş sentetik ERP), model senaryolu sahte
- "şık sorulurken model hiç koşmadı" iddiası çağrı sayacından okunur.
"""

import json
import sqlite3

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.agent.clarify import CHOICE_MARKER
from nl2sql.agent.llm import ChatResponse, ToolCall
from nl2sql.app.ask import ask_payload
from nl2sql.app.conversations import ConversationStore
from nl2sql.app.session import open_session
from nl2sql.schema_map import build

CUSTOMERS_SQL = "SELECT TOP 5 CARI_KOD, CARI_ISIM FROM TBLCASABIT ORDER BY CARI_KOD"
ONE_CUSTOMER_SQL = "SELECT TOP 1 CARI_KOD, CARI_ISIM FROM TBLCASABIT ORDER BY CARI_KOD"
SALES_SQL = "SELECT TOP 3 STOK_KODU, STOK_ADI FROM TBLSTSABIT ORDER BY STOK_KODU"
LIST_QUESTION = "Beş müşteriyi listeler misin?"
FOLLOW_UP = "Bu müşteriye başka ne sattık?"
PLURAL_FOLLOW_UP = "Bunlara başka ne sattık?"


def submit(sql):
    return ChatResponse(tool_calls=[ToolCall(id="", name="submit_sql", arguments={"sql": sql})])


class Scripted:
    """Koşum başına sıradaki senaryoyu oynatan sahte model; her koşumun ilk isteğini de kaydeder."""

    def __init__(self, scripts):
        self._scripts = list(scripts)
        self._run = -1
        self.calls = 0
        self.users = []

    def client_factory(self, mode):
        self._run += 1
        return self

    def chat(self, messages, tools=None):
        self.calls += 1
        if not any(message["role"] == "assistant" for message in messages):
            self.users.append(_user(messages))
        script = self._scripts[min(self._run, len(self._scripts) - 1)]
        return fake.FakeLLM(script).chat(messages, tools)


def _user(messages) -> str:
    """Ajana giden soru: geçmiş system mesajının sonuna eklenir, kullanıcı mesajı çıplak kalır (R7-4)."""
    return next(str(message.get("content") or "") for message in messages if message["role"] == "user")


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    return tmp_path


@pytest.fixture(scope="module")
def erp_db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("conv-clarify")
    path = tmp / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture(scope="module")
def customers(erp_db):
    """İlk turun gerçekten göstereceği beş cari: şıkların beklenen içeriği."""
    with sqlite3.connect(erp_db) as conn:
        return conn.execute("SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT ORDER BY CARI_KOD LIMIT 5").fetchall()


@pytest.fixture
def store(tmp_path):
    return ConversationStore(tmp_path / "app.db")


@pytest.fixture
def world(erp_db, project):
    """``(oturum, senaryolar)`` üreteci: günlükler tmp'de, konuşma deposu çağırandan."""

    def make(scripts):
        scripted = Scripted(scripts)
        session = open_session(
            llm="fake",
            db_path=erp_db,
            audit_path=project / "audit.jsonl",
            ask_log=project / "asks.jsonl",
            client_factory=scripted.client_factory,
        )
        return session, scripted

    return make


def asked_about(session, scripted, store, first, question=FOLLOW_UP):
    """İkinci turu koşar: ``(payload, koşumdan önceki model çağrısı sayısı)``."""
    before = scripted.calls
    payload = ask_payload(session, question, mode="full", conversations=store,
                          conversation_id=first["conversation_id"])
    return payload, before


def test_a_follow_up_on_five_customers_asks_the_user_not_the_model(project, store, world, customers):
    session, scripted = world([fake.wrong_sql(CUSTOMERS_SQL), [submit(SALES_SQL)]])
    first = ask_payload(session, LIST_QUESTION, mode="full", conversations=store)

    asked, calls = asked_about(session, scripted, store, first)

    assert first["status"] == "answered"
    assert asked["status"] == "needs_clarification" and asked["turn"] == 2
    assert asked["clarification"] == {
        "question": "Hangi müşteriyi kastediyorsunuz?",
        "options": [f"{kod} ({isim})" for kod, isim in customers],
        "column": "CARI_KOD",
        # Updated 2026-10-26 (Eren: "otomatik olsun"): T365 sends the raw values next to the labels.
        "values": [kod for kod, _ in customers],
    }
    assert asked["sql"] == "" and asked["answer_text"] == "" and asked["context"] is None
    assert scripted.calls == calls, "şık sorulurken model hiç koşmaz"
    assert {line["source"] for line in records(project / "audit.jsonl")} == {f"web:{first['audit_id']}"}, \
        "şık için hiçbir SQL yürümez"

    turn = store.get(first["conversation_id"])["turns"][1]
    assert turn["status"] == "needs_clarification" and turn["sql"] is None
    assert turn["summary"]["clarification"]["column"] == "CARI_KOD"
    assert [line["turn"] for line in records(project / "asks.jsonl")] == [1, 2]


def test_the_choice_completes_the_turn_with_the_customer_itself(project, store, world, customers):
    session, scripted = world([fake.wrong_sql(CUSTOMERS_SQL), [submit(SALES_SQL)]])
    first = ask_payload(session, LIST_QUESTION, mode="full", conversations=store)
    asked, _ = asked_about(session, scripted, store, first)
    chosen = asked["clarification"]["options"][1]

    answer = ask_payload(session, FOLLOW_UP, mode="full", choice=chosen, conversations=store,
                         conversation_id=first["conversation_id"])

    assert answer["status"] == "answered" and answer["turn"] == 2 and answer["sql"] == SALES_SQL
    assert CHOICE_MARKER in scripted.users[1] and chosen in scripted.users[1], "seçim sorunun peşinden gider"

    kod, isim = customers[1]
    context = answer["context"]
    assert context["entities"] == [{"column": "CARI_KOD", "value": kod}]
    assert context["uses_turns"] == [1] and context["refines_sql_of"] is None
    assert context["line"].startswith("Önceki cevaptan: ")
    assert kod in context["line"] and isim in context["line"]
    assert "CARI_KOD" not in context["line"], "teknik kolon adı kullanıcıya görünmez"

    thread = store.get(first["conversation_id"])
    assert [turn["status"] for turn in thread["turns"]] == ["answered", "answered"]
    assert thread["turns"][1]["choice"] == chosen
    assert thread["turns"][1]["summary"]["context"]["entities"] == [{"column": "CARI_KOD", "value": kod}]


def test_one_customer_in_the_last_turn_answers_without_asking(project, store, world):
    session, scripted = world([fake.wrong_sql(ONE_CUSTOMER_SQL), [submit(SALES_SQL)]])
    first = ask_payload(session, LIST_QUESTION, mode="full", conversations=store)

    answer, calls = asked_about(session, scripted, store, first)

    assert answer["status"] == "answered" and answer["clarification"] is None
    assert answer["turn"] == 2 and answer["sql"] == SALES_SQL and answer["context"] is None
    assert scripted.calls > calls, "tek değer bellidir: soru sorulmaz, model koşar"


def test_a_plural_demonstrative_asks_nothing(project, store, world):
    session, scripted = world([fake.wrong_sql(CUSTOMERS_SQL), [submit(SALES_SQL)]])
    first = ask_payload(session, LIST_QUESTION, mode="full", conversations=store)

    answer, calls = asked_about(session, scripted, store, first, PLURAL_FOLLOW_UP)

    assert answer["status"] == "answered" and answer["clarification"] is None
    assert answer["sql"] == SALES_SQL
    assert scripted.calls > calls, "çoğul zamir birden çok varlığı kapsar: tek bir varlık sorulmaz"
