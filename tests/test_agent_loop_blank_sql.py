# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Boş bir sorgu ve olmayan bir araç cevap sayılmaz; döngü modeli yeniden denemeye bırakır.

tools.dispatch boş bir SQL'e ve tanınmayan bir araç adına sabit başlangıçlı bir red cümlesiyle
cevap veriyor. Döngü o cümleleri "ok" saydığı için boş bir submit_sql koşuyu submitted diye
bitiriyor (submitted_sql = ""), boş bir run_sql de başarısız çalıştırma sayacına işlemiyordu.
Burada model yok: FakeLLM boş bir submit, ardından gerçek bir submit oynatıyor; veritabanı gerçek.
"""

import pytest

from bilgin import config
from bilgin.agent import loop
from bilgin.agent.fake import FakeLLM
from bilgin.agent.llm import ChatResponse, ToolCall
from bilgin.engine.executor import LocalExecutor
from bilgin.schema_map import build, doc

SQL = "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT WHERE IL = 'ANKARA' ORDER BY CARI_KOD"
BLANK = "   "
QUESTION = "Ankara'daki alıcı carilerin kodu ve ünvanı nedir?"


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    paths = tmp_path_factory.mktemp("blank")
    db = paths / "test.db"
    build.build_db(config.SEED, db, paths / "test.sql")
    return LocalExecutor("sqlite", db, audit_path=paths / "audit.jsonl")


def ask(name: str, **arguments) -> ChatResponse:
    return ChatResponse(tool_calls=[ToolCall(id="", name=name, arguments=arguments)])


def run(llm, executor, schema):
    return loop.run_agent(QUESTION, llm, executor, schema, "test")


def test_a_blank_submit_is_not_an_answer_and_the_run_keeps_going(executor, schema):
    result = run(FakeLLM([ask("submit_sql", sql=BLANK), ask("submit_sql", sql=SQL)]), executor, schema)
    assert result.status == "submitted"
    assert result.submitted_sql == SQL
    assert not result.steps[0].ok
    assert result.steps[0].summary.startswith("Sorgu boş")
    assert result.steps[-1].ok


def test_three_blank_queries_stop_the_run_without_a_submission(executor, schema):
    result = run(FakeLLM([ask("run_sql", sql=BLANK)]), executor, schema)
    assert result.status == "no_submission"
    assert result.submitted_sql is None
    assert len(result.steps) == config.MAX_FAILED_RUNS
    assert all(not step.ok for step in result.steps)
    assert "sınır" in result.stop_reason.lower()


def test_an_invented_tool_is_not_an_answer_either(executor, schema):
    result = run(FakeLLM([ask("drop_table"), ask("submit_sql", sql=SQL)]), executor, schema)
    assert result.status == "submitted"
    assert result.submitted_sql == SQL
    assert not result.steps[0].ok
    assert result.steps[0].summary.startswith("Bilinmeyen araç")
