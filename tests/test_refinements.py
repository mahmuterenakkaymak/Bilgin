# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T300: takibat ipuçları ve tek başına okunan soru (PLAN R7-11).

"Sadece Texas" modeli koşmaya bırakır - ortada yeni bir veri isteği vardır - ama nereden
başlayacağını bloğun altındaki tek satır söyler: son turun SQL'i değiştirilecek, baştan
yazılmayacak. Blok ayrıca işareti olmayan ama bir tabloyu adlandıran sorunun tek başına
okunabildiğini de yazar. İddialar sahte istemcinin kaydettiği ilk system mesajında okunur;
notun doğrulanması koşunun sonunda ``validate_note`` ile ölçülür.
"""

import copy

import pytest

from bilgin import config
from bilgin.agent import loop
from bilgin.agent.context import validate_note
from bilgin.agent.fake import FakeLLM, golden_replay
from bilgin.agent.llm import ChatResponse, ToolCall
from bilgin.agent.refine import refine_hint
from bilgin.engine.executor import LocalExecutor
from bilgin.schema_map import build, doc

GOLDEN = "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT WHERE IL = 'ANKARA' ORDER BY CARI_KOD"
PREVIOUS_SQL = "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT ORDER BY CARI_KOD"

# Soru -> R7-11in dört kategorisinden blokte beklenen ipucun ayırt edici parçası.
HINTS = {
    "Sadece Texas": "daraltıyor",
    "Bunu geçen yılla karşılaştır": "karşılaştırıyor",
    "Çeyreklik göster": "dönemsellikte",
    "İlk 10": "listenin başını",
}


def ask(name, **arguments):
    return ChatResponse(tool_calls=[ToolCall(id="", name=name, arguments=arguments)])


class Recorder:
    """Senaryoyu oynayan sahte istemci; her isteğin mesajlarını olduğu gibi saklar.

    Döngü mesaj listesini yerinde büyüttüğü için kayıt kopyadır: yoksa son istek hepsinin olurdu.
    """

    def __init__(self, script):
        self._client = FakeLLM(script)
        self.requests = []

    def chat(self, messages, tools=None):
        self.requests.append((copy.deepcopy(messages), copy.deepcopy(tools)))
        return self._client.chat(messages, tools)

    @property
    def first(self):
        return self.requests[0]


def turn(n, rows=8, row_count=40):
    """Konuşma deposundan çıkmış gibi bir history turn (Contracts "history turn")."""
    return {
        "n": n,
        "question": f"{n}. soru",
        "choice": None,
        "sql": PREVIOUS_SQL,
        "summary": {
            "columns": ["CARI_KOD", "CARI_ISIM"],
            "row_count": row_count,
            "rows": [[100 + i, f"Müşteri {i}"] for i in range(rows)],
            "facts": [],
            "chart_kind": None,
            "context": None,
            "clarification": None,
        },
    }


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    paths = tmp_path_factory.mktemp("refinements")
    db = paths / "test.db"
    build.build_db(config.SEED, db, paths / "test.sql")
    return LocalExecutor("sqlite", db, audit_path=paths / "audit.jsonl")


def run(question, llm, executor, schema, **kwargs):
    return loop.run_agent(question, llm, executor, schema, "test", **kwargs)


def system_of(request) -> str:
    """İlk isteğin tek system mesajı; geçmiş bloğu da oraya düşer."""
    systems = [message for message in request[0] if message["role"] == "system"]
    assert len(systems) == 1
    return systems[0]["content"]


@pytest.mark.parametrize("question,expect", sorted(HINTS.items()))
def test_a_refinement_shows_its_hint_under_the_sql_it_rewrites(question, expect, executor, schema):
    client = Recorder(golden_replay(GOLDEN))

    run(question, client, executor, schema, history=[turn(1)])

    text = system_of(client.first)
    assert f"Tur 1 SQL: {PREVIOUS_SQL}" in text
    assert refine_hint(question) in text
    assert expect in text


def test_a_question_that_names_a_table_is_read_on_its_own(executor, schema):
    client = Recorder(golden_replay(GOLDEN))

    run("Stok kartlarında toplam ürün sayısı ne kadar", client, executor, schema, history=[turn(1)])

    text = system_of(client.first)
    assert "soru tek başına da okunabilir" in text
    assert "bağlanan" not in text


def test_a_note_that_refines_the_last_turn_of_the_conversation_validates(executor, schema):
    note = {"uses_turns": [2], "entities": [{"column": "CARI_KOD", "value": "101"}], "refines_sql_of": 2}
    turns = [turn(1), turn(2)]
    client = Recorder([ask("submit_sql", sql=GOLDEN, context=note)])

    result = run("Sadece Ankara", client, executor, schema, history=turns)

    assert result.status == "submitted"
    assert validate_note(result.context_note, turns) == (note, None)
