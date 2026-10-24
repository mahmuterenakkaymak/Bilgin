"""T132: agent tarafı ölçtüğü veri kümesine göre konuşur (PLAN R4-4).

Referans tarih, sahte istemcinin kaydı ve eşleşmeyen bir sorunun cevabı kümenin kendisine aittir;
"bugün"ün ya da başka bir kümenin tablosu değil. Mini kümesi üzerinde ve uydurma bağlam olmadan
sınanıyor: mini'nin builder'ının kurduğu SQLite'tan geçen gerçek LocalExecutor, FakeEmbedder ile
kurulmuş gerçek arama, şemadan örülmüş gerçek join graphı ve gerçek döngü. Böylece ölçülen şey
gerçekten mini'nin tarihi, mini'nin şeması ve mini'nin altın cevabı.
"""

from pathlib import Path

import pytest

from nl2sql import config
from nl2sql.agent import modes, prompt
from nl2sql.agent.loop import run_agent
from nl2sql.cli import main as cli
from nl2sql.datasets import load_dataset
from nl2sql.engine.executor import LocalExecutor
from nl2sql.graph.graph import build_graph
from nl2sql.graph.profile import load_profile
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import build_search
from nl2sql.schema_map import doc

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
DATASET = load_dataset("mini", root=FIXTURE_ROOT)
SCHEMA = DATASET.schema()
RULES = DATASET.rules()
GOLDEN = DATASET.golden()
BY_ID = {line["id"]: line for line in GOLDEN}
AS_OF = DATASET.as_of
SEARCH = build_search(SCHEMA, RULES, FakeEmbedder())
GRAPH = build_graph(SCHEMA, load_profile(DATASET.profile_path))

# Döngü bağlamın executor'ını kendi denetimli haliyle değiştiriyor; burada boş durabilir.
CONTEXT = modes.ToolContext(
    executor=None,
    schema=SCHEMA,
    rules=RULES,
    search=SEARCH,
    graph=GRAPH,
    mode="rag",
    as_of=AS_OF,
)


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    """Kümenin kendi builder'ının kurduğu dosya; araç cevapları ve altın SQL bu kapıdan geçiyor."""
    folder = tmp_path_factory.mktemp("dataset-agent")
    database = folder / "mini.db"
    DATASET.build_db(db_path=database, sql_path=folder / "mini.sql")
    return LocalExecutor("sqlite", database, doc.allowlist(SCHEMA), folder / "audit.jsonl", SCHEMA)


def run(executor, question: str, source: str = "test"):
    """Mini için kurulmuş sahte istemci, mini bağlamıyla, gerçek döngüde."""
    return run_agent(
        question,
        cli.make_client("fake", "rag", DATASET),
        executor,
        SCHEMA,
        source,
        mode="rag",
        context=CONTEXT,
    )


def tools_of(result):
    return [step.tool for step in result.steps]


# ------------------------------------------------------------------ referans tarih bağlamdan gelir


@pytest.mark.parametrize("mode", config.MODES)
def test_the_contexts_date_is_the_date_every_prompt_shows(mode):
    ctx = modes.ToolContext(executor=None, schema=SCHEMA, rules=RULES, mode=mode, as_of=AS_OF)
    text = modes.get_mode(mode).system_prompt(ctx)
    assert f"Referans tarih: {AS_OF}" in text, mode
    assert config.AS_OF not in text, f"{mode} hâlâ config.AS_OF'i okuyor"


def test_a_context_without_a_date_keeps_the_configured_one():
    ctx = modes.ToolContext(executor=None, schema=SCHEMA)
    assert ctx.as_of == config.AS_OF
    assert config.AS_OF in modes.get_mode("full").system_prompt(ctx)


# ------------------------------------------------------------------ sahte istemci kümenin kaydını oynatır


@pytest.mark.parametrize("line", GOLDEN, ids=lambda line: line["id"])
def test_a_dataset_question_replays_its_own_golden_sql(executor, line):
    result = run(executor, line["question"], line["id"])
    assert result.status == "submitted", result.stop_reason
    assert result.submitted_sql == line["sql"]
    assert all(step.ok for step in result.steps), [
        step.summary for step in result.steps if not step.ok
    ]


def test_the_rag_path_walks_the_datasets_index_before_submitting(executor):
    """Araç cevapları mini'nin indeksinden geliyor: Run 1 şemasının tek bir tablo adı bile geçmez."""
    line = BY_ID["Q03"]
    result = run(executor, line["question"], line["id"])
    assert tools_of(result) == [
        "search_schema",
        "get_table_details",
        "find_join_path",
        "run_sql",
        "submit_sql",
    ]
    details = result.steps[1].summary
    assert "Sales.OrderLines — " in details and "TBLSTSABIT" not in details


def test_a_question_outside_the_dataset_gets_the_datasets_own_fallback(executor):
    result = run(executor, "Depolar hakkında ne biliyorsun?")
    assert result.status == "submitted", result.stop_reason
    assert result.submitted_sql == DATASET.fake_fallback_sql
    assert "TBLSTSABIT" not in DATASET.fake_fallback_sql, "yedek sorgu başka bir kümenin tablosu"


# ------------------------------------------------------------------ auto tahmini de aynı tarihi ölçer


def test_resolve_auto_estimates_with_the_date_the_model_will_read(tmp_path, monkeypatch):
    seen = []
    real = prompt.full_rules_prompt

    def spy(as_of, schema, rules):
        seen.append(as_of)
        return real(as_of, schema, rules)

    monkeypatch.setattr(prompt, "full_rules_prompt", spy)
    mode, estimate = cli.resolve_auto(SCHEMA, RULES, tmp_path / "yok", as_of=AS_OF)

    assert seen == [AS_OF]
    assert estimate == doc.estimate_tokens(real(AS_OF, SCHEMA, RULES))
    assert mode == "full_rules", "mini'nin tam kurallı istemi küçük; bütçeye sığmalı"
