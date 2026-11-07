# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T129: mini fixture veri kümesi (PLAN R4-9 dosya düzeni, M11 entegrasyonu).

Küme ``tests/fixtures/datasets/mini/`` klasöründe durur ve ``load_dataset``'ın kök parametresiyle
okunur; config'in yollarına dokunulmaz. Dört şey birlikte sınanır: klasör bir veri kümesine
dönüyor, üretilen satırların anahtarları şema kolonlarıyla sırayla aynı, foreign key'ler
``doc.split_fk`` ile gerçek bir kolona çıkıyor ve kurulan SQLite dosyasından geçen her golden SQL
kendi Python doğrusunu veriyor (COMPARE bütçesi, iki ondalık).
"""

import re
from collections import Counter
from pathlib import Path

import pytest

from bilgin import config
from bilgin.datasets import load_dataset
from bilgin.engine.executor import LocalExecutor
from bilgin.eval.runner import COMPARE
from bilgin.graph import profile
from bilgin.policy import policy
from bilgin.schema_map import doc

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
DATASET = load_dataset("mini", root=FIXTURE_ROOT)
SCHEMA = DATASET.schema()
ROWS = DATASET.generate()
GOLDEN = DATASET.golden()
FOREIGN_KEYS = {
    f"{table['name']}.{column['name']}": column["fk"]
    for table in SCHEMA["tables"]
    for column in table["columns"]
    if column["fk"]
}


def grid(rows: list[tuple]) -> list[tuple]:
    """Satırlar iki ondalıkta karşılaşır: toplama sırası float'ın son basamağını oynatabiliyor."""
    return [
        tuple(round(value, 2) if isinstance(value, float) else value for value in row) for row in rows
    ]


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    """Kümenin kendi builder'ının kurduğu dosya üzerinden geçen gerçek kapı."""
    folder = tmp_path_factory.mktemp("mini-dataset")
    database, script = folder / "mini.db", folder / "mini.sql"
    DATASET.build_db(db_path=database, sql_path=script)
    assert script.stat().st_size, "T-SQL betiği yazılmadı"
    return LocalExecutor("sqlite", database, doc.allowlist(SCHEMA), folder / "audit.jsonl", SCHEMA)


# ------------------------------------------------------------------ the folder is a dataset


def test_the_folder_loads_as_a_dataset():
    assert DATASET.name == "mini"
    assert DATASET.root == FIXTURE_ROOT / "mini"
    assert DATASET.default_schema is None
    assert DATASET.as_of == "2016-05-31"
    assert DATASET.seed == 42
    assert DATASET.traps_path is None
    assert DATASET.builder_ref == "builder.py:build_db"
    assert DATASET.generator_ref == "builder.py:generate"
    assert DATASET.references_ref == "reference.py:REFERENCES"
    assert DATASET.db_path == config.ROOT / "data" / "mini.db"
    assert DATASET.mssql_script == config.ROOT / "db" / "mssql" / "build_mini.sql"
    assert DATASET.index_dir == config.ROOT / "index" / "mini"
    assert DATASET.eval_out == config.ROOT / "eval_out" / "mini"


def test_row_keys_are_the_schema_columns_in_order():
    for table in SCHEMA["tables"]:
        names = [column["name"] for column in table["columns"]]
        assert ROWS[table["name"]], f"{table['name']} boş kaldı"
        for row in ROWS[table["name"]]:
            assert list(row) == names, table["name"]


def test_every_foreign_key_resolves_to_a_real_column():
    columns = {table["name"]: [column["name"] for column in table["columns"]] for table in SCHEMA["tables"]}
    assert FOREIGN_KEYS == {
        "Sales.Orders.CustomerID": "Sales.Customers.CustomerID",
        "Sales.OrderLines.OrderID": "Sales.Orders.OrderID",
        "Sales.OrderLines.StockItemID": "Warehouse.StockItems.StockItemID",
    }
    for fk in FOREIGN_KEYS.values():
        target, target_column = doc.split_fk(fk)
        assert target in columns, fk
        assert target_column in columns[target], fk


def test_rules_and_profile_load():
    rules = DATASET.rules()
    assert [rule["id"] for rule in rules] == ["ciro"]
    assert rules[0]["tables"] == ["Sales.OrderLines"]
    assert rules[0]["markers"]
    assert profile.load_profile(DATASET.profile_path)


@pytest.mark.parametrize("line", GOLDEN, ids=lambda line: line["id"])
def test_a_cited_rule_marker_hits_the_golden_sql(line):
    markers = {rule["id"]: rule["markers"] for rule in DATASET.rules()}
    for rule_id in line["rules"]:
        for marker in markers[rule_id]:
            assert re.search(marker, line["sql"], re.IGNORECASE), f"{line['id']} -> {rule_id}: {marker}"


@pytest.mark.parametrize("line", GOLDEN, ids=lambda line: line["id"])
def test_the_golden_line_declares_what_its_sql_touches(line):
    verdict = policy.check(line["sql"], doc.allowlist(SCHEMA))
    assert verdict.ok, verdict.reason
    assert {name.upper() for name in line["requires_tables"]} == verdict.tables
    assert ("multi_join" in line["tags"]) == (len(set(line["requires_tables"])) >= 3), line["id"]
    assert ("needs_rule" in line["tags"]) == bool(line["rules"]), line["id"]


# ------------------------------------------------------------------ built db == python truth


@pytest.mark.parametrize("line", GOLDEN, ids=lambda line: line["id"])
def test_every_golden_sql_answers_its_python_reference(executor, line):
    result = executor.execute(line["sql"], COMPARE, line["id"])
    assert result.error is None, f"{line['id']}: {result.error.message}"
    expected = DATASET.references()[line["id"]](ROWS)
    got, want = grid(result.rows), grid(expected)
    if line["ordered"]:
        assert got == want, line["id"]
    else:
        assert Counter(got) == Counter(want), line["id"]
