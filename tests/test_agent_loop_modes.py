# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Döngü mod farkındadır: sistem istemi, araç listesi ve sınır `get_mode`'dan gelir (T61).

Model yine yok; rag yolunu `rag_replay` oynatıyor. Altındaki her şey gerçek: build_db ile kurulmuş
SQLite üzerinde LocalExecutor, FakeEmbedder ile kurulmuş arama, şemadan örülmüş join graph. Böylece
sınanan uydurma bir cevap metni değil, gerçek araç cevaplarının gerçek bir sohbete nasıl dizildiği:
adımların sırası, kırpılan bir cevabın sohbete kırpılmış girmesi, full_rules'un kuralları sistem
mesajına yazması ve rag'in kendi araç sınırında (8 değil 12) durması.
"""

import pytest

from nl2sql import config
from nl2sql.agent import loop, modes
from nl2sql.agent.fake import FakeLLM, golden_replay, rag_replay, tool_spam
from nl2sql.agent.tools import cap_text
from nl2sql.engine.executor import LocalExecutor
from nl2sql.eval.runner import load_golden
from nl2sql.graph.graph import build_graph
from nl2sql.graph.profile import load_profile
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import build_search
from nl2sql.schema_map import build, doc
from nl2sql.schema_map.rules import load_rules

QUESTION = "Ankara'daki alıcı carilerin kodu ve ünvanı nedir?"

# Detayı TOOL_RESULT_MAX_CHARS'ı aşan tablo listesi; kırpmanın devreye girmesi bununla sınanıyor.
WIDE = ["TBLCASABIT", "TBLFATUIRS", "TBLSTHAR", "TBLSTHAR_ARSIV"]

GOLDEN = {line["id"]: line for line in load_golden()}


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def rules():
    return load_rules()


@pytest.fixture(scope="module")
def search(schema, rules):
    return build_search(schema, rules, FakeEmbedder())


@pytest.fixture(scope="module")
def graph(schema):
    return build_graph(schema, load_profile())


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    paths = tmp_path_factory.mktemp("modes")
    db = paths / "test.db"
    build.build_db(config.SEED, db, paths / "test.sql")
    return LocalExecutor("sqlite", db, audit_path=paths / "audit.jsonl")


def world(executor, schema, rules, search, graph, mode):
    return modes.ToolContext(
        executor=executor, schema=schema, rules=rules, search=search, graph=graph, mode=mode
    )


def run(question, llm, executor, schema, rules, search, graph, mode="rag"):
    ctx = world(executor, schema, rules, search, graph, mode)
    return loop.run_agent(question, llm, executor, schema, "test", mode=mode, context=ctx)


def record(turns, seen):
    """Senaryoyu oynatırken modele giren sohbeti de saklar; sistem mesajı orada, AgentRun'da değil."""

    def script(messages):
        seen.append(messages)
        return turns

    return script


def tools_of(result):
    return [step.tool for step in result.steps]


# ------------------------------------------------------------------ rag yolu

def test_the_rag_path_walks_the_tools_in_order_and_submits(executor, schema, rules, search, graph):
    line = GOLDEN["Q04"]
    result = run(line["question"], FakeLLM(rag_replay(line)), executor, schema, rules, search, graph)
    assert result.status == "submitted"
    assert result.submitted_sql == line["sql"]
    assert result.mode == "rag"
    assert tools_of(result) == [
        "search_schema",
        "get_table_details",
        "find_join_path",
        "run_sql",
        "submit_sql",
    ]
    assert all(step.ok for step in result.steps)


def test_a_single_table_question_never_asks_for_a_join_path(executor, schema, rules, search, graph):
    line = GOLDEN["Q03"]
    result = run(line["question"], FakeLLM(rag_replay(line)), executor, schema, rules, search, graph)
    assert result.status == "submitted"
    assert tools_of(result) == ["search_schema", "get_table_details", "run_sql", "submit_sql"]


# ------------------------------------------------------------------ kırpma

def test_a_capped_tool_answer_reaches_the_transcript_capped(executor, schema, rules, search, graph):
    """Araç cevabı modele gitmeden kırpılıyor; sohbetin araç mesajı da o kırpılmış hali taşımalı."""
    line = {**GOLDEN["Q01"], "requires_tables": WIDE}
    detail = cap_text(doc.table_detail(schema, WIDE), config.TOOL_RESULT_MAX_CHARS)
    assert "kırpıldı" in detail, "senaryonun gerçekten uzun bir cevap üretmesi gerekiyor"
    seen = []
    result = run(
        line["question"],
        FakeLLM(record(rag_replay(line), seen)),
        executor,
        schema,
        rules,
        search,
        graph,
    )
    assert result.status == "submitted"
    assert detail in [message["content"] for message in seen[-1] if message["role"] == "tool"]
    assert result.steps[1].summary == detail


# ------------------------------------------------------------------ sistem istemi

def test_full_rules_writes_every_rule_into_the_system_message(executor, schema, rules, search, graph):
    seen = []
    result = run(
        QUESTION,
        FakeLLM(record(golden_replay(GOLDEN["Q01"]["sql"]), seen)),
        executor,
        schema,
        rules,
        search,
        graph,
        mode="full_rules",
    )
    assert result.status == "submitted"
    assert result.mode == "full_rules"
    system = seen[0][0]
    assert system["role"] == "system"
    assert "İŞ KURALLARI" in system["content"]
    for rule in rules:
        assert rule["term"] in system["content"]


def test_the_run_one_call_form_is_full_mode_with_every_column(executor, schema):
    """Bağlam verilmeyen Run 1 çağrısı full moddur: şemanın tamamı istemde, araçlar üç tanedir."""
    seen = []
    result = loop.run_agent(
        QUESTION, FakeLLM(record(golden_replay(GOLDEN["Q01"]["sql"]), seen)), executor, schema, "test"
    )
    assert (result.status, result.mode) == ("submitted", "full")
    assert "STHAR_GCMIK" in seen[0][0]["content"]


def test_the_model_is_shown_the_tools_of_its_mode(executor, schema, rules, search, graph):
    line = GOLDEN["Q04"]
    client = _Recorder(rag_replay(line))
    run(line["question"], client, executor, schema, rules, search, graph)
    assert [tool["function"]["name"] for tool in client.tools] == [
        tool["function"]["name"] for tool in modes.get_mode("rag").tools
    ]


class _Recorder:
    """Sahte istemcinin sarılı hali: modele gösterilen araç listesini de saklar."""

    def __init__(self, turns):
        self._replay = FakeLLM(turns)
        self.tools = None

    def chat(self, messages, tools=None):
        self.tools = tools
        return self._replay.chat(messages, tools)


# ------------------------------------------------------------------ modun aracı sınırı

def test_rag_stops_at_its_own_tool_call_limit(executor, schema, rules, search, graph):
    limit = config.MAX_TOOL_CALLS_BY_MODE["rag"]
    assert limit > config.MAX_TOOL_CALLS, "sınır moddan gelmeli, genel sabitten değil"
    result = run(QUESTION, FakeLLM(tool_spam()), executor, schema, rules, search, graph)
    assert result.status == "no_submission"
    assert len(result.steps) == limit
    assert str(limit) in result.stop_reason
