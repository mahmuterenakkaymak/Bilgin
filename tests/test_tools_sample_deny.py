# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T159: bir `deny` kolon adı sample_values üzerinden modele sızmıyor (PLAN R4-7).

`_column_names` tablonun tüm kolonlarını döndürdüğü için yanlış bir kolon sorulduğunda cevap
"Kolonlar: ..., HashedPassword, Photo." diyerek sırrı adıyla sayıyordu. Artık denetim de liste de
`deny` kolonları atlıyor: kapalı kolon adıyla sorulursa bilinmeyen kolon gibi cevaplanıyor, hiçbir
model metninde adıyla geçmiyor. Test gerçek wwi şeması + kurulu SQLite + gerçek LocalExecutor
üzerinden üç aracı da (get_table_details, get_schema, sample_values) yokluyor; `deny` kolonu olmayan
bir tablo ise tüm kolonlarını listelemeye devam ediyor.
"""

import pytest

from bilgin.agent import modes, tools
from bilgin.datasets import load_dataset
from bilgin.engine.executor import LocalExecutor
from bilgin.schema_map import doc

DATASET = load_dataset("wwi")
SCHEMA = DATASET.schema()
TABLES = {table["name"]: table for table in SCHEMA["tables"]}
DENY = {
    column["name"]
    for table in SCHEMA["tables"]
    for column in table["columns"]
    if column.get("deny")
}
PEOPLE = "Application.People"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("sample-deny") / "wwi.db"
    DATASET.build_db(db_path=path, sql_path=path.with_suffix(".sql"))
    return path


@pytest.fixture
def ctx(db, tmp_path):
    executor = LocalExecutor("sqlite", db, doc.allowlist(SCHEMA), tmp_path / "audit.jsonl", SCHEMA)
    return modes.ToolContext(executor=executor, schema=SCHEMA, mode="rag")


def call(ctx, tool, args):
    return tools.dispatch(tool, args, ctx)


# ------------------------------------------------------- the missing-column listing stays clean


def test_a_missing_column_of_people_lists_readable_columns_only(ctx):
    answer = call(ctx, "sample_values", {"table": PEOPLE, "column": "OLMAYAN_KOLON"})
    assert answer.startswith(f"{tools.ERROR_PREFIX}: ")
    assert "FullName" in answer
    assert "HashedPassword" not in answer
    assert "Photo" not in answer


@pytest.mark.parametrize("secret", sorted(DENY))
def test_a_denied_column_by_name_is_refused_and_returns_no_value(ctx, secret):
    answer = call(ctx, "sample_values", {"table": PEOPLE, "column": secret})
    assert not tools.answer_is_ok(answer)
    assert "Değerler" not in answer


# ------------------------------------------------------- no model-facing text names a deny column


def test_get_table_details_names_no_denied_column_for_any_table(ctx):
    for name in TABLES:
        assert all(secret not in call(ctx, "get_table_details", {"tables": [name]}) for secret in DENY)


def test_get_schema_names_no_denied_column_for_any_table(ctx):
    for name in TABLES:
        assert all(secret not in call(ctx, "get_schema", {"tables": [name]}) for secret in DENY)


def test_sample_values_names_no_denied_column_for_any_table(ctx):
    # Yanlış bir kolon sorulunca cevap o tablonun kolonlarını sayıyor; sırrın orada olmaması iddia.
    for name in TABLES:
        answer = call(ctx, "sample_values", {"table": name, "column": "OLMAYAN_KOLON_9999"})
        assert all(secret not in answer for secret in DENY), name


# ------------------------------------------------------- a table without deny columns is intact


def test_a_table_without_deny_columns_still_lists_all_its_columns(ctx):
    name = next(n for n, table in TABLES.items() if not any(c.get("deny") for c in table["columns"]))
    answer = call(ctx, "sample_values", {"table": name, "column": "OLMAYAN_KOLON_9999"})
    for column in TABLES[name]["columns"]:
        assert column["name"] in answer, column["name"]
