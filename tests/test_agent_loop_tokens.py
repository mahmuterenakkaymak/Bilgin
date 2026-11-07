# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Token sayımı yanıt başına bir kez yapılır.

Endpoint maliyeti araç çağrısı başına değil yanıt başına bildirir, ama döngü tek bir yanıtı her araç
çağrısı için ayrı bir adım sayar. Senaryo bilinçli olarak bir yanıtta iki araç çağrısı istiyor:
koşunun toplamı yanıt sayısının toplamı olmalı (adım sayısının değil), adım satırları da aynı maliyeti
ikinci kez taşımamalı. Rapordaki, canlı satırdaki ve `ask` çıktısındaki token sayısı bu toplama
dayandığı için buradaki ölçüm hepsini ilgilendiriyor.
"""

import pytest

from nl2sql import config
from nl2sql.agent import loop
from nl2sql.agent.fake import FakeLLM
from nl2sql.agent.llm import ChatResponse, ToolCall
from nl2sql.engine.executor import LocalExecutor
from nl2sql.eval import runner
from nl2sql.schema_map import build, doc

GOLDEN = "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT WHERE IL = 'ANKARA' ORDER BY CARI_KOD"
QUESTION = "Ankara'daki alıcı carilerin kodu ve ünvanı nedir?"


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    paths = tmp_path_factory.mktemp("tokens")
    db = paths / "test.db"
    build.build_db(config.SEED, db, paths / "test.sql")
    return LocalExecutor("sqlite", db, audit_path=paths / "audit.jsonl")


def turn(*names, prompt=0, completion=0, says=""):
    """Bir yanıt: istenen araç çağrıları ve endpoint'in bildirdiği sabit maliyet.

    Maliyetler sabit veriliyor ki toplamın kaç olması gerektiği senaryodan okunabilsin; FakeLLM
    kendi fiyatını yalnızca yanıt boş bırakınca yazıyor.
    """
    return ChatResponse(
        content=says,
        tool_calls=[
            ToolCall(id="", name=name, arguments={"sql": GOLDEN} if name.endswith("_sql") else {})
            for name in names
        ],
        prompt_tokens=prompt,
        completion_tokens=completion,
        latency_ms=120.0,
    )


def run(llm, executor, schema):
    return loop.run_agent(QUESTION, llm, executor, schema, "test")


# İki araç çağrılı yanıt + submit: yanıt başına 100+10 ve 200+5.
TWO_CALLS = [
    turn("run_sql", "get_schema", prompt=100, completion=10),
    turn("submit_sql", prompt=200, completion=5),
]


def test_a_response_with_two_tool_calls_is_charged_once(executor, schema):
    result = run(FakeLLM(TWO_CALLS), executor, schema)
    assert result.status == "submitted"
    assert len(result.steps) == 3, "yanıt iki araç çağrısı istediği için üç adım var"
    assert result.total_prompt_tokens == 300
    assert result.total_completion_tokens == 15


def test_the_peak_is_the_largest_response_not_the_sum(executor, schema):
    result = run(FakeLLM(TWO_CALLS), executor, schema)
    assert result.max_prompt_tokens == 200


def test_only_the_first_step_of_a_response_carries_its_cost(executor, schema):
    result = run(FakeLLM(TWO_CALLS), executor, schema)
    charged = [(step.prompt_tokens, step.completion_tokens) for step in result.steps]
    assert charged == [(100, 10), (0, 0), (200, 5)]
    assert sum(step.prompt_tokens for step in result.steps) == result.total_prompt_tokens


def test_a_prose_only_response_is_charged_once_too(executor, schema):
    script = [
        turn("get_schema", prompt=50, completion=4),
        turn(prompt=60, completion=7, says="Şemayı okudum, sorguyu yazıyorum."),
        turn("submit_sql", prompt=70, completion=3),
    ]
    result = run(FakeLLM(script), executor, schema)
    assert result.status == "submitted"
    assert (result.total_prompt_tokens, result.total_completion_tokens) == (180, 14)


def test_one_call_per_response_still_sums_every_response(executor, schema):
    script = [
        turn("get_schema", prompt=10, completion=1),
        turn("run_sql", prompt=20, completion=2),
        turn("submit_sql", prompt=30, completion=3),
    ]
    result = run(FakeLLM(script), executor, schema)
    assert (result.total_prompt_tokens, result.total_completion_tokens) == (60, 6)


def test_the_eval_total_counts_responses_not_steps(executor, schema):
    """QuestionResult.total_tokens (canlı satır ve report.md) aynı düzeltmeden besleniyor."""
    golden = [{"id": "T1", "question": QUESTION, "sql": GOLDEN}]
    results = runner.run_eval(lambda: FakeLLM(TWO_CALLS), executor, golden)
    assert results[0].outcome == "pass"
    assert results[0].total_tokens == 315
