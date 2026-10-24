"""Golden soruların doğruları: aynı satırlardan saf Python ile hesaplanır, SQL hiç okunmaz.

Ürün kodu bu modülü import etmez; yalnız testler kullanır. Her fonksiyonun sütun sırası
golden.jsonl'daki ilgili SQL'in select sırasıyla aynıdır (PLAN Decision 1). Tarih aralıkları
golden SQL'deki yarı-açık sabitlerle birebir aynıdır (PLAN Decision 3).
"""

from __future__ import annotations

from collections.abc import Callable

Dataset = dict[str, list[dict]]

APR = ("2016-04-01", "2016-05-01")
YEAR = ("2016-01-01", "2017-01-01")


def _in_span(value: str, span: tuple[str, str]) -> bool:
    return span[0] <= value < span[1]


def _invoices(rows: Dataset) -> dict[int, dict]:
    return {i["InvoiceID"]: i for i in rows["Sales.Invoices"]}


def _ciro(rows: Dataset, span: tuple[str, str] | None = None) -> dict[str, float]:
    """Ürün adına göre kredi notları hariç ciro; IsCreditNote = 0 satırlarının ExtendedPrice toplamı."""
    invoices = _invoices(rows)
    names = {it["StockItemID"]: it["StockItemName"] for it in rows["Warehouse.StockItems"]}
    totals: dict[str, float] = {}
    for line in rows["Sales.InvoiceLines"]:
        invoice = invoices[line["InvoiceID"]]
        if invoice["IsCreditNote"] == 0 and (span is None or _in_span(invoice["InvoiceDate"], span)):
            name = names[line["StockItemID"]]
            totals[name] = totals.get(name, 0.0) + line["ExtendedPrice"]
    return totals


def q01(rows: Dataset) -> list[tuple]:
    countries = {c["CountryID"]: c["CountryName"] for c in rows["Application.Countries"]}
    counts: dict[str, int] = {}
    for city in rows["Application.Cities"]:
        name = countries[city["CountryID"]]
        counts[name] = counts.get(name, 0) + 1
    return sorted(counts.items())


def q02(rows: Dataset) -> list[tuple]:
    return [(sum(1 for o in rows["Sales.Orders"] if o["InvoiceID"] is None),)]


def q03(rows: Dataset) -> list[tuple]:
    return [(sum(_ciro(rows).values()),)]


def q04(rows: Dataset) -> list[tuple]:
    return [(sum(1 for o in rows["Sales.Orders"] if o["IsBackorder"] == 1),)]


def q05(rows: Dataset) -> list[tuple]:
    names = {it["StockItemID"]: it["StockItemName"] for it in rows["Warehouse.StockItems"]}
    return sorted((names[h["StockItemID"]], h["QuantityOnHand"]) for h in rows["Warehouse.StockItemHoldings"])


def q06(rows: Dataset) -> list[tuple]:
    return [(sum(1 for i in rows["Sales.Invoices"] if i["ConfirmedDeliveryTime"] is None),)]


def q07(rows: Dataset) -> list[tuple]:
    return [(len({c["CustomerID"] for c in rows["Sales.Customers"]}),)]


def q08(rows: Dataset) -> list[tuple]:
    expected = {p["PurchaseOrderID"]: p["ExpectedDeliveryDate"] for p in rows["Purchasing.PurchaseOrders"]}
    late = sum(
        1
        for line in rows["Purchasing.PurchaseOrderLines"]
        if line["ReceivedDate"] is not None and line["ReceivedDate"] > expected[line["PurchaseOrderID"]]
    )
    return [(late,)]


def q09(rows: Dataset) -> list[tuple]:
    return [(sum(line["LineProfit"] for line in rows["Sales.InvoiceLines"]),)]


def q10(rows: Dataset) -> list[tuple]:
    balances: dict[int, float] = {}
    for tx in rows["Sales.CustomerTransactions"]:
        key = tx["CustomerID"]
        balances[key] = balances.get(key, 0.0) + tx["AmountForTransaction"]
    return sorted(balances.items())


def q11(rows: Dataset) -> list[tuple]:
    return [(sum(_ciro(rows, APR).values()),)]


def q12(rows: Dataset) -> list[tuple]:
    top = sorted(_ciro(rows, YEAR).items(), key=lambda item: (-item[1], item[0]))[:5]
    return [(name, total) for name, total in top]


def q13(rows: Dataset) -> list[tuple]:
    counts: dict[int, int] = {}
    for order in rows["Sales.Orders"]:
        if _in_span(order["OrderDate"], YEAR):
            key = order["SalespersonPersonID"]
            counts[key] = counts.get(key, 0) + 1
    return sorted(counts.items())


REFERENCES: dict[str, Callable[[Dataset], list[tuple]]] = {
    "Q01": q01,
    "Q02": q02,
    "Q03": q03,
    "Q04": q04,
    "Q05": q05,
    "Q06": q06,
    "Q07": q07,
    "Q08": q08,
    "Q09": q09,
    "Q10": q10,
    "Q11": q11,
    "Q12": q12,
    "Q13": q13,
}
