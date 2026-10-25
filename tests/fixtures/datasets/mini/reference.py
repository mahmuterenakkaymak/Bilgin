"""Golden soruların doğruları: aynı satırlardan saf Python ile hesaplanır, SQL hiç okunmaz.

Ürün kodu bu modülü import etmez; yalnız testler kullanır. Her fonksiyonun sütun sırası
golden.jsonl'daki ilgili SQL'in select sırasıyla aynıdır (PLAN Decision 1).
"""

from __future__ import annotations

from collections.abc import Callable

Dataset = dict[str, list[dict]]


def _ciro(rows: Dataset) -> dict[int, float]:
    """Müşteri numarası başına ciro: her satırın tutarı siparişinin müşterisine akar."""
    totals: dict[int, float] = {}
    owner = {order["OrderID"]: order["CustomerID"] for order in rows["Sales.Orders"]}
    for line in rows["Sales.OrderLines"]:
        key = owner[line["OrderID"]]
        totals[key] = totals.get(key, 0.0) + line["Quantity"] * line["UnitPrice"]
    return totals


def q01(rows: Dataset) -> list[tuple]:
    return [(sum(line["Quantity"] * line["UnitPrice"] for line in rows["Sales.OrderLines"]),)]


def q02(rows: Dataset) -> list[tuple]:
    names = {item["StockItemID"]: item["StockItemName"] for item in rows["Warehouse.StockItems"]}
    quantities: dict[str, int] = {}
    for line in rows["Sales.OrderLines"]:
        name = names[line["StockItemID"]]
        quantities[name] = quantities.get(name, 0) + line["Quantity"]
    return sorted(quantities.items())


def q03(rows: Dataset) -> list[tuple]:
    names = {customer["CustomerID"]: customer["CustomerName"] for customer in rows["Sales.Customers"]}
    return [
        (key, names[key], total) for key, total in sorted(_ciro(rows).items())
    ]


REFERENCES: dict[str, Callable[[Dataset], list[tuple]]] = {
    "Q01": q01,
    "Q02": q02,
    "Q03": q03,
}
