# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T139: WWI üretecinin 2. bölümü - işlem tabloları ve tuzaklar (PLAN R4-9).

Sınır: üretilen satırların şemayla sözleşmesi (anahtarlar şema kolonlarıyla sırayla aynı, her
foreign key dolu bir hedefe çıkıyor, aynı tohum aynı dünya) ve tuzakların gerçekten var olması -
faturalanmamış sipariş, geri sipariş, NULL toplama zamanı, negatif kredi notları, NULL teslimat
onayı, beklenen tarihten sonra teslim alınan alış satırı, işaretli stok hareketleri ve bunlarla
tutarlı eldeki stok. Ayrıca kredi notunu dışlayan ciro, dışlamayan (naif) toplamlardan farklı olmalı
ve ``build_db`` iki hedefi de kurmalı: SQLite'ta her tablo, T-SQL betiğinde ise ifade ifade
çözümlenen bir kurulum (CREATE SCHEMA dahil).
"""

import sqlite3
from collections import defaultdict

import pytest
from sqlglot import parse

from bilgin.datasets import load_dataset
from bilgin.schema_map import doc

DATASET = load_dataset("wwi")
SCHEMA = DATASET.schema()

COLUMNS = {table["name"]: [c["name"] for c in table["columns"]] for table in SCHEMA["tables"]}
FOREIGN_KEYS = [
    (table["name"], column["name"], column["fk"])
    for table in SCHEMA["tables"]
    for column in table["columns"]
    if column["fk"]
]

ROWS = DATASET.generate()


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Tohum 42'nin kurulu hali: veri kümesi + SQLite dosyası + T-SQL betiğinin metni."""
    folder = tmp_path_factory.mktemp("wwi-build")
    database, script = folder / "wwi.db", folder / "wwi.sql"
    DATASET.build_db(42, database, script)
    return ROWS, database, script.read_text(encoding="utf-8")


def query(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def statements_of(script):
    """GO ile ayrılmış ifadeler; açıklama satırları düşürülür, boş parçalar atılır."""
    bodies = []
    for chunk in script.split("\nGO\n\n"):
        body = "\n".join(line for line in chunk.splitlines() if not line.startswith("--")).strip()
        if body:
            bodies.append(body)
    return bodies


# ----------------------------------------------------------------- şema sözleşmesi


def test_every_schema_table_has_a_key():
    assert set(ROWS) == set(COLUMNS)


def test_row_keys_are_the_schema_columns_in_order():
    for table, rows in ROWS.items():
        for row in rows:
            assert list(row) == COLUMNS[table], table


def test_every_foreign_key_value_exists():
    for table, column, fk in FOREIGN_KEYS:
        target, target_column = doc.split_fk(fk)
        present = {row[target_column] for row in ROWS[target]}
        for row in ROWS[table]:
            value = row[column]
            if value is None:
                continue
            assert value in present, f"{table}.{column} -> {fk}: {value} hedefte yok"


def test_determinism():
    assert DATASET.generate(42) == DATASET.generate(42)
    assert DATASET.generate(42) != DATASET.generate(7)


# ----------------------------------------------------------------- tuzaklar


def test_some_orders_are_never_invoiced():
    orders = ROWS["Sales.Orders"]
    assert any(o["InvoiceID"] is None for o in orders)
    assert any(o["InvoiceID"] is not None for o in orders)


def test_back_orders_reference_an_earlier_order():
    order_ids = {o["OrderID"] for o in ROWS["Sales.Orders"]}
    back = [o for o in ROWS["Sales.Orders"] if o["BackorderOrderID"] is not None]
    assert back, "hiç geri sipariş yok"
    for order in back:
        assert order["IsBackorder"] == 1
        assert order["BackorderOrderID"] in order_ids
        assert order["BackorderOrderID"] < order["OrderID"]


def test_some_orders_have_null_picking_completed_when():
    orders = ROWS["Sales.Orders"]
    assert any(o["PickingCompletedWhen"] is None for o in orders)
    assert any(o["PickingCompletedWhen"] is not None for o in orders)


def test_credit_notes_are_negative():
    credit_ids = {i["InvoiceID"] for i in ROWS["Sales.Invoices"] if i["IsCreditNote"] == 1}
    assert credit_ids, "hiç kredi notu yok"
    lines = [l for l in ROWS["Sales.InvoiceLines"] if l["InvoiceID"] in credit_ids]
    assert lines
    for line in lines:
        assert line["Quantity"] < 0
        assert line["ExtendedPrice"] < 0
        assert line["TaxAmount"] <= 0
        assert line["UnitPrice"] > 0


def test_some_invoices_have_null_confirmed_delivery_time():
    invoices = ROWS["Sales.Invoices"]
    assert any(i["ConfirmedDeliveryTime"] is None for i in invoices)
    assert any(i["ConfirmedDeliveryTime"] is not None for i in invoices)


def test_tax_amount_and_extended_price_follow_the_line():
    for line in ROWS["Sales.InvoiceLines"]:
        q, p, t = line["Quantity"], line["UnitPrice"], line["TaxRate"]
        assert line["TaxAmount"] == round(q * p * t / 100, 2)
        assert line["ExtendedPrice"] == round(q * p, 2)


def test_some_purchase_lines_received_after_expected_delivery():
    expected = {o["PurchaseOrderID"]: o["ExpectedDeliveryDate"] for o in ROWS["Purchasing.PurchaseOrders"]}
    late = [
        line
        for line in ROWS["Purchasing.PurchaseOrderLines"]
        if line["ReceivedDate"] is not None
        and line["ReceivedDate"][:10] > expected[line["PurchaseOrderID"]]
    ]
    assert late, "beklenen tarihten sonra teslim alınan alış satırı yok"


def test_stock_transactions_signed_and_several_per_item():
    transactions = ROWS["Warehouse.StockItemTransactions"]
    assert any(t["Quantity"] > 0 for t in transactions)
    assert any(t["Quantity"] < 0 for t in transactions)
    per_item = defaultdict(int)
    for tx in transactions:
        per_item[tx["StockItemID"]] += 1
    assert per_item and all(count >= 2 for count in per_item.values())


def test_holdings_match_the_transactions():
    by_item = defaultdict(float)
    for tx in ROWS["Warehouse.StockItemTransactions"]:
        by_item[tx["StockItemID"]] += tx["Quantity"]
    for row in ROWS["Warehouse.StockItemHoldings"]:
        assert row["QuantityOnHand"] >= 0
        assert row["QuantityOnHand"] == pytest.approx(by_item[row["StockItemID"]], abs=1e-4)


def test_customer_transactions_one_per_invoice_plus_payments():
    transactions = ROWS["Sales.CustomerTransactions"]
    invoice_ids = {i["InvoiceID"] for i in ROWS["Sales.Invoices"]}
    posted = {t["InvoiceID"] for t in transactions if t["InvoiceID"] is not None}
    assert posted == invoice_ids
    assert all(t["InvoiceID"] is None or t["TransactionTypeID"] in (1, 10) for t in transactions)
    assert any(t["TransactionTypeID"] == 2 and t["InvoiceID"] is None for t in transactions)


def test_credit_note_excluded_revenue_differs_from_naive():
    credit_ids = {i["InvoiceID"] for i in ROWS["Sales.Invoices"] if i["IsCreditNote"] == 1}
    naive = sum(l["ExtendedPrice"] for l in ROWS["Sales.InvoiceLines"])
    correct = sum(l["ExtendedPrice"] for l in ROWS["Sales.InvoiceLines"] if l["InvoiceID"] not in credit_ids)
    assert naive != correct


# ----------------------------------------------------------------- build_db hedefleri


def test_build_db_creates_every_table_in_sqlite(built):
    _, database, _ = built
    created = {
        row[0]
        for row in query(database, "SELECT name FROM sqlite_master WHERE type = 'table'")
        if not row[0].startswith("sqlite_")
    }
    assert created == set(COLUMNS)


def test_build_db_script_parses_statement_by_statement(built):
    _, _, script = built
    bodies = statements_of(script)
    assert any(statement.startswith("CREATE SCHEMA") for statement in bodies)
    assert sum(1 for statement in bodies if statement.startswith("CREATE TABLE")) == len(COLUMNS)
    assert any(statement.startswith("INSERT INTO") for statement in bodies)
    for statement in bodies:
        result = parse(statement, read="tsql")
        assert len(result) == 1 and result[0] is not None, statement[:80]


def test_build_db_not_null_columns_hold_no_nulls(built):
    _, database, _ = built
    for table in SCHEMA["tables"]:
        required = [column["name"] for column in table["columns"] if not column["nullable"]]
        where = " AND ".join(f"{name} IS NULL" for name in required)
        assert query(database, f'SELECT COUNT(*) FROM "{table["name"]}" WHERE {where}') == [(0,)], table["name"]


def test_build_db_checksum_is_deterministic(tmp_path):
    a = DATASET.build_db(42, tmp_path / "a.db", tmp_path / "a.sql")
    b = DATASET.build_db(42, tmp_path / "b.db", tmp_path / "b.sql")
    other = DATASET.build_db(7, tmp_path / "c.db", tmp_path / "c.sql")
    assert a == b
    assert a != other
