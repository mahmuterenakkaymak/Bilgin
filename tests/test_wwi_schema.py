# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T136: WWI veri kümesinin tanımı ve şeması (PLAN R4-9, R4-7).

Kümenin Python'u (``builder.py``, ``reference.py``) T138-T142'de yazılacak; dataset.json'daki kod
gönderimleri ilk kullanımda çözüldüğü için şema bugün onlarsız okunur. Buradaki sınır şemanın kendi
sözleşmesidir: tablo adları ``module.table`` biçiminde, her foreign key gerçek bir kolona çıkıyor,
her tip SQLite yazıcısının bildiği bir ada oturuyor ve PII/deny işaretleri R4-7'nin listesiyle
birebir aynı - sonradan gelecek üreteç altın sorular bunların üstüne kurulacak.
"""

import pytest

from nl2sql import config
from nl2sql.datasets import load_dataset
from nl2sql.policy import pii
from nl2sql.schema_map import build, doc

DATASET = load_dataset("wwi")
SCHEMA = DATASET.schema()

# R4-9: kümenin taşıyacağı yirmi tablo, şema adlarıyla.
R4_9_TABLES = {
    "Application.Countries",
    "Application.StateProvinces",
    "Application.Cities",
    "Application.DeliveryMethods",
    "Application.People",
    "Sales.BuyingGroups",
    "Sales.Customers",
    "Sales.Orders",
    "Sales.OrderLines",
    "Sales.Invoices",
    "Sales.InvoiceLines",
    "Sales.CustomerTransactions",
    "Warehouse.StockGroups",
    "Warehouse.StockItems",
    "Warehouse.StockItemStockGroups",
    "Warehouse.StockItemTransactions",
    "Warehouse.StockItemHoldings",
    "Purchasing.Suppliers",
    "Purchasing.PurchaseOrders",
    "Purchasing.PurchaseOrderLines",
}

# R4-7: WWI'de maskeye giden kolonların tam listesi.
R4_7_PII = {
    "Application.People": {
        "FullName": "person_name",
        "PreferredName": "person_name",
        "LogonName": "email",
        "EmailAddress": "email",
        "PhoneNumber": "phone",
        "FaxNumber": "phone",
    },
    "Sales.Customers": {
        "PhoneNumber": "phone",
        "FaxNumber": "phone",
        "DeliveryAddressLine1": "address",
        "DeliveryAddressLine2": "address",
        "PostalAddressLine1": "address",
        "PostalAddressLine2": "address",
    },
    "Purchasing.Suppliers": {
        "PhoneNumber": "phone",
        "FaxNumber": "phone",
        "DeliveryAddressLine1": "address",
        "DeliveryAddressLine2": "address",
        "PostalAddressLine1": "address",
        "PostalAddressLine2": "address",
    },
}

# R4-7: modelin hiç görmeyeceği iki sır (brief "PhotoPath" diyor, WWI'nin gerçek kolonu Photo).
R4_7_DENY = {"APPLICATION.PEOPLE.HASHEDPASSWORD", "APPLICATION.PEOPLE.PHOTO"}


# ------------------------------------------------------------------ the folder is a dataset


def test_the_folder_loads_as_a_dataset():
    assert DATASET.name == "wwi"
    assert DATASET.display_name == "WideWorldImporters (Microsoft örnek veritabanı)"
    assert DATASET.dialect == "tsql"
    assert DATASET.connection == "sqlite"
    assert DATASET.default_schema is None
    assert DATASET.as_of == "2016-05-31"
    assert DATASET.seed == 42
    assert DATASET.builder_ref == "builder.py:build_db"
    assert DATASET.generator_ref == "builder.py:generate"
    assert DATASET.references_ref == "reference.py:REFERENCES"
    assert DATASET.traps_path == DATASET.root / "traps.jsonl"


def test_the_outputs_are_the_run_4_defaults():
    assert DATASET.db_path == config.ROOT / "data" / "wwi.db"
    assert DATASET.mssql_script == config.ROOT / "db" / "mssql" / "build_wwi.sql"
    assert DATASET.index_dir == config.ROOT / "index" / "wwi"
    assert DATASET.eval_out == config.ROOT / "eval_out" / "wwi"


# ------------------------------------------------------------------ the schema doc


def test_the_schema_holds_the_r4_9_tables():
    assert {table["name"] for table in SCHEMA["tables"]} == R4_9_TABLES


def test_every_table_name_is_qualified_by_its_module():
    for table in SCHEMA["tables"]:
        schema_part, name = doc.split_name(table["name"])
        assert schema_part, table["name"]
        assert name, table["name"]
        assert table["module"] == schema_part, table["name"]


def test_every_foreign_key_resolves_to_a_real_column():
    columns = {table["name"]: [column["name"] for column in table["columns"]] for table in SCHEMA["tables"]}
    for table in SCHEMA["tables"]:
        for column in table["columns"]:
            if not column["fk"]:
                continue
            target, target_column = doc.split_fk(column["fk"])
            assert target in columns, f"{table['name']}.{column['name']} -> {column['fk']}"
            assert target_column in columns[target], f"{table['name']}.{column['name']} -> {column['fk']}"


@pytest.mark.parametrize("table", SCHEMA["tables"], ids=lambda table: table["name"])
def test_every_column_type_is_writable_to_sqlite(table):
    for column in table["columns"]:
        base = column["type"].split("(")[0].upper()
        assert base in build.SQLITE_TYPES, f"{table['name']}.{column['name']}: {column['type']}"


@pytest.mark.parametrize("table", SCHEMA["tables"], ids=lambda table: table["name"])
def test_every_table_is_described_and_has_keywords(table):
    assert table["description"].strip(), table["name"]
    assert table["keywords"], table["name"]


# ------------------------------------------------------------------ pii and deny (R4-7)


def test_every_pii_mark_is_a_known_class():
    for table in SCHEMA["tables"]:
        for column in table["columns"]:
            if column["pii"]:
                assert column["pii"] in pii.CLASSES, f"{table['name']}.{column['name']}: {column['pii']}"


def test_the_pii_marks_are_the_r4_7_list():
    want = {
        (table.upper(), column.upper()): cls
        for table, columns in R4_7_PII.items()
        for column, cls in columns.items()
    }
    assert pii.column_map(SCHEMA) == want


@pytest.mark.parametrize(
    ("table", "column", "cls"),
    [
        (table, column, cls)
        for table, columns in R4_7_PII.items()
        for column, cls in columns.items()
    ],
    ids=lambda value: str(value),
)
def test_the_r4_7_column_carries_its_class(table, column, cls):
    marked = {
        column["name"]: column["pii"]
        for row in SCHEMA["tables"]
        if row["name"] == table
        for column in row["columns"]
    }
    assert marked[column] == cls


def test_the_two_people_secrets_are_denied():
    denied = {
        f"{table['name']}.{column['name']}".upper()
        for table in SCHEMA["tables"]
        for column in table["columns"]
        if column.get("deny")
    }
    assert denied == R4_7_DENY
