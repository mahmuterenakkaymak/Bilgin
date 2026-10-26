"""T291: ``ask_payload`` bir konuşmanın turu (PLAN R7-7, Contracts "AskPayload (ext.)", "ask record (ext.)").

Dünya gerçek (``build_db`` ile kurulmuş sentetik ERP), model senaryolu sahte: her koşum sıradaki
senaryoyu oynar ve ilk isteğinin tek system mesajını saklar - yani "ikinci tur birinciyi gördü mü"
iddiası doğrudan okunur. İddialar aynı turun dört yüzünde birden: payload, soru günlüğünün satırı,
konuşmanın tur satırı ve denetim satırlarının başı.
"""

import json
import sqlite3

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.agent.llm import ChatResponse, ToolCall
from nl2sql.app.ask import ask_payload
from nl2sql.app.conversations import ConversationNotFound, ConversationStore
from nl2sql.app.session import open_session
from nl2sql.schema_map import build

STOCK_SQL = "SELECT TOP 5 STOK_KODU, STOK_ADI FROM TBLSTSABIT ORDER BY STOK_KODU"
REVERSED_SQL = "SELECT TOP 5 STOK_KODU, STOK_ADI FROM TBLSTSABIT ORDER BY STOK_KODU DESC"
Q1 = "Beş ürünü listeler misin?"
Q2 = "Bunların son halleri ne kadar?"

# Contracts "AskPayload" + "AskPayload (ext.)": depo üç anahtarı ekler, depoya koşmayan hiç eklemez.
PAYLOAD_KEYS = {
    "status", "question", "choice", "answer_text", "narration_source", "chart", "facts",
    "columns", "rows", "row_count", "truncated", "sql", "tables_used", "rules_used",
    "masked_columns", "warnings", "notes", "mode", "dataset", "model", "timings",
    "audit_id", "clarification", "error", "steps",
}
CONVERSATION_KEYS = {"conversation_id", "turn", "context"}


def submit(sql, context=None):
    arguments = {"sql": sql}
    if context is not None:
        arguments["context"] = context
    return ChatResponse(tool_calls=[ToolCall(id="", name="submit_sql", arguments=arguments)])


def note(turn, value, column="STOK_KODU"):
    """Modelin submit_sql'e yazdığı bağlam notu (Contracts "ContextNote")."""
    return {"uses_turns": [turn], "entities": [{"column": column, "value": value}], "refines_sql_of": turn}


class Scripted:
    """Koşum başına sıradaki senaryoyu oynatan sahte model; her koşumun ilk isteğini de kaydeder.

    Bir ``ask_payload`` ``client_factory``yi tam bir kez çağırdığı için sıra senaryoda ilerler;
    kayıt transkriptin ilk halinden alınır, böylece system mesajı geçmiş bloğu eklenmeden önceki
    haliyle değil eklendikten sonraki haliyle - yani modele giden haliyle - okunur.
    """

    def __init__(self, scripts):
        self._scripts = list(scripts)
        self._run = -1
        self.systems = []

    def client_factory(self, mode):
        self._run += 1
        return self

    def chat(self, messages, tools=None):
        if not any(message["role"] == "assistant" for message in messages):
            self.systems.append(_system(messages))
        script = self._scripts[min(self._run, len(self._scripts) - 1)]
        return fake.FakeLLM(script).chat(messages, tools)


def _system(messages) -> str:
    systems = [message["content"] for message in messages if message["role"] == "system"]
    assert len(systems) == 1, "geçmiş tek system mesajının sonuna eklenir"
    return systems[0]


def records(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    return tmp_path


@pytest.fixture(scope="module")
def erp_db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ask-conversation")
    path = tmp / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture(scope="module")
def first_code(erp_db):
    """İlk turun gerçekten göstereceği ürün kodu: ikinci turun notunun dayandığı değer."""
    with sqlite3.connect(erp_db) as conn:
        return conn.execute("SELECT STOK_KODU FROM TBLSTSABIT ORDER BY STOK_KODU LIMIT 1").fetchone()[0]


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


def two_turn_store_run(world, store, second_script):
    """İki turu tek konuşmada koşar: ``(birinci, ikinci, scripted)``."""
    session, scripted = world([fake.wrong_sql(STOCK_SQL), second_script])
    first = ask_payload(session, Q1, mode="full", conversations=store)
    second = ask_payload(
        session, Q2, mode="full", conversations=store, conversation_id=first["conversation_id"]
    )
    return first, second, scripted


# ------------------------------------------------------------------ aynı konuşmanın turları


def test_two_turns_share_one_conversation_and_their_numbers(project, store, world, first_code):
    first, second, _ = two_turn_store_run(world, store, [submit(REVERSED_SQL, note(1, first_code))])

    assert first["status"] == second["status"] == "answered"
    assert second["conversation_id"] == first["conversation_id"]
    assert (first["turn"], second["turn"]) == (1, 2)
    assert sorted(second) == sorted(PAYLOAD_KEYS | CONVERSATION_KEYS)
    assert first["context"] is None, "ilk turun dayandığı tur yok"

    thread = store.get(first["conversation_id"])
    assert thread["conversation"]["title"] == Q1
    assert [turn["n"] for turn in thread["turns"]] == [1, 2]
    assert [turn["status"] for turn in thread["turns"]] == ["answered", "answered"]
    assert thread["turns"][0]["question"] == Q1 and thread["turns"][0]["sql"] == STOCK_SQL
    assert len(thread["turns"][0]["summary"]["rows"]) <= config.CONV_KEEP_ROWS
    # Turun denetim satırları aynı kimlikle döner: dört yüz de aynı turu gösterir.
    assert thread["turns"][1]["audit_id"] == second["audit_id"]
    assert {line["source"] for line in records(project / "audit.jsonl")} == {
        f"web:{payload['audit_id']}" for payload in (first, second)
    }

    lines = records(project / "asks.jsonl")
    assert [line["turn"] for line in lines] == [1, 2]
    assert {line["conversation_id"] for line in lines} == {first["conversation_id"]}


# ------------------------------------------------------------------ geçmiş ve kanıt satırı


def test_the_second_turn_runs_with_the_first_as_history(project, store, world, first_code):
    _, second, scripted = two_turn_store_run(world, store, [submit(REVERSED_SQL, note(1, first_code))])

    assert "## Önceki turlar" not in scripted.systems[0]
    assert f"Tur 1 sorusu: {Q1}" in scripted.systems[1]
    assert f"Tur 1 SQL: {STOCK_SQL}" in scripted.systems[1]

    context = second["context"]
    assert set(context) == {"uses_turns", "entities", "refines_sql_of", "line"}
    assert {key: context[key] for key in ("uses_turns", "entities", "refines_sql_of")} == {
        "uses_turns": [1],
        "entities": [{"column": "STOK_KODU", "value": first_code}],
        "refines_sql_of": 1,
    }
    assert context["line"].startswith("Önceki cevaptan: ") and first_code in context["line"]
    assert "STOK_KODU" not in context["line"], "teknik kolon adı kullanıcıya görünmez"
    # Kanıt satırı turla birlikte durur: konuşma yeniden açıldığında yeniden üretilmez.
    stored = store.get(second["conversation_id"])["turns"][1]["summary"]["context"]
    assert stored["line"] == context["line"] and stored["uses_turns"] == [1]


# ------------------------------------------------------------------ düşen not


def test_an_invalid_note_drops_but_the_answer_stands(project, store, world):
    first, second, _ = two_turn_store_run(world, store, [submit(REVERSED_SQL, note(1, "STK9999"))])

    assert second["status"] == "answered" and second["sql"] == REVERSED_SQL and second["rows"]
    assert second["context"] is None
    lines = records(project / "asks.jsonl")
    assert "context_dropped" not in lines[0]
    assert lines[1]["turn"] == 2 and lines[1]["context_dropped"]
    assert "STK9999" in lines[1]["context_dropped"]
    assert store.get(first["conversation_id"])["turns"][1]["summary"]["context"] is None


# ------------------------------------------------------------------ netleştirme ve seçimi


def test_a_choice_completes_the_pending_clarification_turn(project, store, world):
    session, _ = world([fake.over_clarify(), fake.wrong_sql(STOCK_SQL)])

    asked = ask_payload(session, Q1, mode="full", conversations=store)
    chosen = ask_payload(
        session, Q1, mode="full", choice=fake.OVER_CLARIFY_OPTIONS[0],
        conversations=store, conversation_id=asked["conversation_id"],
    )

    assert asked["status"] == "needs_clarification" and asked["turn"] == 1
    assert chosen["status"] == "answered" and chosen["turn"] == 1
    assert chosen["conversation_id"] == asked["conversation_id"]
    assert chosen["choice"] == fake.OVER_CLARIFY_OPTIONS[0]

    thread = store.get(asked["conversation_id"])
    assert len(thread["turns"]) == 1, "seçim bekleyen turu tamamlar, üstüne tur açmaz"
    assert thread["turns"][0]["status"] == "answered"
    assert thread["turns"][0]["choice"] == fake.OVER_CLARIFY_OPTIONS[0]
    assert thread["turns"][0]["summary"]["clarification"] is None
    assert [line["turn"] for line in records(project / "asks.jsonl")] == [1, 1]


# ------------------------------------------------------------------ yabancı kimlik


def test_a_foreign_or_missing_conversation_id_raises(project, store, world):
    session, _ = world([fake.wrong_sql(STOCK_SQL)])
    theirs = store.create(username="eren", dataset=None, title="Onun konuşması")
    mine = ask_payload(session, Q1, mode="full", conversations=store)["conversation_id"]

    for conversation_id, username in ((theirs, None), ("0" * 32, None), (mine, "ayse")):
        with pytest.raises(ConversationNotFound) as raised:
            ask_payload(session, Q2, mode="full", conversations=store,
                        conversation_id=conversation_id, username=username)
        assert str(raised.value) == "Konuşma bulunamadı."

    assert store.get(theirs)["turns"] == []
    assert store.get(mine)["conversation"]["username"] is None
    assert len(records(project / "asks.jsonl")) == 1, "bulunamayan konuşma soru sayılmaz"


# ------------------------------------------------------------------ başarısız tur


def test_a_failed_answer_is_stored_as_a_failed_turn(project, store, world):
    session, _ = world([fake.never_submit()])

    payload = ask_payload(session, Q1, mode="full", conversations=store)

    assert payload["status"] == "failed" and payload["turn"] == 1
    turn = store.get(payload["conversation_id"])["turns"][0]
    assert turn["status"] == "failed" and turn["sql"] is None
    assert turn["answer_text"] == payload["answer_text"]
    assert turn["summary"]["rows"] == [] and turn["summary"]["context"] is None
    assert records(project / "asks.jsonl")[0]["turn"] == 1
