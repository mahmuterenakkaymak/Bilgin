"""T289: geçmişin ajan döngüsüne girişi (PLAN R7-4, R7-5).

Geçmiş, tek system mesajının sonuna eklenen bloktur: kullanıcının çıplak sorusu değişmez, görünen
tur sayısı ``CONV_TURNS``le, satır sayısı ``CONV_KEEP_ROWS``le sınırlıdır ve o koşta submit_sql bir
de ``context`` alanı gösterir. Geçmiş yoksa (None ya da []) modele giden ilk istek Run 6 ile aynıdır.
İddialar sahte istemcinin kaydettiği ilk istekte okunur: görünen turlar, satır sınırı, gönderilen
şema, koşuya yazılan not ve bütçe daraldığında neyin düştüğü.
"""

import copy

import pytest

from nl2sql import config
from nl2sql.agent import loop
from nl2sql.agent.budget import estimate_prompt
from nl2sql.agent.fake import FakeLLM, golden_replay
from nl2sql.agent.llm import ChatResponse, ToolCall
from nl2sql.engine.executor import LocalExecutor
from nl2sql.schema_map import build, doc

GOLDEN = "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT WHERE IL = 'ANKARA' ORDER BY CARI_KOD"
QUESTION = "Peki bu müşterinin toplamı ne kadar?"
NOTE = {"uses_turns": [2], "entities": [{"column": "CARI_KOD", "value": "101"}], "refines_sql_of": 2}


def ask(name, **arguments):
    return ChatResponse(tool_calls=[ToolCall(id="", name=name, arguments=arguments)])


class Recorder:
    """Senaryoyu oynayan sahte istemci; her isteğin mesajlarını ve araç şemalarını olduğu gibi saklar.

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
        "sql": f"SELECT TOP {row_count} * FROM TBLCASABIT WHERE N = {n}",
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
    paths = tmp_path_factory.mktemp("history")
    db = paths / "test.db"
    build.build_db(config.SEED, db, paths / "test.sql")
    return LocalExecutor("sqlite", db, audit_path=paths / "audit.jsonl")


def run(llm, executor, schema, **kwargs):
    return loop.run_agent(QUESTION, llm, executor, schema, "test", **kwargs)


def system_of(request) -> str:
    """İlk isteğin tek system mesajı; geçmiş bloğu da oraya düşer."""
    systems = [message for message in request[0] if message["role"] == "system"]
    assert len(systems) == 1
    return systems[0]["content"]


# ------------------------------------------------------------------ bloğun kendisi

def test_the_model_sees_the_last_conv_turns_and_their_kept_rows(executor, schema):
    client = Recorder(golden_replay(GOLDEN))

    result = run(client, executor, schema, history=[turn(n) for n in (1, 2, 3, 4)])

    text = system_of(client.first)
    assert "## Önceki turlar" in text
    for n in range(4 - config.CONV_TURNS + 1, 5):
        assert f"Tur {n} sorusu: {n}. soru" in text
        assert f"Tur {n} SQL: SELECT TOP 40 * FROM TBLCASABIT WHERE N = {n}" in text
        assert f"Tur {n} satırlar ({config.CONV_KEEP_ROWS} / 40):" in text
    assert "Tur 1 sorusu" not in text
    assert text.count("100 | Müşteri 0") == config.CONV_TURNS
    assert "105 | Müşteri 5" not in text  # 6. satır bloğa hiç girmez
    assert "önceki turlardaki bir sayıyı cevaba kopyalama" in text  # bloğun kural metni de eklenir
    assert client.first[0][1] == {"role": "user", "content": QUESTION}
    assert result.status == "submitted"
    assert (result.history_turns, result.history_rows_dropped) == (config.CONV_TURNS, 0)


# ------------------------------------------------------------------ bağlam notu (R7-5)

def test_submit_sql_offers_the_context_field_and_the_run_keeps_the_note(executor, schema):
    client = Recorder([ask("submit_sql", sql=GOLDEN, context=NOTE)])

    result = run(client, executor, schema, history=[turn(1), turn(2)])

    assert result.status == "submitted"
    assert result.submitted_sql == GOLDEN
    assert result.context_note == NOTE
    shown = {tool["function"]["name"]: tool for tool in client.first[1]}
    assert "context" in shown["submit_sql"]["function"]["parameters"]["properties"]
    assert shown["submit_sql"]["function"]["parameters"]["required"] == ["sql"]


# ------------------------------------------------------------------ Run 6 bayt aynı kalır

def test_no_history_and_an_empty_history_send_the_same_request(executor, schema):
    plain, empty = Recorder(golden_replay(GOLDEN)), Recorder(golden_replay(GOLDEN))

    run(plain, executor, schema)
    run(empty, executor, schema, history=[])

    assert empty.first == plain.first
    assert "## Önceki turlar" not in system_of(plain.first)
    for tool in plain.first[1]:
        assert "context" not in tool["function"]["parameters"]["properties"]


# ------------------------------------------------------------------ bütçe

def test_a_budget_below_the_bare_prompt_stops_as_context_overflow(executor, schema):
    client = Recorder(golden_replay(GOLDEN))

    result = run(client, executor, schema, history=[turn(n) for n in (1, 2, 3)], budget=1)

    assert result.status == "context_overflow"
    assert result.overflows == 1
    assert result.history_turns == 0
    assert client.requests == []  # modele hiç gitmedi


def test_a_budget_that_only_covers_the_question_drops_the_history_but_still_answers(executor, schema):
    # tek araç çağrılık senaryo: bütçe çıplak istem kadar, yani araç cevabının sığacağı yer yok.
    plain = Recorder([ask("submit_sql", sql=GOLDEN)])
    run(plain, executor, schema)
    budget = estimate_prompt(plain.first[0], plain.first[1])

    client = Recorder([ask("submit_sql", sql=GOLDEN)])
    result = run(client, executor, schema, history=[turn(n) for n in (1, 2, 3, 4)], budget=budget)

    assert result.status == "submitted"
    assert result.history_turns == 0
    assert "## Önceki turlar" not in system_of(client.first)
