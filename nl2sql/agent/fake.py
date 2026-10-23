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
from collections.abc import Callable, Iterable, Sequence
from dataclasses import replace

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

def golden_replay(golden_sql: str) -> list[Turn]:
    """The passing path: read the schema, run the golden SQL, submit it."""
    return [
        _ask("get_schema"),
        _ask("run_sql", sql=golden_sql),
        _ask("submit_sql", sql=golden_sql),
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


def for_golden(
    golden_lines: Iterable[dict], fallback_sql: str = FALLBACK_SQL, mode: str = "full"
) -> FakeLLM:
    """One client for every question: golden replay when the question text matches, stock query else.

    A golden line with no question or no SQL is not registered, so it can never be answered with
    an empty query; such a question falls back to the stock one. In `rag` mode both paths go
    through the retrieval tools, because searching is all that mode can do.
    """
    by_question = {}
    for line in golden_lines:
        question = str(line.get("question") or "").strip()
        sql = str(line.get("sql") or "").strip()
        if question and sql:
            by_question[question] = line

    def script(messages: list[dict]) -> list[Turn]:
        question = _question(messages)
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
