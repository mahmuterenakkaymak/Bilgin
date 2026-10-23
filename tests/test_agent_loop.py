"""Ajan döngüsü: mesaj akışı, adım kaydı, üç sınır ve LLM hatı.

Burada model yok; FakeLLM senaryo oynatıyor, veritabanı gerçek (build_db ile kurulmuş SQLite
üzerinde LocalExecutor). Böylece döngünün sözleşmesi uçtan uca sınanabiliyor: submit_sql başarılı
olunca durup SQL'i yakalaması, reddedilen bir sorguyu adımda gösterip toparlanması, üç başarısız
çalıştırmada, araç çağrı sınırında ve zaman aşımında durması, endpoint düşüğünde llm_error olması.
Adımların token/gecikme taşıması da raporun boş kalmaması için burada doğrulanıyor.
"""

import pytest

from nl2sql import config
from nl2sql.agent import loop
from nl2sql.agent.fake import (
    BROKEN_SQL,
    FORBIDDEN_SQL,
    FakeLLM,
    failing_sql_forever,
    forbidden_then_recover,
    golden_replay,
    never_submit,
    tool_spam,
    unreachable,
    wrong_sql,
)
from nl2sql.agent.tools import ERROR_PREFIX
from nl2sql.engine.executor import LocalExecutor
from nl2sql.schema_map import build, doc

GOLDEN = "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT WHERE IL = 'ANKARA' ORDER BY CARI_KOD"
WRONG = "SELECT CARI_KOD FROM TBLCASABIT"
QUESTION = "Ankara'daki alıcı carilerin kodu ve ünvanı nedir?"


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    paths = tmp_path_factory.mktemp("loop")
    db = paths / "test.db"
    build.build_db(config.SEED, db, paths / "test.sql")
    return LocalExecutor("sqlite", db, audit_path=paths / "audit.jsonl")


def run(llm, executor, schema, **kwargs):
    return loop.run_agent(QUESTION, llm, executor, schema, "test", **kwargs)


def tools_of(run_result):
    return [step.tool for step in run_result.steps]


# ------------------------------------------------------------------ başarılı yol

def test_the_passing_run_submits_the_golden_query_and_stops(executor, schema):
    result = run(FakeLLM(golden_replay(GOLDEN)), executor, schema)
    assert result.status == "submitted"
    assert result.submitted_sql == GOLDEN
    assert tools_of(result) == ["get_schema", "run_sql", "submit_sql"]
    assert all(step.ok for step in result.steps)


def test_every_step_carries_the_tokens_and_latency_of_its_turn(executor, schema):
    result = run(FakeLLM(golden_replay(GOLDEN)), executor, schema)
    assert all(step.prompt_tokens > 0 and step.completion_tokens > 0 for step in result.steps)
    assert all(step.latency_ms > 0 for step in result.steps)
    assert result.total_prompt_tokens > 0
    assert result.max_prompt_tokens > 0
    assert result.elapsed_s >= 0


def test_the_submitted_sql_actually_runs_against_the_database(executor, schema):
    """submit_sql yalnız metin dönmez; sorgu policy'den geçip çalıştırılmış olmalı."""
    result = run(FakeLLM(golden_replay(GOLDEN)), executor, schema)
    assert result.steps[-1].ok
    assert not result.steps[-1].summary.startswith(ERROR_PREFIX)


# ------------------------------------------------------------------ yanlış cevap

def test_a_wrong_query_is_still_submitted_as_an_answer(executor, schema):
    result = run(FakeLLM(wrong_sql(WRONG)), executor, schema)
    assert result.status == "submitted"
    assert result.submitted_sql == WRONG


# ------------------------------------------------------------------ red ve toparlanma

def test_a_rejected_query_shows_in_the_steps_then_the_run_recovers(executor, schema):
    result = run(FakeLLM(forbidden_then_recover(GOLDEN)), executor, schema)
    assert result.status == "submitted"
    assert result.submitted_sql == GOLDEN
    assert tools_of(result) == ["get_schema", "run_sql", "run_sql", "submit_sql"]
    rejected = result.steps[1]
    assert not rejected.ok
    assert rejected.summary.startswith(ERROR_PREFIX) and "policy" in rejected.summary


# ------------------------------------------------------------------ başarısız çalıştırma sınırı

def test_three_failed_queries_stop_the_run_without_a_submission(executor, schema):
    result = run(FakeLLM(failing_sql_forever()), executor, schema)
    assert result.status == "no_submission"
    assert result.submitted_sql is None
    failed = [step for step in result.steps if step.tool == "run_sql"]
    assert len(failed) == config.MAX_FAILED_RUNS
    assert all(not step.ok for step in failed)
    assert "sınır" in result.stop_reason.lower()


# ------------------------------------------------------------------ araç çağrı sınırı

def test_the_tool_call_limit_stops_a_model_that_only_calls_tools(executor, schema):
    result = run(FakeLLM(tool_spam()), executor, schema)
    assert result.status == "no_submission"
    assert len(result.steps) == config.MAX_TOOL_CALLS
    assert all(step.tool == "get_schema" for step in result.steps)


# ------------------------------------------------------------------ hiç submit etmemesi

def test_a_model_that_only_talks_never_submits(executor, schema):
    result = run(FakeLLM(never_submit()), executor, schema, max_turns=3)
    assert result.status == "no_submission"
    assert result.submitted_sql is None
    assert all(step.tool == "" and step.summary for step in result.steps)


# ------------------------------------------------------------------ zaman aşımı

def test_the_timeout_stops_before_the_model_is_consulted(executor, schema):
    result = run(FakeLLM(golden_replay(GOLDEN)), executor, schema, timeout_s=0.0)
    assert result.status == "timeout"
    assert result.steps == []


# ------------------------------------------------------------------ endpoint düşük

def test_an_unreachable_endpoint_becomes_llm_error(executor, schema):
    result = run(FakeLLM(unreachable()), executor, schema)
    assert result.status == "llm_error"
    assert result.steps == []
    assert "127.0.0.1:" in result.stop_reason
