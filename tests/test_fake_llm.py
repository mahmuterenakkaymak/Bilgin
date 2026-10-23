"""Sahte istemci: senaryonun geri çalınması, tur sırası ve uydurma ama tutarlı maliyet.

Model burada hiç işin içinde değil; asıl mesele sahte istemcinin döngü için gerçek bir endpoint
gibi davranması. Bunun için üç şey sınanıyor: (1) tur sırası sohbetin kendisinden gelmeli, gizli
sayaçtan değil - aynı instance on soruyu da yanıtlasa şaşmamalı; (2) senaryodaki sorgular policy
ve şema karşısında da TASKS.md'de varsayıldığı sonuçları vermeli (biri reddedilir, biri red
edilmez ama veritabanı patlar); (3) token/gecikme raporlanabilir sayılar olmalı, yoksa eval
raporundaki bağlam sütunları boş kalır.
"""

import json

import pytest

from nl2sql import config
from nl2sql.agent.fake import (
    BROKEN_SQL,
    FALLBACK_SQL,
    FORBIDDEN_SQL,
    FakeLLM,
    failing_sql_forever,
    for_golden,
    forbidden_then_recover,
    golden_replay,
    never_submit,
    tool_spam,
    unreachable,
    wrong_sql,
)
from nl2sql.agent.llm import ChatResponse, LLMError
from nl2sql.policy import policy
from nl2sql.schema_map import doc

GOLDEN = "SELECT CARI_KOD FROM TBLCASABIT"
WRONG = "SELECT CARI_KOD FROM TBLCASABIT WHERE IL = 'ANKARA'"
TOOLS = [{"type": "function", "function": {"name": "run_sql"}}]


def golden_lines(path=config.GOLDEN_PATH):
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


SCHEMA = doc.load_schema(config.SCHEMA_PATH)
ALLOWED = doc.allowlist(SCHEMA)
GOLDEN_LINES = golden_lines()


def messages_for(turn, question=GOLDEN_LINES[0]["question"]):
    """Döngünün n. çağrısı: sistem + soru + n tane (asistan mesajı, araç sonucu) çifti."""
    messages = [{"role": "system", "content": "şema ve kurallar"}, {"role": "user", "content": question}]
    for n in range(turn):
        messages.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"c{n}"}]})
        messages.append({"role": "tool", "tool_call_id": f"c{n}", "content": "4 satır"})
    return messages


def calls(response):
    return [(call.name, call.arguments) for call in response.tool_calls]


# ----------------------------------------------------------------- replay

def test_golden_replay_reads_the_schema_then_runs_and_submits_the_golden_query():
    llm = FakeLLM(golden_replay(GOLDEN))
    assert [calls(llm.chat(messages_for(n))) for n in range(3)] == [
        [("get_schema", {})],
        [("run_sql", {"sql": GOLDEN})],
        [("submit_sql", {"sql": GOLDEN})],
    ]


def test_a_tool_turn_says_nothing():
    assert FakeLLM(golden_replay(GOLDEN)).chat(messages_for(0)).content == ""


def test_the_last_turn_repeats_so_an_open_ended_script_never_ends():
    llm = FakeLLM(golden_replay(GOLDEN))
    assert calls(llm.chat(messages_for(9))) == [("submit_sql", {"sql": GOLDEN})]


def test_turn_order_comes_from_the_transcript_not_from_a_hidden_counter():
    answer = FakeLLM(golden_replay(GOLDEN)).chat(messages_for(2))
    llm = FakeLLM(golden_replay(GOLDEN))
    assert llm.chat(messages_for(2)) == answer, "aynı sohbete aynı yanıt verilmeli"
    again = FakeLLM(golden_replay(GOLDEN)).chat(messages_for(0))
    assert llm.chat(messages_for(0)) == again


def test_call_ids_are_unique_within_a_conversation():
    ids = [
        call.id
        for turn in range(3)
        for call in FakeLLM(golden_replay(GOLDEN)).chat(messages_for(turn)).tool_calls
    ]
    assert len(ids) == 3 and len(set(ids)) == 3


def test_the_chat_signature_matches_the_real_client():
    response = FakeLLM(golden_replay(GOLDEN)).chat(messages_for(0), TOOLS)
    assert calls(response) == [("get_schema", {})]


# ----------------------------------------------------------------- usage

def test_fake_usage_is_reported_and_grows_with_the_conversation():
    llm = FakeLLM(golden_replay(GOLDEN))
    early, late = llm.chat(messages_for(0)), llm.chat(messages_for(3))
    assert (early.prompt_tokens, early.completion_tokens) > (0, 0)
    assert late.prompt_tokens > early.prompt_tokens, "bağlam büyüdükçe prompt token'ı da büyür"
    assert late.completion_tokens > 0
    assert late.latency_ms > 0


def test_a_builder_can_pin_its_own_numbers():
    pinned = ChatResponse(content="sabit", prompt_tokens=99, completion_tokens=3, latency_ms=1.0)
    response = FakeLLM([pinned]).chat(messages_for(0))
    assert (response.prompt_tokens, response.completion_tokens, response.latency_ms) == (99, 3, 1.0)


# ----------------------------------------------------------------- scripts

def test_a_wrong_answer_is_run_and_then_submitted():
    llm = FakeLLM(wrong_sql(WRONG))
    assert calls(llm.chat(messages_for(1))) == [("run_sql", {"sql": WRONG})]
    assert calls(llm.chat(messages_for(2))) == [("submit_sql", {"sql": WRONG})]


def test_a_rejected_query_is_followed_by_the_golden_one():
    llm = FakeLLM(forbidden_then_recover(GOLDEN))
    assert [calls(llm.chat(messages_for(n))) for n in range(4)] == [
        [("get_schema", {})],
        [("run_sql", {"sql": FORBIDDEN_SQL})],
        [("run_sql", {"sql": GOLDEN})],
        [("submit_sql", {"sql": GOLDEN})],
    ]


def test_the_failing_query_never_stops_failing():
    llm = FakeLLM(failing_sql_forever())
    failing = [("run_sql", {"sql": BROKEN_SQL})]
    assert all(calls(llm.chat(messages_for(n))) == failing for n in (1, 5, 20))


def test_tool_spam_only_ever_asks_for_the_schema():
    llm = FakeLLM(tool_spam())
    assert all(calls(llm.chat(messages_for(n))) == [("get_schema", {})] for n in (0, 7, 30))


def test_never_submit_talks_without_asking_for_a_tool():
    llm = FakeLLM(never_submit())
    for turn in (0, 4):
        response = llm.chat(messages_for(turn))
        assert response.tool_calls == []
        assert response.content, "boş cevap izleyiciye hiçbir şey söylemez"


def test_unreachable_raises_the_error_the_real_endpoint_would():
    with pytest.raises(LLMError) as caught:
        FakeLLM(unreachable()).chat(messages_for(0))
    message = str(caught.value)
    assert "127.0.0.1:" in message and "NL2SQL_LLM_BASE_URL" in message


# ------------------------------------------------------- the scripts against the guardrail

def test_the_forbidden_query_is_rejected_and_the_broken_one_is_not():
    """Senaryonun doğru sonucu üretmesi policy'nin de aynı görüşte olmasını gerektirir."""
    assert not policy.check(FORBIDDEN_SQL, ALLOWED).ok
    assert policy.check(BROKEN_SQL, ALLOWED).ok
    assert policy.check(FALLBACK_SQL, ALLOWED).ok


def test_the_broken_query_names_a_column_the_schema_does_not_have():
    columns = {column["name"] for table in SCHEMA["tables"] for column in table["columns"]}
    assert "OLMAKOLAN_KOLON" not in columns


def test_the_stock_query_only_uses_columns_the_schema_has():
    stock = {table["name"]: {c["name"] for c in table["columns"]} for table in SCHEMA["tables"]}
    assert {"STOK_KODU", "STOK_ADI"} <= stock["TBLSTSABIT"]


# ----------------------------------------------------------------- for_golden

def test_every_golden_question_replays_its_own_golden_query():
    llm = for_golden(GOLDEN_LINES)
    for line in GOLDEN_LINES:
        response = llm.chat(messages_for(2, question=line["question"]))
        assert calls(response) == [("submit_sql", {"sql": line["sql"]})], line["id"]


def test_the_golden_query_is_replayed_from_the_first_turn_on():
    line = GOLDEN_LINES[0]
    llm = for_golden(GOLDEN_LINES)
    asked = [calls(llm.chat(messages_for(n, question=line["question"]))) for n in range(3)]
    assert asked == [
        [("get_schema", {})],
        [("run_sql", {"sql": line["sql"]})],
        [("submit_sql", {"sql": line["sql"]})],
    ]


def test_question_text_is_matched_after_stripping():
    line = GOLDEN_LINES[1]
    response = for_golden(GOLDEN_LINES).chat(messages_for(1, question=f"  {line['question']}  "))
    assert calls(response) == [("run_sql", {"sql": line["sql"]})]


def test_an_unknown_question_gets_the_stock_query():
    response = for_golden(GOLDEN_LINES).chat(messages_for(2, question="Depolar hakkında ne biliyorsun?"))
    assert calls(response) == [("submit_sql", {"sql": FALLBACK_SQL})]


def test_a_golden_line_without_a_question_or_a_query_is_never_matched():
    usable = {"question": "Soru", "sql": GOLDEN}
    broken = [{"question": "  ", "sql": GOLDEN}, {"sql": GOLDEN}, {"question": "Soru", "sql": "  "}]
    llm = for_golden([*broken, usable])
    assert calls(llm.chat(messages_for(0, question="Soru"))) == [("get_schema", {})]
    assert calls(llm.chat(messages_for(2, question="Soru"))) == [("submit_sql", {"sql": GOLDEN})]


def test_the_question_survives_a_tool_result_written_as_a_user_message():
    line = GOLDEN_LINES[0]
    messages = [
        {"role": "system", "content": "şema ve kurallar"},
        {"role": "user", "content": line["question"]},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
        {"role": "user", "content": "Böyle bir sütun yok."},
    ]
    assert calls(for_golden(GOLDEN_LINES).chat(messages)) == [("run_sql", {"sql": line["sql"]})]
