# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""`sample_values` tabloyu şemanın parçalarıyla yazar (T156, PLAN R4-5).

İki iddia var: modele giden SQL SQL Server'ın okuyabileceği bir ad taşıyor — `[Sales].[Customers]`,
`[Sales.Customers]` değil — ve çıplak ad önce şemada çözüldüğü için kolon denetimi nitelikli
tabloda yapılıyor. Kaydedici executor ne gönderildiğini, mini kümenin gerçek SQLite'ı cevabın
gerçekten çalıştığını söyler. Şemada olmayan sentetik tablo eski yolunda kalıyor: orada sözü
hâlâ policy söylüyor, yani red denetim izine düşüyor.
"""

from pathlib import Path

import pytest
from sqlglot import exp, parse

from bilgin.agent import modes, tools
from bilgin.datasets import load_dataset
from bilgin.engine.executor import LocalExecutor
from bilgin.engine.result import Result
from bilgin.schema_map import doc

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
DATASET = load_dataset("mini", root=FIXTURE_ROOT)
SCHEMA = DATASET.schema()


class Recording:
    """Çalıştırmaz, gönderdiği sorguyu tutar; böylece sorgunun kendisi iddia edilebiliyor."""

    def __init__(self):
        self.sqls = []

    def execute(self, sql, budget=None, source=""):
        self.sqls.append(sql)
        return Result(columns=["Deger"], rows=[("A",)])


def sample(executor, table, column, schema=SCHEMA):
    ctx = modes.ToolContext(executor=executor, schema=schema, mode="rag")
    return tools.dispatch("sample_values", {"table": table, "column": column}, ctx)


@pytest.fixture
def rec():
    return Recording()


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    """Kümenin kendi builder'ının kurduğu SQLite; cevap bu kapıdan geçiyor."""
    folder = tmp_path_factory.mktemp("sample-qualified")
    database = folder / "mini.db"
    DATASET.build_db(db_path=database, sql_path=folder / "mini.sql")
    return LocalExecutor("sqlite", database, doc.allowlist(SCHEMA), folder / "audit.jsonl", SCHEMA)


# ------------------------------------------------------------------ the SQL that leaves the tool


@pytest.mark.parametrize("asked", ["Sales.Customers", "Customers"])
def test_the_table_leaves_the_tool_split_into_its_own_schema(rec, asked):
    sample(rec, asked, "City")
    assert len(rec.sqls) == 1
    tree = parse(rec.sqls[0], read="tsql")[0]
    assert [(table.db, table.name) for table in tree.find_all(exp.Table)] == [("Sales", "Customers")]
    dotted = [id.name for id in tree.find_all(exp.Identifier) if "." in id.name]
    assert dotted == [], rec.sqls[0]


def test_a_bare_table_the_schema_does_not_have_is_written_as_it_was(rec):
    sample(rec, "TBLSTSABIT", "KOD")
    assert "FROM [TBLSTSABIT]" in rec.sqls[0]


# ------------------------------------------------------------------ the column check follows


def test_an_unknown_column_of_the_bare_name_stops_before_the_database(rec):
    answer = sample(rec, "Customers", "OLMAYAN_KOLON")
    assert answer.startswith(f"{tools.ERROR_PREFIX}: ")
    assert "OLMAYAN_KOLON kolonu Sales.Customers tablosunda yok." in answer
    assert "CustomerID, CustomerName, City, PhoneNumber" in answer
    assert rec.sqls == []


def test_an_ambiguous_bare_name_asks_for_the_schema_without_executing(rec):
    two = {"tables": [dict(t) for t in SCHEMA["tables"]]}
    two["tables"].append({"name": "Warehouse.Customers", "module": "Warehouse", "columns": []})
    answer = sample(rec, "Customers", "City", schema=two)
    assert answer.startswith(f"{tools.ERROR_PREFIX}: Belirsiz tablo adı: Customers (")
    assert rec.sqls == []


# ------------------------------------------------------------------ and it still runs


def test_the_built_database_answers_a_qualified_table(executor):
    assert sample(executor, "Sales.Orders", "OrderDate").startswith("Değerler (")
