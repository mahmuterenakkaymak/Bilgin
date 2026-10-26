"""T302: sahte istemci zincir turunu önceki sorularından tanır (PLAN R7-13).

Zincirin ikinci turu kendi sorusuyla değil, kendinden önce hangi soruların sorulduyla ayırt
edilir: ``for_golden`` bloğun ``Tur n sorusu:`` satırlarını okur ve eşleşen turun golden SQL'ini
``uses_turns``iyle birlikte gönderir. Ölçüm gerçek ``ask_payload``, gerçek konuşma deposu ve
kurulmuş sentetik ERP dünyası üzerinden yapılır - yani zincir, sonradan ``eval --followups``ın
koşacağı kapıdan koşar; ``make_client("fake")`` kümenin zincirlerini de istemciye geçirir.
"""

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.agent.context import context_block
from nl2sql.app.ask import ask_payload
from nl2sql.app.conversations import ConversationStore
from nl2sql.app.session import open_session
from nl2sql.datasets import load_dataset
from nl2sql.schema_map import build

DATASET = load_dataset("synthetic_erp")
CHAINS = {chain["id"]: chain for chain in DATASET.followups()}
IDS = ["F01", "F02", "F03"]

# Beklenen bağlam: None = not boş kaldı, yani tur ya tek başına durdu ya da notu kod kurmadı.
USES = {"F01": [None, [1], [2]], "F02": [None, [1], [2]], "F03": [None, None, [1]]}

# Aynı sorunun iki zincirde neye dönüştüğü: birinci zincir carileri, ikincisi ürünleri sayar.
SAME = "Kaç tane?"
TWIN_CHAINS = [
    {
        "id": "X1",
        "tags": [],
        "turns": [
            {"question": "Carileri listeler misin?", "sql": "SELECT TOP 3 CARI_KOD FROM TBLCASABIT ORDER BY CARI_KOD",
             "uses_turns": [], "tags": []},
            {"question": SAME, "sql": "SELECT COUNT(*) AS SAYI FROM TBLCASABIT", "uses_turns": [1], "tags": []},
        ],
    },
    {
        "id": "X2",
        "tags": [],
        "turns": [
            {"question": "Ürünleri listeler misin?", "sql": "SELECT TOP 3 STOK_KODU FROM TBLSTSABIT ORDER BY STOK_KODU",
             "uses_turns": [], "tags": []},
            {"question": SAME, "sql": "SELECT COUNT(*) AS SAYI FROM TBLSTSABIT", "uses_turns": [1], "tags": []},
        ],
    },
]

REFINED_CHAIN = [
    {
        "id": "R1",
        "tags": [],
        "turns": [
            {"question": "Eylül cirosu ne kadar?", "sql": "SELECT 1 AS CIRO", "uses_turns": [], "tags": []},
            {"question": "Sadece Ankara", "sql": "SELECT 2 AS CIRO", "uses_turns": [1], "tags": ["refine"]},
        ],
    }
]


def run_chain(session, store, chain):
    """Zinciri konuşma turu tur koşar: turların payload'ları sırayla."""
    payloads, conversation_id = [], None
    for turn in chain["turns"]:
        payload = ask_payload(session, turn["question"], mode="full", conversations=store,
                              conversation_id=conversation_id)
        payloads.append(payload)
        conversation_id = payload["conversation_id"]
    return payloads


@pytest.fixture(scope="module")
def erp_db(tmp_path_factory):
    folder = tmp_path_factory.mktemp("fake-followups")
    path = folder / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture
def session(erp_db, tmp_path):
    """Kümenin kendi sahte istemcisi: ``make_client("fake")`` zincirleri de geçirmeli (R7-13)."""
    return open_session(
        "synthetic_erp", llm="fake", db_path=erp_db,
        audit_path=tmp_path / "audit.jsonl", ask_log=tmp_path / "asks.jsonl",
    )


@pytest.fixture
def twin_session(erp_db, tmp_path):
    """Aynı soruyu iki zincirde taşıyan uydurma küme: ayrımı önceki sorular yapar."""

    def client(mode):
        return fake.for_golden(
            DATASET.golden(), DATASET.fake_fallback_sql, mode=mode,
            ambiguous=DATASET.ambiguous(), followups=TWIN_CHAINS,
        )

    return open_session(
        "synthetic_erp", llm="fake", db_path=erp_db, client_factory=client,
        audit_path=tmp_path / "twin-audit.jsonl", ask_log=tmp_path / "twin-asks.jsonl",
    )


@pytest.fixture
def store(tmp_path):
    return ConversationStore(tmp_path / "app.db")


# ------------------------------------------------------------------ the chains on the real door


@pytest.mark.parametrize("chain_id", IDS)
def test_every_chain_turn_is_answered_with_its_golden_query(session, store, chain_id):
    turns = CHAINS[chain_id]["turns"]
    payloads = run_chain(session, store, CHAINS[chain_id])

    assert [payload["status"] for payload in payloads] == ["answered"] * len(turns)
    assert [payload["sql"] for payload in payloads] == [turn["sql"] for turn in turns]
    assert [payload["turn"] for payload in payloads] == list(range(1, len(turns) + 1))
    assert [payload["context"]["uses_turns"] if payload["context"] else None for payload in payloads] == (
        USES[chain_id]
    )


def test_f03_stands_alone_in_the_middle_and_returns_to_its_customers(session, store):
    payloads = run_chain(session, store, CHAINS["F03"])

    assert payloads[1]["context"] is None, "ortadaki tur önceki tura bakmıyor: boş not"
    assert payloads[2]["context"]["uses_turns"] == [1]
    assert payloads[2]["context"]["refines_sql_of"] is None
    assert payloads[2]["context"]["line"].startswith("Önceki cevaptan: ")


def test_a_chain_question_still_answers_outside_a_conversation(session):
    first = CHAINS["F01"]["turns"][0]
    payload = ask_payload(session, first["question"], mode="full")

    assert payload["status"] == "answered" and payload["sql"] == first["sql"]
    assert "context" not in payload, "konuşmasız koşum Run 6'nın payload'ıdır"


def test_the_same_question_in_two_chains_resolves_by_its_previous_questions(twin_session, store):
    counts = [run_chain(twin_session, store, chain)[1]["sql"] for chain in TWIN_CHAINS]

    assert counts == [chain["turns"][1]["sql"] for chain in TWIN_CHAINS]


# ------------------------------------------------------------------ the note the fake submits


def test_a_turn_tagged_refine_names_the_query_it_rewrites():
    block = context_block(
        [{"n": 1, "question": "Eylül cirosu ne kadar?", "sql": "SELECT 1 AS CIRO",
          "summary": {"columns": ["CIRO"], "row_count": 1, "rows": [[1.0]], "facts": []}}],
        None,
    )
    messages = [{"role": "system", "content": block}, {"role": "user", "content": "Sadece Ankara"}]
    for n in range(2):
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{n}"}]})
        messages.append({"role": "tool", "tool_call_id": f"c{n}", "content": "1 satır"})

    call = fake.for_golden([], followups=REFINED_CHAIN).chat(messages).tool_calls[0]

    assert call.name == "submit_sql"
    assert call.arguments == {
        "sql": "SELECT 2 AS CIRO",
        "context": {"uses_turns": [1], "entities": [], "refines_sql_of": 1},
    }


def test_a_chain_turn_without_a_note_of_its_own_submits_an_empty_one():
    messages = [{"role": "system", "content": "şema"}, {"role": "user", "content": "Eylül cirosu ne kadar?"}]
    for n in range(2):
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{n}"}]})
        messages.append({"role": "tool", "tool_call_id": f"c{n}", "content": "1 satır"})

    arguments = fake.for_golden([], followups=REFINED_CHAIN).chat(messages).tool_calls[0].arguments

    assert arguments["context"] == {"uses_turns": [], "entities": [], "refines_sql_of": None}
