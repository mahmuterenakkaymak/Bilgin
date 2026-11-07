# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Nitelikli tablo adları (PLAN R4-5): allowlist `Schema.Table` da yazılabilir.

İki parça şema ile ayrılır ve tam adın büyük hali allowlistteyse geçerlidir; üçüncü bir parça
veritabanı ya da sunucu demek olduğu için sınırı aşar. Çıplak ad allowlistte yoksa tek bir
`Schema.Ad`'e çözülür ve ağaç o ada yeniden yazılır ki SQL Server da şemayı görsün; iki aday
varsa politika tahmin etmez, sorar. Nedenler hep tam ad taşır: model hangi tablonun
kastedildiğini görüp SQL'i tek adımda düzeltebilsin.
"""

import pytest

from bilgin import config
from bilgin.policy import policy

ALLOWED = {"SALES.ORDERS", "SALES.CUSTOMERS", "PURCHASING.PURCHASEORDERS", "WAREHOUSE.STOCKITEMS"}
PII = {("SALES.ORDERS", "TCKN"): "tckn"}


def check(sql, top_n=config.TOP_N, pii=None):
    return policy.check(sql, ALLOWED, top_n, pii)


# ----------------------------------------------------------------- what is allowed


def test_a_qualified_join_passes_and_reports_full_names():
    sql = (
        "SELECT o.OrderID, c.Name FROM Sales.Orders o "
        "JOIN Sales.Customers c ON c.CustomerID = o.CustomerID"
    )
    result = check(sql)
    assert result.ok, result.reason
    assert result.tables == {"SALES.ORDERS", "SALES.CUSTOMERS"}


def test_brackets_and_case_are_only_spelling():
    result = check("select top 5 [OrderID] from [Sales].[Orders]")
    assert result.ok, result.reason
    assert result.tables == {"SALES.ORDERS"}
    assert "[Sales].[Orders]" in result.sql


def test_a_bare_unique_name_is_rewritten_to_its_qualified_name():
    result = check("SELECT OrderID FROM Orders", 250)
    assert result.ok, result.reason
    assert result.tables == {"SALES.ORDERS"}
    assert result.sql == "SELECT TOP 250 OrderID FROM SALES.Orders"


def test_a_bare_allowlisted_name_is_left_alone():
    result = policy.check("SELECT STOK_KODU FROM TBLSTHAR", {"TBLSTHAR"}, config.TOP_N)
    assert result.ok, result.reason
    assert result.tables == {"TBLSTHAR"} and result.sql.endswith("FROM TBLSTHAR")


# ----------------------------------------------------------------- what stays closed


@pytest.mark.parametrize(
    "sql,expected",
    [
        ("SELECT * FROM Website.Customers", "İzin verilmeyen tablo: WEBSITE.CUSTOMERS"),
        ("SELECT * FROM [Application].[People]", "İzin verilmeyen tablo: APPLICATION.PEOPLE"),
        ("SELECT * FROM WideWorldImporters.Sales.Orders", "Tablo adı"),
        ("SELECT * FROM SRV.WideWorldImporters.Sales.Orders", "Tablo adı"),
        ("SELECT OrderID FROM Sales.Orders o JOIN Application.People p ON 1=1", "İzin verilmeyen tablo"),
    ],
)
def test_another_schema_database_or_server_is_never_readable(sql, expected):
    result = check(sql)
    assert not result.ok and result.sql is None
    assert expected in result.reason, result.reason
    assert "veritabanı" in result.reason


@pytest.mark.parametrize(
    "sql",
    ["SELECT * FROM sys.objects", "SELECT * FROM INFORMATION_SCHEMA.TABLES"],
)
def test_the_system_catalog_stays_closed_under_a_qualified_name(sql):
    result = check(sql)
    assert not result.ok and "Sistem kataloğu" in result.reason


def test_a_bare_name_with_no_match_keeps_the_plain_denial():
    assert check("SELECT * FROM TBLGECKMIS").reason == "İzin verilmeyen tablo: TBLGECKMIS."


def test_an_ambiguous_bare_name_is_rejected_not_guessed():
    result = policy.check("SELECT * FROM Orders", ALLOWED | {"PURCHASING.ORDERS"}, config.TOP_N)
    assert not result.ok and result.sql is None
    assert result.reason == "Belirsiz tablo adı: ORDERS (PURCHASING.ORDERS, SALES.ORDERS); şemasıyla yazın."


# ----------------------------------------------------------------- CTEs over qualified names


def test_a_cte_named_like_a_table_still_checks_the_real_one():
    result = check("WITH Orders AS (SELECT OrderID FROM Sales.Orders) SELECT * FROM Orders")
    assert result.ok, result.reason
    assert result.tables == {"SALES.ORDERS"}


def test_a_cte_name_cannot_hide_a_forbidden_table_behind_a_bare_name():
    result = check("WITH Orders AS (SELECT object_id AS OrderID FROM sys.objects) SELECT * FROM Orders")
    assert not result.ok and "Sistem kataloğu" in result.reason


# ----------------------------------------------------------------- row cap


def test_top_is_still_injected_on_the_outermost_select():
    result = check("SELECT OrderID FROM Orders", 250)
    assert result.ok and result.sql.startswith("SELECT TOP 250 ")


def test_a_top_level_union_of_qualified_tables_is_still_wrapped():
    sql = "SELECT OrderID FROM Sales.Orders UNION SELECT CustomerID FROM Sales.Customers"
    result = check(sql, 100)
    assert result.ok and result.sql.startswith("SELECT TOP 100 * FROM (") and result.sql.endswith(") AS _q")


# ----------------------------------------------------------------- pii map speaks full names


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT OrderID FROM Sales.Orders WHERE TCKN LIKE '1%'",
        "SELECT o.OrderID FROM Sales.Orders o JOIN Sales.Customers c ON c.CustomerID = o.CustomerID "
        "WHERE o.TCKN LIKE '1%'",
        "SELECT OrderID FROM Orders WHERE TCKN LIKE '1%'",
    ],
)
def test_a_pii_filter_on_a_qualified_table_is_named_by_its_full_name(sql):
    result = check(sql, config.TOP_N, PII)
    assert not result.ok and result.reason == "Filtrede PII kolon: SALES.ORDERS.TCKN."
