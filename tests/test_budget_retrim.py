# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Kırpılmış araç cevabı bir daha kırpılmaz (PLAN R4-11: kesim kalıcı, mesaj yerinde kalıyor).

trim_tool_answers her taşan turda aynı transcript'i baştan ölçüyor; marker'ı zaten taşıyan bir
cevabın tekrar kesilmesi iki şeyi bozuyor: `cuts` aynı cevabı birden kez sayıyor (AgentRun.trimmed,
"✂ bağlam: N araç cevabı kısaltıldı" satırı, compare'ın trimmed sütunu) ve marker'ın "N karakter"i
gerçekten silinenin yerine eski marker'ın uzunluğuyla yazılıyor - kırpılmış bir cevap her turda
biraz daha kısalıyor. Ölçülen: ikinci çağrının transcript'e hiç dokunmaması.
"""

import pytest

from nl2sql import config
from nl2sql.agent import budget, loop, modes
from nl2sql.agent.fake import FakeLLM
from nl2sql.agent.llm import ChatResponse, ToolCall
from nl2sql.engine.executor import LocalExecutor
from nl2sql.schema_map import build, doc

MARKER = "… (bağlam bütçesi için kısaltıldı: {n} karakter)"
PREFIX = "… (bağlam bütçesi için kısaltıldı:"

GOLDEN = "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT WHERE IL = 'ANKARA' ORDER BY CARI_KOD"
QUESTION = "Ankara'daki alıcı carilerin kodu ve ünvanı nedir?"
FULL_TOOLS = modes.get_mode("full").tools


def tool(answer: str) -> dict:
    return {"role": "tool", "tool_call_id": "c1", "content": answer}


def transcript(*answers: str) -> list[dict]:
    """system + user + her cevap için bir tool mesajı; sondaki en yeni araç cevabı."""
    messages = [{"role": "system", "content": "s" * 8}, {"role": "user", "content": "u" * 8}]
    return messages + [tool(answer) for answer in answers]


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    paths = tmp_path_factory.mktemp("retrim")
    db = paths / "test.db"
    build.build_db(config.SEED, db, paths / "test.sql")
    return LocalExecutor("sqlite", db, audit_path=paths / "audit.jsonl")


# ------------------------------------------------------------------ ikinci çağrı hiçbir şey yapmaz


def test_a_second_call_cuts_nothing_and_changes_nothing():
    once, cuts, _ = budget.trim_tool_answers(transcript("a" * 2000, "b" * 2000, "c" * 1000), 0)
    assert cuts == 2
    twice, recuts, _ = budget.trim_tool_answers(once, 0)
    assert recuts == 0, "kırpılmış cevaplar yeniden kesilmez"
    assert twice == once


def test_the_marker_keeps_the_characters_the_first_cut_removed():
    once, _, _ = budget.trim_tool_answers(transcript("a" * 2000, "b" * 100), 0)
    first = once[2]["content"]
    assert first == "a" * config.TRIM_TOOL_CHARS + MARKER.format(n=1600)
    twice, cuts, _ = budget.trim_tool_answers(once, 0)
    assert cuts == 0
    assert twice[2]["content"] == first, "sayı eski marker'ın uzunluğuyla ezilmez"


# ------------------------------------------------------------------ kesim kalıcı: bir cevap en çok bir kez


def test_an_answer_just_over_the_limit_is_cut_once_and_never_again():
    barely = "a" * (config.TRIM_TOOL_CHARS + 10)
    once, cuts, _ = budget.trim_tool_answers(transcript(barely, "b" * 100), 0)
    assert cuts == 1
    assert once[2]["content"].endswith(MARKER.format(n=10))
    twice, recuts, _ = budget.trim_tool_answers(once, 0)
    assert recuts == 0
    assert twice[2]["content"] == once[2]["content"], "ikinci kesim mesajı uzatmaz/geri kısaltmaz"


def test_the_message_never_grows_past_its_first_cut():
    long = "b" * (5 * (config.TRIM_TOOL_CHARS + 10))
    once, cuts, _ = budget.trim_tool_answers(transcript(long, "c" * 100), 0)
    assert cuts == 1
    first = once[2]["content"]
    for _ in range(3):
        again, recuts, _ = budget.trim_tool_answers(once, 0)
        assert recuts == 0
        assert len(again[2]["content"]) == len(first)


# ------------------------------------------------------------------ döngü: trimmed = kesilen cevap sayısı


def ask(name: str, **arguments) -> ChatResponse:
    return ChatResponse(tool_calls=[ToolCall(id="", name=name, arguments=arguments)])


def script() -> list[ChatResponse]:
    return [ask("get_schema") for _ in range(4)] + [ask("submit_sql", sql=GOLDEN)]


class Recorder:
    """Senaryoyu oynatırken modele giden sohbeti saklar; bütçe ölçümü ve kesilenler buradan."""

    def __init__(self, script):
        self._llm = FakeLLM(script)
        self.seen = []

    def chat(self, messages, tools=None):
        self.seen.append([dict(message) for message in messages])
        return self._llm.chat(messages, tools)


def test_trimmed_counts_each_answer_once(executor, schema):
    probe = Recorder(script())
    loop.run_agent(QUESTION, probe, executor, schema, "test", budget=None)
    # Bütçe = son istemin kırpılabilecek her cevabı kırpılmış halinin tahmini: hiçbir tur taşmıyor
    # ve her turda yalnızca YENİ bir cevap kırpılıyor.
    limit = budget.trim_tool_answers(probe.seen[-1], 0, FULL_TOOLS)[2]
    recorder = Recorder(script())
    result = loop.run_agent(QUESTION, recorder, executor, schema, "test", budget=limit)
    assert result.status == "submitted"
    cut = [m for m in recorder.seen[-1] if PREFIX in (m.get("content") or "")]
    assert len(cut) >= 2, "birden fazla tur kırpma görmeli"
    assert result.trimmed == len(cut), "aynı cevap birden kez sayılmaz"
