# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Nitelikli adlar iki fiziksel hedefte de kurulabilir olmalı (PLAN R4-6).

SQLite'ta nokta şema ayracıdır: `"Sales"."Orders"` iki parçalı bir ad sayılır, oysa dosyada
tablonun tek adı `Sales.Orders`. Çeviri adımı o iki parçayı tek kimliğe indirir; politikanın
verdiği SQL T-SQL olarak kalır, yani indirme yalnız SQLite yolunda olur. T-SQL betiği ise
şemayı kendisi kurar: her şema bir kez `CREATE SCHEMA`, adlar köşeli parantezle. Üç yeni tip
eşlemesi de (BIT, DATETIME2, VARBINARY) aynı yoldan geçiyor: SQLite'ta değer bozulmadan
durmalı, betikte okunabilir yazılmalı.
"""

import pytest
from sqlglot import exp, parse

from nl2sql.engine.executor import LocalExecutor
from nl2sql.schema_map import build, doc

SCHEMA = {
    "tables": [
        {
            "name": "Sales.Orders",
            "description": "satış siparişleri",
            "module": "Satış",
            "columns": [
                {"name": "OrderID", "type": "INT", "nullable": False},
                {"name": "CustomerID", "type": "INT", "nullable": False},
                {"name": "OrderDate", "type": "DATETIME2", "nullable": False},
                {"name": "Paid", "type": "DECIMAL(18,2)", "nullable": False},
                {"name": "Active", "type": "BIT", "nullable": False},
                {"name": "RowVersion", "type": "VARBINARY", "nullable": True},
            ],
        },
        {
            "name": "Sales.Customers",
            "description": "cari kartlar",
            "module": "Satış",
            "columns": [
                {"name": "CustomerID", "type": "INT", "nullable": False},
                {"name": "Name", "type": "NVARCHAR(50)", "nullable": False},
            ],
        },
        {
            "name": "Purchasing.PurchaseOrders",
            "description": "satın alma siparişleri",
            "module": "Satın Alma",
            "columns": [
                {"name": "PurchaseOrderID", "type": "INT", "nullable": False},
                {"name": "Active", "type": "BIT", "nullable": False},
            ],
        },
    ]
}

DATASET = {
    "Sales.Orders": [
        {
            "OrderID": 1,
            "CustomerID": 10,
            "OrderDate": "2026-09-05 10:30:00",
            "Paid": 1250.5,
            "Active": 1,
            "RowVersion": b"\xde\xad",
        },
        {
            "OrderID": 2,
            "CustomerID": 20,
            "OrderDate": "2026-10-01 08:00:00",
            "Paid": 99.9,
            "Active": 0,
            "RowVersion": None,
        },
    ],
    "Sales.Customers": [
        {"CustomerID": 10, "Name": "Şok Market"},
        {"CustomerID": 20, "Name": "Başak Gıda"},
    ],
    "Purchasing.PurchaseOrders": [{"PurchaseOrderID": 500, "Active": 1}],
}

JOINED = [(1, "Şok Market"), (2, "Başak Gıda")]

# Aynı sorgunun üç yazımı: politika çıplak adı da köşeli parantezi de tam ada çevirir,
# SQLite yolunda üçünün de aynı satırları vermesi gerekir.
SPELLINGS = {
    "nitelikli": "SELECT o.OrderID, c.Name FROM Sales.Orders o "
    "JOIN Sales.Customers c ON c.CustomerID = o.CustomerID ORDER BY o.OrderID",
    "çıplak": "SELECT o.OrderID, c.Name FROM Orders o "
    "JOIN Customers c ON c.CustomerID = o.CustomerID ORDER BY o.OrderID",
    "köşeli": "SELECT o.OrderID, c.Name FROM [Sales].[Orders] o "
    "JOIN [Sales].[Customers] c ON c.CustomerID = o.CustomerID ORDER BY o.OrderID",
}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Elle kurulmuş şemalı dünya: SQLite dosyası ve T-SQL betiğinin metni."""
    folder = tmp_path_factory.mktemp("qualified")
    database, script = folder / "test.db", folder / "test.sql"
    build.write_sqlite(DATASET, SCHEMA, database)
    build.write_mssql_script(DATASET, SCHEMA, script)
    return database, script.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def executor(world, tmp_path_factory):
    database, _ = world
    audit = tmp_path_factory.mktemp("qualified-audit") / "audit.jsonl"
    return LocalExecutor("sqlite", database, doc.allowlist(SCHEMA), audit)


@pytest.fixture(scope="module")
def script(world):
    return world[1]


def run(executor, sql):
    result = executor.execute(sql, source="ask")
    assert result.error is None, f"sorgu çalışmadı: {result.error}"
    return result.rows


def statements_of(script):
    """GO ile ayrılmış ifadeler; açıklama satırları düşürülür."""
    bodies = []
    for chunk in script.split("\nGO\n\n"):
        body = "\n".join(line for line in chunk.splitlines() if not line.startswith("--")).strip()
        if body:
            bodies.append(body)
    return bodies


def created(script):
    """CREATE ifadelerinin sırasıyla tür ve adları: ("SCHEMA", "Sales"), ("TABLE", "Sales.Orders")."""
    items = []
    for statement in statements_of(script):
        tree = parse(statement, read="tsql")[0]
        if not isinstance(tree, exp.Create):
            continue
        if tree.args["kind"] == "SCHEMA":
            items.append(("SCHEMA", tree.this.db))
        else:
            table = tree.this.this
            full = f"{table.db}.{table.name}" if table.db else table.name
            items.append(("TABLE", full))
    return items


# ----------------------------------------------------------------- sqlite: üç yazım, aynı cevap


@pytest.mark.parametrize("spelling", sorted(SPELLINGS))
def test_the_same_join_answers_whatever_the_spelling(executor, spelling):
    assert run(executor, SPELLINGS[spelling]) == JOINED


def test_a_three_part_column_prefix_reads_the_same_table(executor):
    sql = (
        "SELECT Sales.Orders.OrderID, Sales.Orders.Paid FROM Sales.Orders "
        "WHERE Sales.Orders.Active = 1 ORDER BY Sales.Orders.OrderID"
    )
    assert run(executor, sql) == [(1, 1250.5)]


def test_a_cte_over_a_qualified_table_still_answers(executor):
    sql = (
        "WITH Orders AS (SELECT CustomerID, Paid FROM Sales.Orders WHERE Active = 1) "
        "SELECT c.Name, o.Paid FROM Orders o JOIN Sales.Customers c ON c.CustomerID = o.CustomerID"
    )
    assert run(executor, sql) == [("Şok Market", 1250.5)]


# ----------------------------------------------------------------- sqlite: yeni tipler


def test_bit_datetime2_and_varbinary_values_survive_the_round_trip(executor):
    rows = run(executor, "SELECT OrderID, OrderDate, Active, RowVersion FROM Sales.Orders ORDER BY OrderID")
    assert rows == [
        (1, "2026-09-05 10:30:00", 1, b"\xde\xad"),
        (2, "2026-10-01 08:00:00", 0, None),
    ]


def test_a_half_open_range_still_filters_a_datetime2_column(executor):
    sql = (
        "SELECT OrderID FROM Sales.Orders "
        "WHERE OrderDate >= '2026-09-01' AND OrderDate < '2026-10-01' ORDER BY OrderID"
    )
    assert run(executor, sql) == [(1,)]


# ----------------------------------------------------------------- t-sql script


def test_every_statement_parses_as_one_tsql_statement(script):
    for statement in statements_of(script):
        trees = parse(statement, read="tsql")
        assert len(trees) == 1 and trees[0] is not None, statement[:80]


def test_each_schema_is_created_once_before_the_tables(script):
    assert created(script) == [
        ("SCHEMA", "Sales"),
        ("SCHEMA", "Purchasing"),
        ("TABLE", "Sales.Orders"),
        ("TABLE", "Sales.Customers"),
        ("TABLE", "Purchasing.PurchaseOrders"),
    ]


def test_qualified_names_are_bracketed_in_create_and_insert(script):
    assert "CREATE TABLE [Sales].[Orders]" in script
    assert "INSERT INTO [Purchasing].[PurchaseOrders] (PurchaseOrderID, Active) VALUES" in script


def test_bytes_are_written_as_hex_literals(script):
    assert "0xdead" in script


def test_a_bare_name_and_dbo_stay_as_they_are_today(tmp_path):
    schema = {
        "tables": [
            {"name": "TBLSTHAR", "columns": [{"name": "STHAR_GCMIK", "type": "INT", "nullable": True}]},
            {"name": "dbo.TBLCASABIT", "columns": [{"name": "CARI_KOD", "type": "VARCHAR(10)", "nullable": True}]},
        ]
    }
    path = tmp_path / "dbo.sql"
    build.write_mssql_script({"TBLSTHAR": [], "dbo.TBLCASABIT": []}, schema, path)
    script = path.read_text(encoding="utf-8")
    assert "CREATE SCHEMA" not in script
    assert "CREATE TABLE TBLSTHAR" in script and "CREATE TABLE [dbo].[TBLCASABIT]" in script
