# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Mini veri kümesi: Satış/Depo şemalı dört tablonun deterministik satırları ve kurulumu.

WWI kurulana kadar M11 testleri bu küçük dünyayı okur (PLAN R4-9 dosya düzeni): nitelikli tablo
adları, bir PII kolonu ve üç tabloya yayılan bir join. Satırlar kendi RNG'sinden gelir; aynı
``seed`` aynı satırları verir, synthetic_erp'nin üreteciyle paylaşığı bir şey yoktur.
"""

from __future__ import annotations

import random
from pathlib import Path

from nl2sql.schema_map import build, doc

SCHEMA_PATH = Path(__file__).parent / "schema.json"

# (ünvan, şehir, telefon ön alanı)
CUSTOMERS = [
    ("Şok Market", "İstanbul", "0212"),
    ("Başak Gıda", "Ankara", "0312"),
    ("Marmara Toptan", "İzmir", "0232"),
    ("Anadolu Büfe", "Bursa", "0224"),
]

# (ürün, birim, liste birim fiyatı) - sipariş satırı bu fiyatı indirimli ya da indirimisiz öder
STOCK_ITEMS = [
    ("Filtre Kahve", "PAKET", 42.50),
    ("Toz Şeker", "KG", 18.90),
    ("Ayçiçek Yağı", "LT", 64.75),
    ("Yemeklik Un", "KG", 12.35),
    ("Makarna", "PAKET", 9.80),
    ("Zeytinyağı", "LT", 189.90),
]

ORDERS = 8


def generate(seed: int) -> dict[str, list[dict]]:
    """Bir tohumun dünyası: siparişler müşterilere sırayla dağılır, hiçbiri siparişsiz kalmaz."""
    rng = random.Random(f"{seed}:mini")
    customers = [
        {
            "CustomerID": 1 + index,
            "CustomerName": name,
            "City": city,
            "PhoneNumber": f"{phone} {rng.randint(200, 899)} {rng.randint(10, 99)} {rng.randint(10, 99)}",
        }
        for index, (name, city, phone) in enumerate(CUSTOMERS)
    ]
    items = [
        {"StockItemID": 1 + index, "StockItemName": name, "UnitName": unit}
        for index, (name, unit, _) in enumerate(STOCK_ITEMS)
    ]
    prices = {1 + index: price for index, (_, _, price) in enumerate(STOCK_ITEMS)}

    orders, lines, line_id = [], [], 0
    for order_id in range(1, ORDERS + 1):
        orders.append(
            {
                "OrderID": order_id,
                "CustomerID": 1 + (order_id - 1) % len(customers),
                "OrderDate": f"2016-{rng.randint(1, 5):02d}-{rng.randint(1, 28):02d}",
            }
        )
        for item_id in rng.sample(range(1, len(items) + 1), rng.randint(2, 3)):
            line_id += 1
            lines.append(
                {
                    "OrderLineID": line_id,
                    "OrderID": order_id,
                    "StockItemID": item_id,
                    "Quantity": rng.randint(2, 25),
                    "UnitPrice": round(prices[item_id] * rng.choice([1.0, 0.95]), 2),
                }
            )
    return {
        "Sales.Customers": customers,
        "Sales.Orders": orders,
        "Sales.OrderLines": lines,
        "Warehouse.StockItems": items,
    }


def build_db(seed: int, db_path, sql_path) -> str:
    """Kümenin iki fiziksel hedefini de kurar; SQLite sağlama toplamını döndürür."""
    dataset = generate(seed)
    schema = doc.load_schema(SCHEMA_PATH)
    build.write_sqlite(dataset, schema, db_path)
    build.write_mssql_script(dataset, schema, sql_path)
    return build.checksum(db_path)
