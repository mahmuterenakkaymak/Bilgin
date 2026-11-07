# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Eksik bağlam düşürmez: araçlar red dönerir, kuralı olmayan full_rules ise koşmaz (T72).

`ToolContext` arama indeksini ve join graph'ını `None` doğuruyor, runner ile CLI da bugün bağlam
vermeden çağırıyor. İki tarafın sözleşmesi farklı: `dispatch` kötü bir çağrıda yükseltmez, o yüzden
rag'in arama araçları onlarsız bir red satırı dönmeli ve döngü bunu başarısız adım saymalı.
`full_rules`ta tam tersi doğru: `rules=[]` istemi `full` ile aynı olduğu için sessiz kalmak A/B'nin
kendisini bozar, yani bağlamın yokluğu burada bir hatadır.
"""

import pytest

from nl2sql import config
from nl2sql.agent import fake, loop, modes
from nl2sql.agent.fake import FakeLLM
from nl2sql.agent.llm import ChatResponse, ToolCall
from nl2sql.agent.tools import ERROR_PREFIX, answer_is_ok, dispatch
from nl2sql.engine.executor import LocalExecutor
from nl2sql.schema_map import build, doc

SCHEMA = doc.load_schema()
QUESTION = "Geçen ayın net cirosu ne kadar?"

# Arama, kural araması ve join yolu: üçünün de gidecek bir yeri yok.
CALLS = {
    "search_schema": {"query": "stok hareketleri satış iade"},
    "search_rules": {"query": "ağustos net ciro"},
    "find_join_path": {"tables": ["TBLFATUIRS", "TBLCASABIT"]},
}


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    paths = tmp_path_factory.mktemp("missing-context")
    db = paths / "test.db"
    build.build_db(config.SEED, db, paths / "test.sql")
    return LocalExecutor("sqlite", db, audit_path=paths / "audit.jsonl")


def bare(executor) -> modes.ToolContext:
    """Bağlamın en eksik hali: ne indeks ne graph ne kural; mod yine rag."""
    return modes.ToolContext(executor=executor, schema=SCHEMA, mode="rag")


# ------------------------------------------------------------------ dispatch
@pytest.mark.parametrize("name,args", sorted(CALLS.items()))
def test_a_tool_without_its_context_answers_instead_of_raising(executor, name, args):
    answer = dispatch(name, args, bare(executor))
    assert isinstance(answer, str)
    assert answer.startswith(f"{ERROR_PREFIX}: ")
    assert answer_is_ok(answer) is False


def test_the_missing_index_names_itself(executor):
    assert dispatch("search_schema", CALLS["search_schema"], bare(executor)) == (
        f"{ERROR_PREFIX}: arama indeksi yok."
    )
    assert dispatch("search_rules", CALLS["search_rules"], bare(executor)) == (
        f"{ERROR_PREFIX}: arama indeksi yok."
    )


def test_the_missing_graph_names_itself(executor):
    assert dispatch("find_join_path", CALLS["find_join_path"], bare(executor)) == (
        f"{ERROR_PREFIX}: join graph yok."
    )


# ------------------------------------------------------------------ döngü
def test_a_rag_run_without_a_context_ends_in_failed_steps_not_a_crash(executor):
    """Asıl gerileme buradaydı: bağlamsız rag çağrısı AttributeError ile döngüden dışarı taşıyordu."""
    turn = ChatResponse(tool_calls=[ToolCall(id="", name="search_schema", arguments=CALLS["search_schema"])])
    result = loop.run_agent(QUESTION, FakeLLM([turn]), executor, SCHEMA, "test", mode="rag")
    assert result.status == "no_submission"
    assert [step.tool for step in result.steps] == ["search_schema"] * config.MAX_TOOL_CALLS_BY_MODE["rag"]
    assert not any(step.ok for step in result.steps)
    assert result.steps[0].summary.startswith(f"{ERROR_PREFIX}: ")


def test_full_rules_without_a_context_raises_naming_the_rules(executor):
    with pytest.raises(ValueError) as state:
        loop.run_agent(
            QUESTION,
            FakeLLM(fake.golden_replay(fake.FALLBACK_SQL)),
            executor,
            SCHEMA,
            "test",
            mode="full_rules",
        )
    assert "context.rules" in str(state.value)


def test_full_without_a_context_still_runs(executor):
    """Bağlamı olmayan full modun hiçbir araca ihtiyacı yok; şemanın tamamı zaten istemde."""
    result = loop.run_agent(
        QUESTION,
        FakeLLM(fake.golden_replay(fake.FALLBACK_SQL)),
        executor,
        SCHEMA,
        "test",
    )
    assert (result.status, result.mode) == ("submitted", "full")
    assert result.submitted_sql == fake.FALLBACK_SQL
    assert all(step.ok for step in result.steps)
