"""`sample_values` aracının cevabı ve nerede durduğu (T60).

İki iddia var: cevap kolondaki gerçek farklı değerler (executor ve veritabanı gerçek, yani
örnekler uydurma değil) ve uydurmanın önüne kimin geçtiği — kolon adı şemada yoksa araç
veritabanına hiç gitmez, tablo adı ise policy'ye kadar gider, dolayısıyla reddi denetim
izine düşer. Uğramayan bir çağrının iz bırakmaması, iz bırakanın ise `policy` olması
ikisinin ayrıldığı yerdir.
"""

import json
import sqlite3

import pytest

from nl2sql import config
from nl2sql.agent import modes, tools
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Result
from nl2sql.schema_map import build, doc

SCHEMA = doc.load_schema()


def build_db(tmp):
    path = tmp / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return build_db(tmp_path_factory.mktemp("sample-values"))


@pytest.fixture
def world(db, tmp_path):
    """Araç çağrısı ve o çağrının yazdığı denetim dosyası; her test kendi boş denetimini görür."""
    audit_path = tmp_path / "audit.jsonl"
    executor = LocalExecutor("sqlite", db, doc.allowlist(SCHEMA), audit_path)
    ctx = modes.ToolContext(executor=executor, schema=SCHEMA, mode="rag")
    return ctx, audit_path


def sample(ctx, table, column):
    return tools.dispatch("sample_values", {"table": table, "column": column}, ctx)


def entries(audit_path):
    if not audit_path.exists():
        return []
    text = audit_path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def distinct(db, table, column):
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(
            f"SELECT DISTINCT [{column}] FROM [{table}] WHERE [{column}] IS NOT NULL ORDER BY [{column}]"
        ).fetchall()
    finally:
        conn.close()
    return [row[0] for row in rows]


# ------------------------------------------------------------------ the answer

def test_the_answer_lists_the_distinct_non_null_values_of_the_column(db, world):
    ctx, _ = world
    answer = sample(ctx, "TBLCARISUBE", "IL")
    header, _, tail = answer.partition(": ")
    assert header.startswith("Değerler (")
    values = tail.split(", ")
    assert header == f"Değerler ({len(values)})"
    assert values == distinct(db, "TBLCARISUBE", "IL")
    assert "NULL" not in values


def test_the_number_of_values_never_exceeds_the_budget(db, world):
    ctx, _ = world
    answer = sample(ctx, "TBLCARISUBE", "IL")
    assert len(answer.partition(": ")[2].split(", ")) <= config.SAMPLE_VALUES_N
    assert len(distinct(db, "TBLCARISUBE", "IL")) > 1


def test_a_column_without_values_says_so(world):
    ctx, _ = world

    class Empty:
        def execute(self, sql, budget=None, source=""):
            assert budget.max_rows == config.SAMPLE_VALUES_N
            return Result(columns=["IL"])

    ctx = modes.ToolContext(executor=Empty(), schema=ctx.schema, mode="rag")
    assert sample(ctx, "TBLCARISUBE", "IL") == "Değer yok."


# ------------------------------------------------------------------ where a bad call stops


def test_a_system_table_is_refused_by_the_policy_and_audited(world):
    ctx, audit_path = world
    answer = sample(ctx, "sys.objects", "name")
    assert answer.startswith(f"{tools.ERROR_PREFIX} (policy): ")
    assert [entry["outcome"] for entry in entries(audit_path)] == ["policy"]


def test_a_table_the_schema_does_not_have_is_refused_by_the_policy_and_audited(world):
    ctx, audit_path = world
    answer = sample(ctx, "TBLYOK", "IL")
    assert answer.startswith(f"{tools.ERROR_PREFIX} (policy): ")
    recorded = entries(audit_path)
    assert [entry["outcome"] for entry in recorded] == ["policy"]
    assert "TBLYOK" in recorded[0]["sql"]


def test_a_column_the_table_does_not_have_stops_before_the_database(world):
    ctx, audit_path = world
    assert sample(ctx, "TBLCARISUBE", "OLMAYAN_KOLON").startswith(f"{tools.ERROR_PREFIX}: ")
    assert entries(audit_path) == []


def test_a_column_carrying_sql_is_rejected_before_any_sql_is_built(world):
    ctx, audit_path = world
    answer = sample(ctx, "TBLCARISUBE", "IL; DROP TABLE TBLCARISUBE")
    assert answer.startswith(f"{tools.ERROR_PREFIX}: ")
    assert "DROP" in answer
    assert entries(audit_path) == []


def test_a_missing_argument_is_answered_not_executed(world):
    ctx, audit_path = world
    assert sample(ctx, "TBLCARISUBE", "").startswith(f"{tools.ERROR_PREFIX}: ")
    assert entries(audit_path) == []
