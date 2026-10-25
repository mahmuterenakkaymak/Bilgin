"""COUNT(*) under column DENY (2026-10-25, found on the restored WideWorldImporters).

The read-only login DENYs every `pii`/`deny` column, and SQL Server then refuses `COUNT(*)` and
`COUNT(1)` on that table. The policy rewrites them to `COUNT(<FROM table>.<first NOT NULL unmarked
column>)`, which counts the same rows; tables without marked columns, `COUNT(DISTINCT ...)` and SELECTs
with a RIGHT/FULL join are left alone. The rewritten SQL must still count the same rows on SQLite.
"""

import sqlite3

from nl2sql.policy import pii, policy

SCHEMA = {
    "tables": [
        {"name": "Sales.Customers", "columns": [
            {"name": "CustomerID", "nullable": False},
            {"name": "CustomerName", "nullable": False},
            {"name": "PhoneNumber", "nullable": False, "pii": "phone"},
        ]},
        {"name": "Sales.Orders", "columns": [
            {"name": "OrderID", "nullable": False},
            {"name": "CustomerID", "nullable": False},
        ]},
        {"name": "Application.People", "columns": [
            {"name": "FullName", "nullable": False, "pii": "person_name"},
            {"name": "PersonID", "nullable": False},
            {"name": "Photo", "nullable": True, "deny": True},
        ]},
    ]
}
ALLOW = {"Sales.Customers", "Sales.Orders", "Application.People"}


def check(sql):
    verdict = policy.check(sql, ALLOW, 1000, pii=pii.column_map(SCHEMA), deny=pii.deny_set(SCHEMA),
                           keys=pii.count_keys(SCHEMA))
    assert verdict.ok, verdict.reason
    return verdict.sql


def test_count_keys_skip_marked_columns():
    assert pii.count_keys(SCHEMA) == {"SALES.CUSTOMERS": "CustomerID", "SALES.ORDERS": "OrderID",
                                      "APPLICATION.PEOPLE": "PersonID"}


def test_count_star_on_a_closed_table_counts_its_key():
    assert "COUNT(c.CustomerID)" in check("SELECT COUNT(*) FROM Sales.Customers c")
    assert "COUNT(CustomerID)" in check("SELECT COUNT(1) FROM Sales.Customers")
    assert "COUNT(p.PersonID)" in check("SELECT COUNT(*) AS n FROM Application.People p")


def test_a_join_with_a_closed_table_counts_the_from_key():
    sql = check("SELECT COUNT(*) FROM Sales.Orders o JOIN Sales.Customers c ON c.CustomerID = o.CustomerID")
    assert "COUNT(o.OrderID)" in sql
    sql = check("SELECT c.CustomerName, COUNT(*) FROM Sales.Customers c LEFT JOIN Sales.Orders o "
                "ON o.CustomerID = c.CustomerID GROUP BY c.CustomerName")
    assert "COUNT(c.CustomerID)" in sql


def test_open_tables_distinct_and_outer_joins_stay():
    assert "COUNT(*)" in check("SELECT COUNT(*) FROM Sales.Orders o")
    assert "COUNT(DISTINCT c.CustomerID)" in check("SELECT COUNT(DISTINCT c.CustomerID) FROM Sales.Customers c")
    sql = check("SELECT COUNT(*) FROM Sales.Orders o RIGHT JOIN Sales.Customers c ON c.CustomerID = o.CustomerID")
    assert "COUNT(*)" in sql


def test_a_subquery_count_uses_its_own_from():
    sql = check("SELECT COUNT(*) FROM Sales.Orders o WHERE 0 < (SELECT COUNT(*) FROM Sales.Customers c "
                "WHERE c.CustomerID = o.CustomerID)")
    # The inner SELECT reads the closed table; the outer one reads only Orders and keeps COUNT(*).
    assert "COUNT(c.CustomerID)" in sql and sql.startswith("SELECT TOP 1000 COUNT(*)")


def test_no_keys_means_no_rewrite():
    verdict = policy.check("SELECT COUNT(*) FROM Sales.Customers c", ALLOW, 1000, pii=pii.column_map(SCHEMA))
    assert verdict.ok and "COUNT(*)" in verdict.sql


def test_the_rewrite_counts_the_same_rows():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE Customers (CustomerID INT NOT NULL, CustomerName TEXT, PhoneNumber TEXT)")
    conn.executemany("INSERT INTO Customers VALUES (?, ?, ?)", [(i, f"c{i}", None) for i in range(1, 8)])
    rewritten = check("SELECT COUNT(*) FROM Sales.Customers c").replace("Sales.", "").replace("TOP 1000 ", "")
    assert conn.execute(rewritten).fetchone()[0] == conn.execute("SELECT COUNT(*) FROM Customers").fetchone()[0] == 7
