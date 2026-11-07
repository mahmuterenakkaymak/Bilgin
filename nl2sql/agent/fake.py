# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""A model-free client that replays a scripted conversation.

The loop asks the client one thing: "what does the model say next?". So a fake is a list of turns
plus a rule for finding which turn a transcript has reached - the number of assistant messages it
already contains. Replay is therefore a pure function of the transcript: no hidden counter to
reset between questions, the same transcript always gets the same answer, and one instance can
serve a whole eval run. The cost a real endpoint reports is faked but consistent: prompt tokens
grow with the transcript, so the report's context numbers still mean something.

The builders below are the paths the loop has to survive: a golden replay, a confident wrong
answer, a policy reject that recovers, a query the database refuses, a model that only calls
tools, one that never submits, and an endpoint that is down. A script entry may be an exception
instead of a turn; replaying it raises, which is how `unreachable` reaches the llm_error outcome.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace

from nl2sql.agent.clarify import split_follow_up
from nl2sql.agent.llm import UNREACHABLE, ChatResponse, LLMError, ToolCall

# A script entry is the turn the model produces, or the failure that stops it.
Turn = ChatResponse | Exception
Script = Sequence[Turn] | Callable[[list[dict]], Sequence[Turn]]

# Port 9 (discard) never answers, so the error names an address a reader recognises.
FAKE_URL = "http://127.0.0.1:9/v1"

# The queries the builders reach for: one the policy rejects, one the database rejects, and the
# stock answer for a question no golden line matches.
FORBIDDEN_SQL = "SELECT name FROM sys.objects"
BROKEN_SQL = "SELECT OLMAKOLAN_KOLON FROM TBLSTSABIT"
FALLBACK_SQL = "SELECT TOP 20 STOK_KODU, STOK_ADI FROM TBLSTSABIT ORDER BY STOK_KODU"

# A follow-up turn is told from the same wording in another chain by the questions asked before
# it, and those are exactly the `Tur n sorusu:` lines the history block writes (PLAN R7-4, R7-13).
_TURN_QUESTION = re.compile(r"^Tur \d+ sorusu: (.*)$", re.MULTILINE)

CHARS_PER_TOKEN = 4
FAKE_LATENCY_MS = 180.0


class FakeLLM:
    """The OpenAIClient contract without a model: replays a script, turn by turn."""

    def __init__(self, script: Script) -> None:
        self._script = script

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> ChatResponse:
        """The turn this transcript has reached; ``tools`` is ignored, the script knows them."""
        index = _turn_index(messages)
        script = self._script(messages) if callable(self._script) else self._script
        turn = script[min(index, len(script) - 1)]
        if isinstance(turn, Exception):
            raise turn
        return _priced(turn, messages, index)


# ------------------------------------------------------------------ builders

def golden_replay(golden_sql: str, context: dict | None = None) -> list[Turn]:
    """The passing path: read the schema, run the golden SQL, submit it.

    ``context`` is the conversation note a follow-up turn submits with its SQL (PLAN R7-13); left
    out, the submit is the one Run 6 always wrote.
    """
    submit = {"sql": golden_sql} if context is None else {"sql": golden_sql, "context": context}
    return [
        _ask("get_schema"),
        _ask("run_sql", sql=golden_sql),
        _ask("submit_sql", **submit),
    ]


def wrong_sql(sql: str) -> list[Turn]:
    """A confident wrong answer: the query runs, the result is not the golden one."""
    return [
        _ask("get_schema"),
        _ask("run_sql", sql=sql),
        _ask("submit_sql", sql=sql),
    ]


def forbidden_then_recover(golden_sql: str) -> list[Turn]:
    """Rejected by the guardrail first, then the golden SQL - the reject has to show in the steps."""
    return [
        _ask("get_schema"),
        _ask("run_sql", sql=FORBIDDEN_SQL),
        _ask("run_sql", sql=golden_sql),
        _ask("submit_sql", sql=golden_sql),
    ]


def failing_sql_forever() -> list[Turn]:
    """The database says no every time; the loop has to stop at MAX_FAILED_RUNS."""
    return [_ask("get_schema"), _ask("run_sql", sql=BROKEN_SQL)]


def tool_spam() -> list[Turn]:
    """get_schema over and over; the loop has to stop at MAX_TOOL_CALLS."""
    return [_ask("get_schema")]


def never_submit() -> list[Turn]:
    """Answers in prose and stops; no tool is ever asked for, so nothing is submitted."""
    return [_says("Ürün kodlarını ve adlarını listeledim; sonucu karttan kendiniz de çekebilirsiniz.")]


def unreachable() -> list[Turn]:
    """The endpoint is down: every turn raises the error the real client would raise."""
    return [LLMError(UNREACHABLE.format(url=FAKE_URL))]


def rag_replay(line: dict) -> list[Turn]:
    """The `rag` path: ask the index for the tables, read them, join them, then the golden SQL.

    A `rag` model sees only table names, so it has to earn every column: the search finds the
    tables, the detail hands back their columns, and a join path is only worth asking for when the
    answer really combines more than one of them.
    """
    question = str(line.get("question") or "").strip()
    sql = str(line.get("sql") or "").strip()
    tables = [str(name).strip() for name in (line.get("requires_tables") or []) if str(name).strip()]
    turns = [_ask("search_schema", query=question), _ask("get_table_details", tables=tables)]
    if len(tables) > 1:
        turns.append(_ask("find_join_path", tables=tables))
    return [*turns, _ask("run_sql", sql=sql), _ask("submit_sql", sql=sql)]


# A clarification on a golden question is a wrong answer (PLAN R5-12), so measuring that needs a
# client that asks whatever was asked: the two options are only there to be a legal call.
OVER_CLARIFY_QUESTION = "Sorunuz iki anlama geliyor; hangisini kastettiniz?"
OVER_CLARIFY_OPTIONS = ["İlk okunuş", "İkinci okunuş"]


def over_clarify() -> list[Turn]:
    """The same ask_clarification every turn: the run always stops on a question, never answers."""
    return [_ask("ask_clarification", question=OVER_CLARIFY_QUESTION, options=OVER_CLARIFY_OPTIONS)]


def for_golden(
    golden_lines: Iterable[dict],
    fallback_sql: str = FALLBACK_SQL,
    mode: str = "full",
    ambiguous: Iterable[dict] | None = None,
    followups: Iterable[dict] | None = None,
) -> FakeLLM:
    """One client for every question: golden replay when the question text matches, stock query else.

    A golden line with no question or no SQL is not registered, so it can never be answered with
    an empty query; such a question falls back to the stock one. In `rag` mode both paths go
    through the retrieval tools, because searching is all that mode can do.

    `ambiguous` lines (PLAN R5-12) are the questions that have to be asked about: the question
    itself gets one ask_clarification turn whose options are the reading labels, and its follow-up
    (R5-11) runs the chosen reading's SQL - in `rag` mode after a search, like every other answer.
    A choice no reading offers falls back to the stock query; a golden question never asks.

    `followups` lines (PLAN R7-13) are the conversation chains. A chain turn is recognised by its
    question *and* the questions of the turns before it, read back out of the history block, so the
    same wording in two chains gets its own SQL, and its submit carries the golden `uses_turns` as
    the context note. A chain's first turn has no earlier questions, so it answers that question
    wherever it is asked - which is what a turn 1 golden question always did.
    """
    by_chain = {}
    for chain in followups or ():
        earlier: list[str] = []
        for turn in chain.get("turns") or []:
            question = _key(turn.get("question"))
            sql = str(turn.get("sql") or "").strip()
            if question and sql:
                by_chain[(question, tuple(earlier))] = (sql, _chain_note(turn))
            earlier.append(question)

    by_question = {}
    for line in golden_lines:
        question = str(line.get("question") or "").strip()
        sql = str(line.get("sql") or "").strip()
        if question and sql:
            by_question[question] = line

    by_ambiguous = {}
    for line in ambiguous or ():
        question = str(line.get("question") or "").strip()
        if question and len(_readings(line)) >= 2:
            by_ambiguous[question] = line

    def script(messages: list[dict]) -> list[Turn]:
        question, choice = split_follow_up(_question(messages))
        chain = by_chain.get((_key(question), _previous_questions(messages)))
        if chain is not None:
            sql, note = chain
            return golden_replay(sql, note)
        line = by_ambiguous.get(question)
        if line is not None:
            readings = _readings(line)
            if choice is None:
                options = [label for label, _ in readings]
                return [_ask("ask_clarification", question=_clarify_question(line), options=options)]
            chosen = next((sql for label, sql in readings if label == choice), "") or fallback_sql
            # ASSUMPTION: an ambiguous line has no requires_tables, so its rag follow-up searches
            # for the tables the way rag_replay opens, then replays the reading as a golden answer.
            if mode != "rag":
                return golden_replay(chosen)
            return [_ask("search_schema", query=question), *golden_replay(chosen)]
        line = by_question.get(question)
        if mode != "rag":
            return golden_replay(line["sql"] if line else fallback_sql)
        if line is not None:
            return rag_replay(line)
        return [
            _ask("search_schema", query=question),
            _ask("run_sql", sql=fallback_sql),
            _ask("submit_sql", sql=fallback_sql),
        ]

    return FakeLLM(script)


def suggest_client(golden_lines: Iterable[dict], roles: Iterable[str]) -> FakeLLM:
    """The suggester's fake (PLAN R7-20): the dataset's golden questions dealt round-robin.

    Round-robin is what keeps the fake honest here - every text it hands back is a question this
    same client can answer from the golden replay, so a suggestion run reaches the store exactly
    the way a real model's run does.
    """
    by_role: dict[str, list[str]] = {role: [] for role in roles}
    names = list(by_role)
    for n, line in enumerate(golden_lines):
        question = str(line.get("question") or "").strip()
        if question and names:
            by_role[names[n % len(names)]].append(question)
    return FakeLLM(lambda messages: [_says(json.dumps(by_role, ensure_ascii=False))])


# ------------------------------------------------------------------ narrators

# The number no result has, written the way the guard would otherwise accept.
INVENTED_NUMBER = "9.999.999"
NARRATION_NO_FACTS = "Sonuçta anlatılacak sayısal özet yok."


def narration_client() -> FakeLLM:
    """A narrator that speaks the first fact's own display: deterministic, and the guard has seen it.

    The facts are read back out of the `GERÇEKLER:` block the narrator was shown, so the sentence
    stays a function of the result: the same answer narrated twice gets the same words twice.
    """
    return FakeLLM(lambda messages: [_says(_spoken_fact(messages))])


def inventing_narrator() -> FakeLLM:
    """A narrator that names a number the result does not have, every turn: the guard must fall back."""
    return FakeLLM(lambda messages: [_says(f"Sonuç {INVENTED_NUMBER} olarak ölçüldü.")])


def rounding_narrator() -> FakeLLM:
    """One unit of the last shown digit wrong at first, the honest display on the retry."""

    def script(messages: list[dict]) -> list[Turn]:
        fact = _first_fact(messages)
        if fact is not None and _turn_index(messages) == 0:
            return [_says(_fact_sentence(fact, shift=True))]
        return [_says(_spoken_fact(messages))]

    return FakeLLM(script)


# ------------------------------------------------------------------ internals

def _ask(name: str, **arguments) -> ChatResponse:
    """One turn that asks for a single tool call; the id is filled in at replay time."""
    return ChatResponse(tool_calls=[ToolCall(id="", name=name, arguments=arguments)])


def _says(content: str) -> ChatResponse:
    """One turn that only talks."""
    return ChatResponse(content=content)


def _turn_index(messages: list[dict]) -> int:
    """How far the conversation has got: one assistant message is one turn we already answered."""
    # ASSUMPTION: the loop echoes the assistant message back with the tool results, as the
    # OpenAI-compatible protocol requires; the transcript is the only place a shared client can
    # read its turn from.
    return sum(1 for message in messages if message.get("role") == "assistant")


def _question(messages: list[dict]) -> str:
    """The question is the first user message; tool results are appended after it."""
    for message in messages:
        if message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


def _previous_questions(messages: list[dict]) -> tuple[str, ...]:
    """The questions the history block says were asked before this one, in the order it lists them."""
    for message in messages:
        if message.get("role") == "system":
            return tuple(_key(line) for line in _TURN_QUESTION.findall(str(message.get("content") or "")))
    return ()


def _chain_note(turn: dict) -> dict:
    """The context note a chain turn submits: its golden `uses_turns`, empty when it stood alone.

    ASSUMPTION: `refine` is one of the free-form turn tags a chain line carries (Contracts
    "followup chain"); a turn tagged with it rewrites the last turn it says it uses, so that turn
    is what `refines_sql_of` names.
    """
    uses = [number for number in (turn.get("uses_turns") or []) if isinstance(number, int)]
    refines = uses[-1] if uses and "refine" in (turn.get("tags") or []) else None
    return {"uses_turns": uses, "entities": [], "refines_sql_of": refines}


def _key(text) -> str:
    """Question key in the shape the block stores it: one line, runs of whitespace collapsed."""
    return " ".join(str(text or "").split())


def _readings(line: dict) -> list[tuple[str, str]]:
    """(label, sql) of every reading that has both: a reading without one is not a choice to offer."""
    readings = []
    for reading in line.get("readings") or []:
        label = str(reading.get("label") or "").strip()
        sql = str(reading.get("sql") or "").strip()
        if label and sql:
            readings.append((label, sql))
    return readings


def _clarify_question(line: dict) -> str:
    """The term is what only the user can define, so the question names it and nothing else (R5-11)."""
    return f"'{str(line.get('term') or '').strip()}' ile neyi kastediyorsunuz?"


def _first_fact(messages: list[dict]) -> dict | None:
    """The first fact the narrator was shown, read back from the `GERÇEKLER:` block of the question."""
    for message in messages:
        if message.get("role") != "user":
            continue
        _, _, tail = str(message.get("content") or "").partition("GERÇEKLER:")
        try:
            shown = json.loads(tail.strip() or "[]")
        except json.JSONDecodeError:
            return None
        return shown[0] if shown else None
    return None


def _spoken_fact(messages: list[dict]) -> str:
    fact = _first_fact(messages)
    return _fact_sentence(fact) if fact is not None else NARRATION_NO_FACTS


def _fact_sentence(fact: dict, shift: bool = False) -> str:
    """A sentence whose only number is the fact's own display, which is what the guard allows."""
    display = str(fact.get("display") or "")
    return f"{fact.get('label')} {_shift_last_digit(display) if shift else display}."


def _shift_last_digit(text: str) -> str:
    """Move the last shown digit by one: more than the half-unit tolerance ever forgives."""
    for index in range(len(text) - 1, -1, -1):
        if text[index].isdigit():
            digit = int(text[index])
            return text[:index] + str(digit - 1 if digit == 9 else digit + 1) + text[index + 1 :]
    return text


def _priced(turn: ChatResponse, messages: list[dict], index: int) -> ChatResponse:
    """Add the cost an endpoint reports; a builder may already have pinned its own numbers."""
    return replace(
        turn,
        tool_calls=[
            replace(call, id=f"call_{index + 1}_{n + 1}")
            for n, call in enumerate(turn.tool_calls)
        ],
        prompt_tokens=turn.prompt_tokens or _tokens(_transcript(messages)),
        completion_tokens=turn.completion_tokens or _tokens(_spoken(turn)),
        latency_ms=turn.latency_ms or FAKE_LATENCY_MS,
    )


def _transcript(messages: list[dict]) -> str:
    return json.dumps(messages, ensure_ascii=False, default=str)


def _spoken(turn: ChatResponse) -> str:
    """Everything the turn puts on the wire: its text plus the arguments of every tool call."""
    asked = "".join(json.dumps(call.arguments, ensure_ascii=False) for call in turn.tool_calls)
    return turn.content + asked


def _tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)
