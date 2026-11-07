# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

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


def q14(rows: Dataset) -> list[tuple]:
    countries = {c["CountryID"]: c["CountryName"] for c in rows["Application.Countries"]}
    return [(sum(1 for ci in rows["Application.Cities"] if countries[ci["CountryID"]] == "United States"),)]


def q15(rows: Dataset) -> list[tuple]:
    methods = {m["DeliveryMethodID"]: m["DeliveryMethodName"] for m in rows["Application.DeliveryMethods"]}
    return [(sum(1 for o in rows["Sales.Orders"] if methods[o["DeliveryMethodID"]] == "Courier Delivery"),)]


def q16(rows: Dataset) -> list[tuple]:
    names = {it["StockItemID"]: it["StockItemName"] for it in rows["Warehouse.StockItems"]}
    groups = {g["StockGroupID"]: g["StockGroupName"] for g in rows["Warehouse.StockGroups"]}
    in_clothing = {l["StockItemID"] for l in rows["Warehouse.StockItemStockGroups"] if groups[l["StockGroupID"]] == "Clothing"}
    return sorted(
        (names[h["StockItemID"]], h["QuantityOnHand"])
        for h in rows["Warehouse.StockItemHoldings"]
        if h["StockItemID"] in in_clothing
    )


def q17(rows: Dataset) -> list[tuple]:
    groups = {g["BuyingGroupID"]: g["BuyingGroupName"] for g in rows["Sales.BuyingGroups"]}
    return [(sum(1 for c in rows["Sales.Customers"] if groups.get(c["BuyingGroupID"]) == "Northern Traders Alliance"),)]


def q18(rows: Dataset) -> list[tuple]:
    return [(sum(line["ExtendedPrice"] for line in rows["Sales.InvoiceLines"]),)]


def q19(rows: Dataset) -> list[tuple]:
    items = {it["StockItemID"]: it for it in rows["Warehouse.StockItems"]}
    suppliers = {s["SupplierID"]: s["SupplierName"] for s in rows["Purchasing.Suppliers"]}
    invoices = _invoices(rows)
    totals: dict[str, float] = {}
    for line in rows["Sales.InvoiceLines"]:
        if invoices[line["InvoiceID"]]["IsCreditNote"] == 0:
            name = suppliers[items[line["StockItemID"]]["SupplierID"]]
            totals[name] = totals.get(name, 0.0) + line["ExtendedPrice"]
    return sorted(totals.items())


def q20(rows: Dataset) -> list[tuple]:
    people = {p["PersonID"]: p["FullName"] for p in rows["Application.People"]}
    invoices = _invoices(rows)
    totals: dict[str, float] = {}
    for line in rows["Sales.InvoiceLines"]:
        invoice = invoices[line["InvoiceID"]]
        if invoice["IsCreditNote"] == 0 and _in_span(invoice["InvoiceDate"], YEAR):
            name = people[invoice["SalespersonPersonID"]]
            totals[name] = totals.get(name, 0.0) + line["ExtendedPrice"]
    return sorted(totals.items())


def q21(rows: Dataset) -> list[tuple]:
    methods = {m["DeliveryMethodID"]: m["DeliveryMethodName"] for m in rows["Application.DeliveryMethods"]}
    invoices = _invoices(rows)
    totals: dict[str, float] = {}
    for line in rows["Sales.InvoiceLines"]:
        invoice = invoices[line["InvoiceID"]]
        if invoice["IsCreditNote"] == 0:
            name = methods[invoice["DeliveryMethodID"]]
            totals[name] = totals.get(name, 0.0) + line["ExtendedPrice"]
    return sorted(totals.items())


def q22(rows: Dataset) -> list[tuple]:
    methods = {m["DeliveryMethodID"]: m["DeliveryMethodName"] for m in rows["Application.DeliveryMethods"]}
    return [(sum(1 for o in rows["Sales.Orders"] if methods[o["DeliveryMethodID"]] == "Collection" and _in_span(o["OrderDate"], YEAR)),)]


def q23(rows: Dataset) -> list[tuple]:
    countries = {c["CountryID"]: c["CountryName"] for c in rows["Application.Countries"]}
    return [(sum(1 for sp in rows["Application.StateProvinces"] if countries[sp["CountryID"]] == "Germany"),)]


def q24(rows: Dataset) -> list[tuple]:
    orders = {p["PurchaseOrderID"]: p for p in rows["Purchasing.PurchaseOrders"]}
    suppliers = {s["SupplierID"]: s["SupplierName"] for s in rows["Purchasing.Suppliers"]}
    counts: dict[str, int] = {}
    for line in rows["Purchasing.PurchaseOrderLines"]:
        order = orders[line["PurchaseOrderID"]]
        if line["ReceivedDate"] is not None and line["ReceivedDate"] > order["ExpectedDeliveryDate"]:
            name = suppliers[order["SupplierID"]]
            counts[name] = counts.get(name, 0) + 1
    return sorted(counts.items())


def q25(rows: Dataset) -> list[tuple]:
    customers = {c["CustomerID"]: c for c in rows["Sales.Customers"]}
    cities = {ci["CityID"]: ci["CountryID"] for ci in rows["Application.Cities"]}
    countries = {c["CountryID"]: c["CountryName"] for c in rows["Application.Countries"]}
    invoices = _invoices(rows)
    totals: dict[str, float] = {}
    for line in rows["Sales.InvoiceLines"]:
        invoice = invoices[line["InvoiceID"]]
        if invoice["IsCreditNote"] == 0:
            country_id = cities[customers[invoice["BillToCustomerID"]]["DeliveryCityID"]]
            name = countries[country_id]
            totals[name] = totals.get(name, 0.0) + line["ExtendedPrice"]
    return sorted(totals.items())


def q26(rows: Dataset) -> list[tuple]:
    groups = {g["StockGroupID"]: g["StockGroupName"] for g in rows["Warehouse.StockGroups"]}
    item_groups: dict[int, list[int]] = {}
    for link in rows["Warehouse.StockItemStockGroups"]:
        item_groups.setdefault(link["StockItemID"], []).append(link["StockGroupID"])
    invoices = _invoices(rows)
    totals: dict[str, float] = {}
    for line in rows["Sales.InvoiceLines"]:
        if invoices[line["InvoiceID"]]["IsCreditNote"] == 0:
            for group_id in item_groups.get(line["StockItemID"], []):
                name = groups[group_id]
                totals[name] = totals.get(name, 0.0) + line["ExtendedPrice"]
    return sorted(totals.items())


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
    "Q14": q14,
    "Q15": q15,
    "Q16": q16,
    "Q17": q17,
    "Q18": q18,
    "Q19": q19,
    "Q20": q20,
    "Q21": q21,
    "Q22": q22,
    "Q23": q23,
    "Q24": q24,
    "Q25": q25,
    "Q26": q26,
}
