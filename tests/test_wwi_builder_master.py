"""T138: WWI üretecinin 1. bölümü - ana kayıtlar (PLAN R4-9).

``generate(seed)`` şemadaki her tabloya bir anahtar verir ve ana kayıtları doldurur. Buradaki
sınır üretilen satırların şemayla sözleşmesidir: satır anahtarları şema kolonlarıyla sırayla birebir
aynı, her foreign key dolu bir hedef satıra çıkıyor, aynı tohum aynı dünyayı veriyor ve bir müşteri
adı iki müşteri kartında iki farklı satın alma grubunda taşıyor. İşlem tabloları bu bölümde boştur.
"""

from collections import defaultdict

from nl2sql.datasets import load_dataset
from nl2sql.schema_map import doc

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


def test_same_seed_is_reproducible():
    assert DATASET.generate(42) == DATASET.generate(42)


def test_other_seed_is_a_different_world():
    assert DATASET.generate(42) != DATASET.generate(7)


def test_one_customer_name_sits_in_two_buying_groups():
    cards = defaultdict(set)
    groups = defaultdict(set)
    for row in ROWS["Sales.Customers"]:
        cards[row["CustomerName"]].add(row["CustomerID"])
        groups[row["CustomerName"]].add(row["BuyingGroupID"])
    matches = [
        name
        for name in cards
        if len(cards[name]) == 2 and len(groups[name]) == 2 and None not in groups[name]
    ]
    assert matches, "aynı ad iki kartta iki farklı satın alma grubunda taşınmıyor"
