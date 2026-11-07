# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R4-5: qualified-name helpers — split, resolve and `table_detail` by bare or qualified name."""

import json

import pytest

from nl2sql.schema_map import doc

TABLES = [
    {
        "name": "Sales.Orders",
        "description": "siparişler",
        "module": "Sales",
        "columns": [
            {"name": "OrderID", "type": "INT", "description": "sipariş numarası", "nullable": False},
            {"name": "CustomerID", "type": "INT", "description": "müşteri", "fk": "Sales.Customers.CustomerID"},
            {"name": "StockItemID", "type": "INT", "description": "ürün", "fk": "Warehouse.StockItems.StockItemID"},
            {
                "name": "IsCreditNote",
                "type": "BIT",
                "description": "iade siparişi",
                "values": {"0": "hayır", "1": "evet"},
            },
        ],
    },
    {
        "name": "Purchasing.PurchaseOrders",
        "description": "satın alma siparişleri",
        "module": "Purchasing",
        "columns": [
            {"name": "PurchaseOrderID", "type": "INT", "description": "sipariş numarası", "nullable": False},
            {"name": "SupplierID", "type": "INT", "description": "tedarikçi"},
        ],
    },
    {
        "name": "Warehouse.StockItems",
        "description": "ürünler",
        "module": "Warehouse",
        "columns": [
            {"name": "StockItemID", "type": "INT", "description": "ürün numarası", "nullable": False},
            {"name": "StockItemName", "type": "NVARCHAR(200)", "description": "ürün adı"},
        ],
    },
    {
        "name": "TBLX",
        "description": "şemasız tablo",
        "module": "Genel",
        "columns": [
            {"name": "KOD", "type": "INT", "description": "kod", "nullable": False},
            {"name": "AD", "type": "NVARCHAR(50)", "description": "ad"},
        ],
    },
]

NAMES = [table["name"] for table in TABLES]


def load(tables, folder):
    path = folder / "schema.json"
    path.write_text(json.dumps({"tables": tables}, ensure_ascii=False), encoding="utf-8")
    return doc.load_schema(path)


@pytest.fixture(scope="module")
def schema(tmp_path_factory):
    return load(TABLES, tmp_path_factory.mktemp("qualified"))


# ----------------------------------------------------------------- split helpers


def test_split_name_splits_the_schema_off_the_table():
    assert doc.split_name("Sales.Orders") == ("Sales", "Orders")
    assert doc.split_name("Purchasing.PurchaseOrders") == ("Purchasing", "PurchaseOrders")


def test_split_name_leaves_a_bare_name_without_a_schema():
    assert doc.split_name("TBLSTHAR") == (None, "TBLSTHAR")
    assert doc.split_name(" TBLX ") == (None, "TBLX")


def test_split_fk_splits_the_column_off_the_right():
    assert doc.split_fk("Sales.Orders.CustomerID") == ("Sales.Orders", "CustomerID")
    assert doc.split_fk("Warehouse.StockItems.StockItemID") == ("Warehouse.StockItems", "StockItemID")


def test_split_fk_of_a_two_part_name_keeps_the_bare_table():
    assert doc.split_fk("TBLSTHAR.FISNO") == ("TBLSTHAR", "FISNO")


def test_split_fk_leaves_the_whole_name_as_the_table_of_a_bare_column():
    assert doc.split_fk("FISNO") == ("", "FISNO")


def test_allowlist_is_the_upper_full_names(schema):
    assert doc.allowlist(schema) == {
        "SALES.ORDERS",
        "PURCHASING.PURCHASEORDERS",
        "WAREHOUSE.STOCKITEMS",
        "TBLX",
    }


# ----------------------------------------------------------------- resolution


def test_resolve_table_takes_the_exact_full_name(schema):
    assert doc.resolve_table("Sales.Orders", NAMES) == "Sales.Orders"
    assert doc.resolve_table("sales.orders", NAMES) == "Sales.Orders"
    assert doc.resolve_table(" Sales.Orders ", NAMES) == "Sales.Orders"


def test_resolve_table_finds_the_qualified_table_by_its_bare_name(schema):
    assert doc.resolve_table("Orders", NAMES) == "Sales.Orders"
    assert doc.resolve_table("stockitems", NAMES) == "Warehouse.StockItems"
    assert doc.resolve_table("PurchaseOrders", NAMES) == "Purchasing.PurchaseOrders"


def test_resolve_table_keeps_a_bare_name_bare(schema):
    assert doc.resolve_table("TBLX", NAMES) == "TBLX"
    assert doc.resolve_table("tblx", NAMES) == "TBLX"


def test_resolve_table_unknown_name_is_none(schema):
    assert doc.resolve_table("Application.People", NAMES) is None
    assert doc.resolve_table("Order", NAMES) is None
    assert doc.resolve_table("", NAMES) is None


def test_resolve_table_ambiguous_bare_name_returns_the_candidates():
    names = ["Sales.Orders", "Purchasing.Orders", "Warehouse.StockItems"]
    assert doc.resolve_table("Orders", names) == ["Sales.Orders", "Purchasing.Orders"]


def test_resolve_table_exact_match_beats_an_ambiguous_bare_name():
    names = ["Sales.Orders", "Purchasing.Orders", "Orders"]
    assert doc.resolve_table("Orders", names) == "Orders"


# ----------------------------------------------------------------- table_detail


def test_table_detail_by_qualified_name(schema):
    text = doc.table_detail(schema, ["Sales.Orders"])
    assert text.startswith("Sales.Orders — siparişler [Sales]")
    assert "OrderID INT NOT NULL — sipariş numarası" in text
    assert "-> Sales.Customers.CustomerID" in text
    assert "-> Warehouse.StockItems.StockItemID" in text
    assert "0=hayır" in text


def test_table_detail_by_bare_name_is_the_same_text(schema):
    assert doc.table_detail(schema, ["stockitems"]) == doc.table_detail(schema, ["Warehouse.StockItems"])
    assert "StockItemName NVARCHAR(200)" in doc.table_detail(schema, ["StockItems"])


def test_table_detail_mixes_bare_and_qualified_names_in_request_order(schema):
    text = doc.table_detail(schema, ["TBLX", "purchaseorders"])
    assert text.index("TBLX —") < text.index("Purchasing.PurchaseOrders —")
    assert "SupplierID" in text


def test_table_detail_ambiguous_bare_name_asks_for_the_schema(tmp_path):
    schema = load(
        [
            {"name": "Sales.Orders", "columns": [{"name": "OrderID", "type": "INT"}]},
            {"name": "Purchasing.Orders", "columns": [{"name": "OrderID", "type": "INT"}]},
        ],
        tmp_path,
    )
    text = doc.table_detail(schema, ["Orders"])
    assert text == "Belirsiz tablo adı: Orders (Sales.Orders, Purchasing.Orders); şemasıyla yazın."
    assert len(text.splitlines()) == 1
    assert "OrderID" not in text
    assert doc.table_detail(schema, ["Purchasing.Orders"]).startswith("Purchasing.Orders —")


def test_table_detail_unknown_qualified_name_lists_the_known_ones(schema):
    text = doc.table_detail(schema, ["Website.Customers"])
    assert text.startswith("Bilinmeyen tablo: Website.Customers.")
    assert "SALES.ORDERS" in text and "TBLX" in text
    assert len(text.splitlines()) == 1


def test_table_detail_never_shows_none(schema):
    for name in NAMES + ["orders", "TBLFOO"]:
        assert "None" not in doc.table_detail(schema, [name])
