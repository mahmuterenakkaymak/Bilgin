# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T303: M22 entegrasyonu - zincir gerçek kapıdan (PLAN R7-13).

Burada elle kurulmuş senaryo yok: ``open_session(llm="fake")`` + ``make_client("fake")`` +
``ConversationStore``, kurulu sentetik ERP dünyasında. F02 zinciri tur tur ``ask_payload``tan
geçer - ikinci turun system mesajı birinci turun SQL'ini taşır, üçüncü tur modeli hiç koşurmaz
ve grafiği çubuğa çevirir, konuşmaya yazılan hiçbir özet ``CONV_KEEP_ROWS``dan çok satır
taşımaz. Belirsiz bir ardışık soru da aynı kapıdan geçer: şıklarını konuşmanın kendi
satırlarından kurar, seçilen şık o turu tamamlar.
"""

import pytest

from nl2sql import config
from nl2sql.app.ask import ask_payload
from nl2sql.app.conversations import ConversationStore
from nl2sql.app.session import open_session
from nl2sql.cli import main as cli
from nl2sql.datasets import load_dataset
from nl2sql.schema_map import build

DATASET = load_dataset("synthetic_erp")
CHAINS = {chain["id"]: chain for chain in DATASET.followups()}
F02 = CHAINS["F02"]
F01_FIRST = CHAINS["F01"]["turns"][0]["question"]

# Son turun beş ürününe tekille işaret eden soru: hangisini kastettiğini yalnız kullanıcı bilir.
AMBIGUOUS = "Bu ürünün Eylül satışı?"


class Counting:
    """Gerçek ``make_client("fake")`` istemcisinin etrafında sayaç (elle senaryo yok, R7-13).

    Her ajan koşumu kendi gerçek istemcisini kurar; sayaç hepsinin toplamını, ``systems`` ise
    bloğun modele gerçekte ne taşındığını söyler.
    """

    def __init__(self):
        self.chats = 0
        self.systems = []

    def client_factory(self, mode):
        self._real = cli.make_client("fake", mode, DATASET, None)
        return self

    def chat(self, messages, tools=None):
        self.chats += 1
        self.systems.append(_system(messages))
        return self._real.chat(messages, tools)


def _system(messages) -> str:
    """Ajana giden system mesajı: geçmiş blok onun sonuna eklenir (R7-4)."""
    return next(
        (str(message.get("content") or "") for message in messages if message.get("role") == "system"), ""
    )


def run_chain(session, counter, store, chain):
    """Zinciri tek konuşmada tur tur koşar: (payloadlar, her turun başındaki model isteği sayısı)."""
    payloads, before, conversation_id = [], [], None
    for turn in chain["turns"]:
        before.append(counter.chats)
        payload = ask_payload(session, turn["question"], mode="full", conversations=store,
                              conversation_id=conversation_id)
        payloads.append(payload)
        conversation_id = payload["conversation_id"]
    return payloads, before


def ask_about_product(session, store):
    """F01'in ilk turunu koşup belirsiz ardışık soruyu sorar: ``(birinci tur, şıklar)``."""
    first = ask_payload(session, F01_FIRST, mode="full", conversations=store)
    asked = ask_payload(session, AMBIGUOUS, mode="full", conversations=store,
                        conversation_id=first["conversation_id"])
    return first, asked


@pytest.fixture(scope="module")
def erp_db(tmp_path_factory):
    folder = tmp_path_factory.mktemp("integration-m22")
    path = folder / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture
def world(erp_db, tmp_path):
    """``(oturum, sayaç, depo)``: gerçek sahte istemci yalnız sayaca sarıldı, günlükler tmp'de."""
    counter = Counting()
    session = open_session(
        "synthetic_erp", llm="fake", db_path=erp_db,
        audit_path=tmp_path / "audit.jsonl", ask_log=tmp_path / "asks.jsonl",
        client_factory=counter.client_factory,
    )
    return session, counter, ConversationStore(tmp_path / "app.db")


@pytest.fixture
def f02(world):
    """F02 zinciri tek konuşmada koşulmuş: ``(payloadlar, sayaçlar, sayaç, depo)``."""
    session, counter, store = world
    payloads, before = run_chain(session, counter, store, F02)
    return payloads, before, counter, store


# ------------------------------------------------------------------ F02 zinciri tur tur


def test_the_second_turn_is_shown_the_first_turns_query(f02):
    payloads, before, counter, _ = f02

    assert [payload["status"] for payload in payloads] == ["answered"] * 3
    assert [payload["turn"] for payload in payloads] == [1, 2, 3]
    assert [payload["sql"] for payload in payloads] == [turn["sql"] for turn in F02["turns"]]

    block = counter.systems[before[1]]
    assert f"Tur 1 sorusu: {payloads[0]['question']}" in block
    assert f"Tur 1 SQL: {payloads[0]['sql']}" in block, "takip eden soru önceki sorguyu görür"
    assert payloads[1]["context"]["uses_turns"] == [1]


def test_the_chart_wish_reruns_the_previous_query_without_the_model(f02):
    payloads, before, counter, _ = f02
    third = payloads[2]

    assert counter.chats == before[2], "sunum değişikliği modeli koşurmaz"
    assert third["status"] == "answered" and third["turn"] == 3
    assert third["sql"] == payloads[1]["sql"] and third["rows"] == payloads[1]["rows"]
    assert third["chart"]["type"] == "bar" and "reason" not in third["chart"]
    assert third["narration_source"] == "template"
    assert [step["tool"] for step in third["steps"]] == ["chart"]
    assert third["context"]["refines_sql_of"] == 2


def test_no_stored_turn_keeps_more_rows_than_the_allowance(f02):
    payloads, _, _, store = f02
    turns = store.get(payloads[0]["conversation_id"])["turns"]

    kept = [len(turn["summary"]["rows"]) for turn in turns]
    assert kept == [min(turn["summary"]["row_count"], config.CONV_KEEP_ROWS) for turn in turns]
    assert all(count <= config.CONV_KEEP_ROWS for count in kept)


# ------------------------------------------------------------------ belirsiz ardışık soru


def test_an_ambiguous_product_question_asks_its_five_options(world):
    session, counter, store = world
    first, asked = ask_about_product(session, store)

    assert first["status"] == "answered" and first["row_count"] == 5
    assert asked["status"] == "needs_clarification" and asked["turn"] == 2
    assert asked["clarification"]["question"] == "Hangi ürünü kastediyorsunuz?"
    assert asked["clarification"]["column"] == "STOK_KODU"
    assert [option.split(" (")[0] for option in asked["clarification"]["options"]] == [
        row[0] for row in first["rows"]
    ], "şıklar konuşmanın kendi satırlarıdır"
    assert counter.chats == 3, "şık sorulurken model bir kez daha koşmaz"


def test_the_choice_completes_the_ambiguous_turn_with_the_product_itself(world):
    session, _, store = world
    first, asked = ask_about_product(session, store)
    chosen = asked["clarification"]["options"][1]

    answer = ask_payload(session, AMBIGUOUS, mode="full", choice=chosen, conversations=store,
                         conversation_id=first["conversation_id"])

    assert answer["status"] == "answered" and answer["turn"] == 2, "seçim yeni tur açmaz"
    kod, ad = first["rows"][1][0], first["rows"][1][1]
    assert answer["context"]["entities"] == [{"column": "STOK_KODU", "value": kod}]
    assert answer["context"]["uses_turns"] == [1] and answer["context"]["refines_sql_of"] is None
    assert kod in answer["context"]["line"] and ad in answer["context"]["line"]
    assert "STOK_KODU" not in answer["context"]["line"], "teknik kolon adı kullanıcıya görünmez"

    turns = store.get(first["conversation_id"])["turns"]
    assert [turn["status"] for turn in turns] == ["answered", "answered"]
    assert turns[1]["choice"] == chosen
    assert turns[1]["summary"]["row_count"] > config.CONV_KEEP_ROWS
    assert len(turns[1]["summary"]["rows"]) == config.CONV_KEEP_ROWS
