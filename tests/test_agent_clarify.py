# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""ask_clarification: aracın kendisi, döngüdeki yeri ve istemdeki kuralı (PLAN R5-10).

Model yok; senaryoyu FakeLLM oynatıyor, veritabanı gerçek (build_db ile kurulmuş SQLite üzerinde
LocalExecutor). clarify varsayılan kapalı olduğu için iki taraf da sınanıyor: açıkken geçerli bir
sorunun çalışmayı needs_clarification ile durdurması, geçersiz bir çağrının yalnız modele söylenen
bir red olup çalışmayı sürdürmesi; kapalıyken ise hiçbir şeyin değişmemesi - ne modele giden araç
listesi, ne sistem istemi, ne de dispatch'in kabul ettiği adlar.
"""

import pytest

from bilgin import config
from bilgin.agent import loop, modes, prompt, tools
from bilgin.agent.fake import FakeLLM, golden_replay
from bilgin.agent.llm import ChatResponse, ToolCall
from bilgin.agent.tools import ASK_CLARIFICATION, ERROR_PREFIX, UNKNOWN_TOOL_PREFIX
from bilgin.engine.executor import LocalExecutor
from bilgin.schema_map import build, doc

GOLDEN = "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT WHERE IL = 'ANKARA' ORDER BY CARI_KOD"
QUESTION = "Satış derken brüt mü net mi kastediliyor?"
OPTIONS = ["Brüt satış (iptaller dahil)", "Net satış (iptaller düşülmüş)"]


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    paths = tmp_path_factory.mktemp("clarify")
    db = paths / "test.db"
    build.build_db(config.SEED, db, paths / "test.sql")
    return LocalExecutor("sqlite", db, audit_path=paths / "audit.jsonl")


def ask(name: str, **arguments) -> ChatResponse:
    return ChatResponse(tool_calls=[ToolCall(id="", name=name, arguments=arguments)])


def ask_clarify(question: str, options) -> ChatResponse:
    return ask("ask_clarification", question=question, options=options)


def world(executor, schema: dict, clarify: bool) -> modes.ToolContext:
    return modes.ToolContext(executor=executor, schema=schema, mode="full", clarify=clarify)


def run(executor, schema: dict, llm, clarify: bool):
    return loop.run_agent(
        QUESTION,
        llm,
        executor,
        schema,
        "test",
        mode="full",
        context=world(executor, schema, clarify),
    )


class Recorder:
    """Senaryoyu oynatırken modele giden araç listesini ve sohbeti de saklar."""

    def __init__(self, turns):
        self._replay = FakeLLM(turns)
        self.tools = None
        self.messages = None

    def chat(self, messages, tools=None):
        self.tools = tools
        self.messages = messages
        return self._replay.chat(messages, tools)


# ------------------------------------------------------------------ şema ve argüman denetimi


def test_the_tool_is_declared_but_stays_out_of_the_run_one_list():
    function = ASK_CLARIFICATION["function"]
    assert function["name"] == "ask_clarification"
    assert function["description"].strip()
    assert function["parameters"]["required"] == ["question", "options"]
    assert function["parameters"]["properties"]["options"]["items"] == {"type": "string"}
    assert "ask_clarification" not in tools.TOOL_NAMES, "Run 1'in üç aracı sabittir"


def test_a_valid_call_shows_the_question_and_every_option(schema):
    answer = tools.dispatch(
        "ask_clarification", {"question": QUESTION, "options": OPTIONS}, world(None, schema, True)
    )
    assert QUESTION in answer
    for option in OPTIONS:
        assert f"- {option}" in answer


def test_the_accepted_question_and_options_reach_the_run_trimmed():
    question, options = tools.clarify_request(
        {"question": f" {QUESTION} ", "options": [f" {option} " for option in OPTIONS]}
    )
    assert (question, options) == (QUESTION, OPTIONS)


@pytest.mark.parametrize(
    "args,problem",
    [
        ({"question": "  ", "options": OPTIONS}, "boş"),
        ({"options": OPTIONS}, "boş"),
        ({"question": QUESTION, "options": OPTIONS[0]}, "metin dizisi"),
        ({"question": QUESTION, "options": ["yalnız bir okunuş"]}, "En az iki"),
        ({"question": QUESTION, "options": ["a", "b", "c", "d", "e"]}, str(config.CLARIFY_MAX_OPTIONS)),
        ({"question": QUESTION, "options": ["a", " "]}, "boş metin"),
        ({"question": QUESTION, "options": ["a", "a"]}, "Yinelenen"),
        ({"question": QUESTION, "options": ["a", 3]}, "yalnız metin"),
    ],
)
def test_every_invalid_call_names_its_own_problem(args, problem, schema):
    answer = tools.dispatch("ask_clarification", args, world(None, schema, True))
    assert answer.startswith(f"{ERROR_PREFIX}: ")
    assert problem in answer


# ------------------------------------------------------------------ açıkken çalışma


def test_a_valid_question_stops_the_run_with_its_options(executor, schema):
    result = run(executor, schema, FakeLLM([ask_clarify(QUESTION, OPTIONS)]), clarify=True)
    assert result.status == "needs_clarification"
    assert result.clarification == {"question": QUESTION, "options": OPTIONS}
    assert result.submitted_sql is None
    assert [step.tool for step in result.steps] == ["ask_clarification"]
    assert result.steps[0].ok
    assert all(option in result.steps[0].summary for option in OPTIONS)


def test_a_refused_question_goes_on_and_still_submits(executor, schema):
    result = run(
        executor,
        schema,
        FakeLLM([ask_clarify("", OPTIONS), ask("submit_sql", sql=GOLDEN)]),
        clarify=True,
    )
    assert result.status == "submitted"
    assert result.submitted_sql == GOLDEN
    assert result.clarification is None
    assert [step.tool for step in result.steps] == ["ask_clarification", "submit_sql"]
    assert not result.steps[0].ok
    assert result.steps[0].summary.startswith(ERROR_PREFIX)


def test_a_refused_question_is_a_tool_call_and_never_a_failed_query(executor, schema):
    """Sınırı dolduran şey araç çağrısı; reddedilen soru sorgu sayılmıyor, 3'te değil 8'de duruyor."""
    limit = config.MAX_TOOL_CALLS_BY_MODE["full"]
    assert limit > config.MAX_FAILED_RUNS, "senaryonun ayırt edebilmesi için"
    refused = ask_clarify(QUESTION, ["tek seçenek"])
    result = run(executor, schema, FakeLLM([refused] * (limit + 1)), clarify=True)
    assert result.status == "no_submission"
    assert len(result.steps) == limit
    assert str(limit) in result.stop_reason


# ------------------------------------------------------------------ kapalıyken hiçbir şey değişmez


def test_without_clarify_the_model_is_shown_the_modes_own_tools(executor, schema):
    client = Recorder([ask_clarify(QUESTION, OPTIONS), ask("submit_sql", sql=GOLDEN)])
    result = run(executor, schema, client, clarify=False)
    assert [tool["function"]["name"] for tool in client.tools] == [
        tool["function"]["name"] for tool in modes.get_mode("full").tools
    ]
    assert result.status == "submitted"
    assert result.clarification is None
    assert result.steps[0].summary.startswith(UNKNOWN_TOOL_PREFIX)


def test_the_clarification_rules_reach_the_system_prompt_only_when_open(executor, schema):
    on = Recorder(golden_replay(GOLDEN))
    run(executor, schema, on, clarify=True)
    off = Recorder(golden_replay(GOLDEN))
    run(executor, schema, off, clarify=False)
    assert prompt.CLARIFY_RULES in on.messages[0]["content"]
    assert prompt.CLARIFY_RULES not in off.messages[0]["content"]
    assert off.messages[0]["content"] == prompt.full_prompt(config.AS_OF, schema)


def test_the_extra_tool_is_paid_for_in_the_prompt_estimate(executor, schema):
    """Araç şeması istemin bir parçası: aynı sohbetin tahmini clarify açıkken daha pahalıdır."""
    on = run(executor, schema, FakeLLM(golden_replay(GOLDEN)), clarify=True)
    off = run(executor, schema, FakeLLM(golden_replay(GOLDEN)), clarify=False)
    assert on.peak_estimate > off.peak_estimate
