"""WWI veri kümesinin üreteci (PLAN R4-9).

Kendi RNG'sinden deterministik bir dünya kurar: ``random.Random(f"{seed}:wwi")`` aynı tohumu her
zaman aynı satırlara çevirir, başka bir tohum başka bir dünya verir. Bu 1. bölüm şemadaki her
tabloya bir anahtar döndürür ve yalnız ana kayıtları doldurur (ülkeler, kişiler, müşteriler,
tedarikçiler, stok kalemleri); işlem tabloları (Orders, Invoices, hareketler) boş listenin içindedir
ve sonraki bölümlerde dolar. Satır anahtarları şema kolonlarıyla sırayla birebir aynıdır, tarihler
ISO metin, BIT 0/1'dir; HashedPassword ve Photo sır olduğu için NULL kalır.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from pathlib import Path

from nl2sql.schema_map import build, doc

SCHEMA_PATH = Path(__file__).parent / "schema.json"

# Ülke sabitleri (kıta/ISO gerçek dünya); nüfuslar RNG ile üretilen kurgusal adlardan gelir.
COUNTRIES = [
    (1, "United States", "US", "North America"),
    (2, "Canada", "CA", "North America"),
    (3, "Germany", "DE", "Europe"),
    (4, "France", "FR", "Europe"),
]

# (kod, ad, CountryID) - her ülkeye iki eyalet.
PROVINCES = [
    ("CA", "California", 1),
    ("NY", "New York", 1),
    ("ON", "Ontario", 2),
    ("QC", "Quebec", 2),
    ("BY", "Bavaria", 3),
    ("BE", "Berlin", 3),
    ("IDF", "Ile-de-France", 4),
    ("ARA", "Auvergne-Rhone-Alpes", 4),
]

CITY_NAMES = [
    "Northgate", "Rivermont", "Ashvale", "Brackenhill", "Cedarford", "Dunmore",
    "Elmsworth", "Fairhaven", "Glenmoor", "Havenport", "Ironwood", "Kirkwall",
    "Larkspur", "Marlowe", "Nettlebury", "Oakridge", "Pinehurst", "Quarryville",
]

# (ad, LeadTimeDays, IsCashDelivery)
DELIVERY_METHODS = [
    ("Collection", 0, 0),
    ("Courier Delivery", 1, 0),
    ("Drop Down Delivery", 3, 1),
    ("Reception", 0, 0),
    ("Cash on Collection", 0, 1),
]

BUYING_GROUPS = [
    "Continental Retail Group",
    "Northern Traders Alliance",
    "Pacific Mercantile Union",
]

# İki müşteri kartının paylaşacağı ad: biri 1 numaralı, öteki 2 numaralı satın alma grubunda.
SHARED_CUSTOMER_NAME = "Meridian Provisions"

CUSTOMER_NAMES = [
    "Alder & Finch Retail", "Bramble Grocery Co", "Copperfield Markets", "Driftwood Provisions",
    "Everline Wholesale", "Foxglove Foods", "Granite City Grocers", "Harborview Trading",
]

CUSTOMER_CATEGORIES = ["Primary Market", "Wholesale", "Supermarket", "Small Reseller"]
MARKET_CATEGORIES = ["General Retail", "Specialty Retail", "Online Retail"]

SUPPLIER_NAMES = [
    "Ashcombe Novelties", "Brightline Toys", "Cedarvale Foods", "Dunmore Textiles",
]
SUPPLIER_CATEGORIES = ["Novelty Suppliers", "Toy Suppliers", "Food Suppliers", "Clothing Suppliers"]

STOCK_GROUPS = ["Novelty Items", "Clothing", "Toys", "General Merchandise"]

PRODUCT_NAMES = [
    "Alpine Rechargeable Torch", "Beacon Ceramic Mug", "Crestline Wool Scarf",
    "Dovetail Cutting Board", "Emberly Steel Bottle", "Fjord Fleece Blanket",
    "Grove Bamboo Utensils", "Harbor Canvas Tote", "Ironbark Cast Iron Pan",
    "Juniper Scented Candle", "Kestrel Rain Jacket", "Lantern Wooden Toy Train",
]
BRANDS = ["Alpine", "Beacon", "Crestline", "Dovetail", "Emberly"]
SIZES = ["each", "1200 ml", "100 tablet", "200 mm", "pack of 6", "500 g"]

FIRST_NAMES = [
    "Avery", "Jordan", "Rowan", "Cameron", "Morgan", "Taylor", "Skyler", "Reese",
    "Dana", "Lena", "Marco", "Priya", "Noel", "Sasha", "Iris", "Emre",
]
LAST_NAMES = [
    "Halloway", "Brightwater", "Fairbanks", "Kingsley", "Ashford", "Vandermeer",
    "Okafor", "Lindqvist", "Moreau", "Castellano", "Novak", "Whitfield",
    "Sandoval", "Petrov", "Delacroix", "Abernathy",
]

STREETS = [
    "Market Street", "Foundry Road", "Harbour Lane", "Mill Brook Way",
    "Kiln Row", "Vine Terrace", "Orchard Bend", "Granary Close",
]

TAX_RATES = [0.0, 5.0, 20.0]


def _iso_date(rng: random.Random, lo: int, hi: int) -> str:
    return f"{rng.randint(lo, hi):04d}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"


def _phone(rng: random.Random) -> str:
    return f"({rng.randint(200, 989)}) 555-{rng.randint(1000, 9999)}"


def _address(rng: random.Random) -> str:
    return f"{rng.randint(1, 999)} {rng.choice(STREETS)}"


def _people(rng: random.Random):
    """Satış temsilcileri, alıcılar ve müşteri/tedarikçi muhatapları; adlar kurgusal ve benzersiz."""
    used: set[str] = set()

    def full_name() -> str:
        while True:
            name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
            if name not in used:
                used.add(name)
                return name

    rows, sales, buyers, contacts = [], [], [], []

    def add(person_id: int, is_sales: bool, is_buyer: bool, is_disabled: bool) -> int:
        full = full_name()
        first, last = full.split(" ", 1)
        logon = f"{first}{last}@fabrikam.example".lower()
        rows.append(
            {
                "PersonID": person_id,
                "FullName": full,
                "PreferredName": first,
                "IsSalesPerson": 1 if is_sales else 0,
                "IsBuyer": 1 if is_buyer else 0,
                "IsDisabled": 1 if is_disabled else 0,
                "LogonName": logon,
                "EmailAddress": logon,
                "PhoneNumber": _phone(rng),
                "FaxNumber": rng.choice([None, _phone(rng)]),
                "HashedPassword": None,
                "Photo": None,
            }
        )
        return person_id

    pid = 0
    for _ in range(6):
        pid += 1
        sales.append(add(pid, True, False, False))
    for _ in range(4):
        pid += 1
        buyers.append(add(pid, False, True, False))
    for index in range(4):
        pid += 1
        contacts.append(add(pid, False, False, index == 3))
    return rows, sales, buyers, contacts


def _day(s: str) -> date:
    return date.fromisoformat(s[:10])


def _add_days(s: str, n: int) -> str:
    return (_day(s) + timedelta(days=n)).isoformat()


def _dt(s: str, rng: random.Random) -> str:
    """ISO tarihe RNG ile bir saat ekler; DATETIME2 kolonları için 'YYYY-MM-DD HH:MM:SS' üretir."""
    return datetime.strptime(s[:10], "%Y-%m-%d").replace(
        hour=rng.randint(8, 18), minute=rng.randint(0, 59), second=rng.randint(0, 59)
    ).strftime("%Y-%m-%d %H:%M:%S")


def _purchase_orders(rng: random.Random, dataset: dict) -> list[dict]:
    """Alış siparişleri ve satırları; bazı satırlar ExpectedDeliveryDate sonrası teslim alınır (tuzak)."""
    suppliers = dataset["Purchasing.Suppliers"]
    delivery_ids = [m["DeliveryMethodID"] for m in dataset["Application.DeliveryMethods"]]
    buyers = [p["PersonID"] for p in dataset["Application.People"] if p["IsBuyer"]]
    items_by_supplier: dict[int, list[dict]] = {}
    for item in dataset["Warehouse.StockItems"]:
        items_by_supplier.setdefault(item["SupplierID"], []).append(item)

    orders, lines = [], []
    line_id = 0
    for po_index, supplier in enumerate(suppliers):
        pool = items_by_supplier.get(supplier["SupplierID"]) or dataset["Warehouse.StockItems"]
        order_id = len(orders) + 1
        order_date = f"2016-{rng.randint(1, 5):02d}-{rng.randint(1, 26):02d}"
        expected = _add_days(order_date, rng.randint(3, 10))
        orders.append(
            {
                "PurchaseOrderID": order_id,
                "SupplierID": supplier["SupplierID"],
                "OrderDate": order_date,
                "DeliveryMethodID": rng.choice(delivery_ids),
                "ContactPersonID": rng.choice(buyers),
                "ExpectedDeliveryDate": expected,
                "SupplierReference": rng.choice([None, f"PO-{rng.randint(10000, 99999)}"]),
                "IsOrderClosed": rng.randint(0, 1),
            }
        )
        for line_index, item in enumerate(rng.sample(pool, rng.randint(1, min(3, len(pool))))):
            line_id += 1
            received = rng.random() < 0.8
            # İlk siparişin ilk satırı geç teslim: "bazıları beklenen tarihten sonra alındı" tuzağı garantili.
            late = po_index == 0 and line_index == 0
            received_date = None
            if received:
                offset = rng.randint(1, 6) if late else -rng.randint(1, 5)
                received_date = _dt(_add_days(expected, offset), rng)
            lines.append(
                {
                    "PurchaseOrderLineID": line_id,
                    "PurchaseOrderID": order_id,
                    "StockItemID": item["StockItemID"],
                    "OrderQuantity": rng.randint(50, 300),
                    "UnitPrice": round(item["BuyingPrice"] * rng.uniform(0.9, 1.1), 4),
                    "TaxRate": rng.choice(TAX_RATES),
                    "LineDescription": item["StockItemName"],
                    "ReceivedDate": received_date,
                    "IsOrderClosed": 1 if received else 0,
                    "OrderLineStatus": "Closed" if received else "Open",
                }
            )
    return orders, lines


def _sales(rng: random.Random, dataset: dict) -> None:
    """Satış tarafını kurar: siparişler Ocak-Mayıs 2016, faturalar (bazıları kredi notu), hesap ve stok hareketleri, eldeki stok."""
    customers = dataset["Sales.Customers"]
    items = dataset["Warehouse.StockItems"]
    delivery_ids = [m["DeliveryMethodID"] for m in dataset["Application.DeliveryMethods"]]
    sales_people = [p["PersonID"] for p in dataset["Application.People"] if p["IsSalesPerson"]]
    contacts = [p["PersonID"] for p in dataset["Application.People"] if not p["IsSalesPerson"] and not p["IsBuyer"]]
    # Fatura, müşterinin BillToCustomerID'sine kesilir; ana kayıt bunu satın alma grubunun başına ayarlamıştı.
    bill_to = {c["CustomerID"]: c["BillToCustomerID"] for c in customers}
    buying_price = {i["StockItemID"]: i["BuyingPrice"] for i in items}

    # --- Siparişler: bazıları faturalanmamış (InvoiceID NULL), bazıları geri sipariş, bazıları toplanmamış.
    orders, order_lines = [], []
    line_id = 0
    for order_id in range(1, 25):
        customer = rng.choice(customers)
        order_date = f"2016-{rng.randint(1, 5):02d}-{rng.randint(1, 27):02d}"
        picked = rng.random() < 0.75
        picked_by = rng.choice(sales_people) if picked else None
        picking_when = _dt(order_date, rng) if picked else None
        orders.append(
            {
                "OrderID": order_id,
                "CustomerID": customer["CustomerID"],
                "OrderDate": order_date,
                "IsStockItemOrderType": 1,
                "IsBackorder": 0,
                "InvoiceID": None,
                "BackorderOrderID": None,
                "ContactPersonID": rng.choice(contacts),
                "SalespersonPersonID": rng.choice(sales_people),
                "PickedByPersonID": picked_by,
                "DeliveryMethodID": rng.choice(delivery_ids),
                "ExpectedDeliveryDate": _add_days(order_date, rng.randint(1, 7)),
                "PickingCompletedWhen": picking_when,
            }
        )
        for stock_item in rng.sample(items, rng.randint(1, 4)):
            line_id += 1
            gift = rng.random() < 0.08
            quantity = rng.randint(1, 40)
            order_lines.append(
                {
                    "OrderLineID": line_id,
                    "OrderID": order_id,
                    "StockItemID": stock_item["StockItemID"],
                    "Description": stock_item["StockItemName"],
                    "IsGift": 1 if gift else 0,
                    "Quantity": quantity,
                    "UnitPrice": round(stock_item["BuyingPrice"] * rng.uniform(1.4, 2.6), 4),
                    "TaxRate": rng.choice(TAX_RATES),
                    "PickedQuantity": quantity if picked else 0,
                    "PickingCompletedWhen": picking_when,
                    "FirstDeliveryQuantity": quantity if picked else None,
                    "FirstDeliveryDate": order_date if picked else None,
                }
            )

    # Geri siparişler: bir önceki siparişi geri sipariş eder; IsBackorder=1, BackorderOrderID dolu.
    # 2 numaralı sipariş zorunlu geri sipariş (tuzak garantili); zincir olmaması için hedef geri sipariş olamaz.
    backorder: set[int] = set()
    for order in orders:
        order_id = order["OrderID"]
        if order_id < 2 or (order_id - 1) in backorder:
            continue
        if order_id == 2 or rng.random() < 0.15:
            order["IsBackorder"] = 1
            order["BackorderOrderID"] = order_id - 1
            backorder.add(order_id)

    # --- Faturalar: toplanmış siparişlerin çoğu faturalanır, birkaçı faturalanmamış kalır (tuzak).
    picked_orders = [o["OrderID"] for o in orders if o["PickingCompletedWhen"] is not None]
    invoiced = set(rng.sample(picked_orders, max(1, len(picked_orders) - 3)))
    lines_by_order: dict[int, list[dict]] = {}
    for line in order_lines:
        lines_by_order.setdefault(line["OrderID"], []).append(line)

    invoices, invoice_lines = [], []
    invoice_id = 0
    invoice_line_id = 0
    for order in orders:
        if order["OrderID"] not in invoiced:
            continue
        invoice_id += 1
        invoice_date = _add_days(order["OrderDate"], rng.randint(1, 4))
        invoices.append(
            {
                "InvoiceID": invoice_id,
                "CustomerID": order["CustomerID"],
                "BillToCustomerID": bill_to[order["CustomerID"]],
                "OrderID": order["OrderID"],
                "DeliveryMethodID": order["DeliveryMethodID"],
                "SalespersonPersonID": order["SalespersonPersonID"],
                "InvoiceDate": invoice_date,
                "IsCreditNote": 0,
                "ConfirmedDeliveryTime": rng.choice([None, _dt(invoice_date, rng)]),
            }
        )
        order["InvoiceID"] = invoice_id
        for line in lines_by_order[order["OrderID"]]:
            if line["IsGift"]:
                continue  # hediye satırı sipariş edilir ve toplanır ama asla faturalanmaz.
            invoice_line_id += 1
            quantity, price, rate = line["Quantity"], line["UnitPrice"], line["TaxRate"]
            tax = round(quantity * price * rate / 100, 2)
            # ASSUMPTION: ExtendedPrice şema tanımına göre KDV hariç Quantity*UnitPrice'dır (görev metnindeki "+ TaxAmount" şemanın "VAT excluded" tanımıyla çelişir).
            invoice_lines.append(
                {
                    "InvoiceLineID": invoice_line_id,
                    "InvoiceID": invoice_id,
                    "StockItemID": line["StockItemID"],
                    "Description": line["Description"],
                    "Quantity": quantity,
                    "UnitPrice": price,
                    "TaxRate": rate,
                    "TaxAmount": tax,
                    "LineProfit": round((price - buying_price[line["StockItemID"]]) * quantity, 2),
                    "ExtendedPrice": round(quantity * price, 2),
                }
            )

    # Kredi notları: faturalanmış siparişlerin bir kısmı için iade; negatif miktar ve tutarlar (tuzak).
    credit_source = rng.sample(invoices, min(3, len(invoices)))
    for source in credit_source:
        invoice_id += 1
        credit_date = _add_days(source["InvoiceDate"], rng.randint(3, 15))
        invoices.append(
            {
                "InvoiceID": invoice_id,
                "CustomerID": source["CustomerID"],
                "BillToCustomerID": source["BillToCustomerID"],
                "OrderID": source["OrderID"],
                "DeliveryMethodID": source["DeliveryMethodID"],
                "SalespersonPersonID": source["SalespersonPersonID"],
                "InvoiceDate": credit_date,
                "IsCreditNote": 1,
                "ConfirmedDeliveryTime": None,
            }
        )
        for line in [l for l in invoice_lines if l["InvoiceID"] == source["InvoiceID"]]:
            invoice_line_id += 1
            invoice_lines.append(
                {
                    "InvoiceLineID": invoice_line_id,
                    "InvoiceID": invoice_id,
                    "StockItemID": line["StockItemID"],
                    "Description": line["Description"],
                    "Quantity": -line["Quantity"],
                    "UnitPrice": line["UnitPrice"],
                    "TaxRate": line["TaxRate"],
                    "TaxAmount": -line["TaxAmount"],
                    "LineProfit": -line["LineProfit"],
                    "ExtendedPrice": -line["ExtendedPrice"],
                }
            )

    # --- Müşteri hesap hareketleri: her fatura/kredi notu için bir tane + bazı ödemeler; RunningTotal müşteri bazında.
    lines_by_invoice: dict[int, list[dict]] = {}
    for line in invoice_lines:
        lines_by_invoice.setdefault(line["InvoiceID"], []).append(line)
    invoice_by_id = {i["InvoiceID"]: i for i in invoices}
    raw = []
    for invoice in invoices:
        total = round(sum(l["ExtendedPrice"] for l in lines_by_invoice.get(invoice["InvoiceID"], [])), 4)
        credit = invoice["IsCreditNote"]
        raw.append((invoice["BillToCustomerID"], invoice["InvoiceDate"], 10 if credit else 1, invoice["InvoiceID"], total,
                    f"{'Credit note' if credit else 'Sales invoice'} {invoice['InvoiceID']}."))
        if not credit and rng.random() < 0.6:
            raw.append((invoice["BillToCustomerID"], _add_days(invoice["InvoiceDate"], rng.randint(5, 30)), 2, None, -total,
                        f"Customer payment received against invoice {invoice['InvoiceID']}."))
    raw.sort(key=lambda t: (t[1], t[3] if t[3] is not None else 0))
    running: dict[int, float] = {}
    customer_transactions = []
    for index, (customer_id, tx_date, type_id, inv_id, amount, description) in enumerate(raw, start=1):
        running[customer_id] = round(running.get(customer_id, 0.0) + amount, 4)
        customer_transactions.append(
            {
                "CustomerTransactionID": index,
                "CustomerID": customer_id,
                "TransactionDate": tx_date,
                "TransactionDescription": description,
                "TransactionTypeID": type_id,
                "InvoiceID": inv_id,
                "StockItemID": None,
                "AmountForTransaction": amount,
                "RunningTotal": running[customer_id],
            }
        )

    # --- Stok hareketleri: alış girişi (+), satış çıkışı (-), iade girişi (+), sayım/transfer; miktarlar işaretli.
    transactions = []
    tx_id = 0
    for line in dataset["Purchasing.PurchaseOrderLines"]:
        if line["ReceivedDate"] is None:
            continue
        tx_id += 1
        order = next(o for o in dataset["Purchasing.PurchaseOrders"] if o["PurchaseOrderID"] == line["PurchaseOrderID"])
        transactions.append(
            {
                "StockItemTransactionID": tx_id,
                "StockItemID": line["StockItemID"],
                "TransactionTypeID": 3,
                "InvoiceID": None,
                "OrderID": None,
                "PurchaseOrderID": line["PurchaseOrderID"],
                "CustomerID": None,
                "SupplierID": order["SupplierID"],
                "TransactionDate": line["ReceivedDate"],
                "Quantity": float(line["OrderQuantity"]),
                "CostPrice": line["UnitPrice"],
            }
        )
    for line in invoice_lines:
        invoice = invoice_by_id[line["InvoiceID"]]
        tx_id += 1
        transactions.append(
            {
                "StockItemTransactionID": tx_id,
                "StockItemID": line["StockItemID"],
                "TransactionTypeID": 10 if invoice["IsCreditNote"] else 1,
                "InvoiceID": line["InvoiceID"],
                "OrderID": None if invoice["IsCreditNote"] else invoice["OrderID"],
                "PurchaseOrderID": None,
                "CustomerID": invoice["CustomerID"],
                "SupplierID": None,
                "TransactionDate": _dt(invoice["InvoiceDate"], rng),
                "Quantity": float(line["Quantity"]),
                "CostPrice": buying_price[line["StockItemID"]],
            }
        )
    for item in items:
        for _ in range(rng.randint(2, 3)):
            tx_id += 1
            transactions.append(
                {
                    "StockItemTransactionID": tx_id,
                    "StockItemID": item["StockItemID"],
                    "TransactionTypeID": rng.choice([7, 8, 9]),
                    "InvoiceID": None,
                    "OrderID": None,
                    "PurchaseOrderID": None,
                    "CustomerID": None,
                    "SupplierID": None,
                    "TransactionDate": _dt(f"2016-{rng.randint(1, 5):02d}-{rng.randint(1, 27):02d}", rng),
                    "Quantity": float(rng.choice([-1, -1, 1]) * rng.randint(1, 15)),
                    "CostPrice": buying_price[item["StockItemID"]],
                }
            )

    # Eldeki stok hareketlerin işaretle toplamıyla tutarlı; negatif inmez (gerekirse denkleştirme girişi eklenir).
    net: dict[int, float] = {}
    for tx in transactions:
        net[tx["StockItemID"]] = round(net.get(tx["StockItemID"], 0.0) + tx["Quantity"], 4)
    holdings = []
    for item in items:
        on_hand = net.get(item["StockItemID"], 0.0)
        if on_hand < 0:
            tx_id += 1
            transactions.append(
                {
                    "StockItemTransactionID": tx_id,
                    "StockItemID": item["StockItemID"],
                    "TransactionTypeID": 9,
                    "InvoiceID": None,
                    "OrderID": None,
                    "PurchaseOrderID": None,
                    "CustomerID": None,
                    "SupplierID": None,
                    "TransactionDate": _dt("2016-05-28", rng),
                    "Quantity": -on_hand,
                    "CostPrice": buying_price[item["StockItemID"]],
                }
            )
            on_hand = 0.0
        reorder = rng.randint(10, 60)
        holdings.append(
            {
                "StockItemID": item["StockItemID"],
                "QuantityOnHand": int(round(on_hand)),
                "CommittedForOrders": rng.randint(0, 40),
                "BackorderQuantity": rng.randint(0, 20),
                "ReorderLevel": reorder,
                "TargetLevel": reorder + rng.randint(50, 200),
                "SafetyStockLevel": rng.randint(0, 30),
                "LastCostPrice": buying_price[item["StockItemID"]],
            }
        )

    dataset["Sales.Orders"] = orders
    dataset["Sales.OrderLines"] = order_lines
    dataset["Sales.Invoices"] = invoices
    dataset["Sales.InvoiceLines"] = invoice_lines
    dataset["Sales.CustomerTransactions"] = customer_transactions
    dataset["Warehouse.StockItemTransactions"] = transactions
    dataset["Warehouse.StockItemHoldings"] = holdings


def generate(seed: int) -> dict[str, list[dict]]:
    """Tohumun dünyası: her şema tablosuna bir anahtar, ana kayıtlar ve işlem tabloları dolu."""
    rng = random.Random(f"{seed}:wwi")

    countries = [
        {"CountryID": cid, "CountryName": name, "ISOAlpha2Code": iso, "Continent": continent}
        for cid, name, iso, continent in COUNTRIES
    ]

    people, sales, buyers, contacts = _people(rng)

    provinces = [
        {
            "StateProvinceID": index,
            "StateProvinceCode": code,
            "StateProvinceName": pname,
            "CountryID": country_id,
            "SalesPersonPersonID": rng.choice(sales),
        }
        for index, (code, pname, country_id) in enumerate(PROVINCES, start=1)
    ]

    city_pool = CITY_NAMES[:]
    rng.shuffle(city_pool)
    cities = []
    for city_id, province in enumerate([p for p in provinces for _ in range(2)], start=1):
        cities.append(
            {
                "CityID": city_id,
                "CityName": city_pool[city_id - 1],
                "StateProvinceID": province["StateProvinceID"],
                "CountryID": province["CountryID"],
            }
        )
    city_ids = [city["CityID"] for city in cities]

    delivery_methods = [
        {
            "DeliveryMethodID": index,
            "DeliveryMethodName": name,
            "LeadTimeDays": lead,
            "IsCashDelivery": cash,
        }
        for index, (name, lead, cash) in enumerate(DELIVERY_METHODS, start=1)
    ]
    delivery_ids = [method["DeliveryMethodID"] for method in delivery_methods]

    buying_groups = [
        {"BuyingGroupID": index, "BuyingGroupName": name}
        for index, name in enumerate(BUYING_GROUPS, start=1)
    ]

    # (CustomerID, CustomerName, BuyingGroupID): ilk iki kart aynı adı iki farklı grupta taşır,
    # 3 ve 4 bağımsız (NULL grup) - "bazı NULL BuyingGroupID" gereği.
    plan = [
        (1, SHARED_CUSTOMER_NAME, 1),
        (2, SHARED_CUSTOMER_NAME, 2),
        (3, CUSTOMER_NAMES[0], None),
        (4, CUSTOMER_NAMES[1], None),
    ]
    for customer_id in range(5, 11):
        plan.append((customer_id, CUSTOMER_NAMES[customer_id - 3], rng.choice([1, 2, 3, None])))

    head: dict[int, int] = {}
    for customer_id, _, group in plan:
        if group is not None:
            head[group] = min(head.get(group, customer_id), customer_id)

    customers = [
        {
            "CustomerID": customer_id,
            "CustomerName": name,
            "BillToCustomerID": head[group] if group is not None else customer_id,
            "CustomerCategory": rng.choice(CUSTOMER_CATEGORIES),
            "BuyingGroupID": group,
            "MarketCategory": rng.choice(MARKET_CATEGORIES),
            "PrimaryContactPersonID": rng.choice(contacts),
            "DeliveryMethodID": rng.choice(delivery_ids),
            "DeliveryCityID": rng.choice(city_ids),
            "PostalCityID": rng.choice(city_ids),
            "CreditLimit": round(rng.uniform(10000, 120000), 2),
            "AccountOpenedDate": _iso_date(rng, 2013, 2015),
            "StandardDiscountPercentage": round(rng.uniform(0, 30), 2),
            "IsStatementSendingAllowed": rng.randint(0, 1),
            "SalesPersonPersonID": rng.choice(sales + [None]),
            "PhoneNumber": _phone(rng),
            "FaxNumber": rng.choice([None, _phone(rng)]),
            "DeliveryAddressLine1": _address(rng),
            "DeliveryAddressLine2": rng.choice([None, f"Unit {rng.randint(1, 40)}"]),
            "PostalAddressLine1": _address(rng),
            "PostalAddressLine2": rng.choice([None, f"PO Box {rng.randint(100, 9999)}"]),
        }
        for customer_id, name, group in plan
    ]

    stock_groups = [
        {"StockGroupID": index, "StockGroupName": name}
        for index, name in enumerate(STOCK_GROUPS, start=1)
    ]

    suppliers = [
        {
            "SupplierID": index,
            "SupplierName": name,
            "SupplierCategory": rng.choice(SUPPLIER_CATEGORIES),
            "SupplierReference": rng.choice([None, f"WWI-{rng.randint(1000, 9999)}"]),
            "InternalContactPersonID": buyers[index - 1],
            "DeliveryMethodID": rng.choice(delivery_ids),
            "DeliveryCityID": rng.choice(city_ids),
            "PostalCityID": rng.choice(city_ids),
            "AccountOpenedDate": _iso_date(rng, 2012, 2015),
            "StandardDiscountPercentage": round(rng.uniform(0, 20), 2),
            "IsSupplierLocked": rng.randint(0, 1),
            "PhoneNumber": _phone(rng),
            "FaxNumber": rng.choice([None, _phone(rng)]),
            "DeliveryAddressLine1": _address(rng),
            "DeliveryAddressLine2": rng.choice([None, f"Unit {rng.randint(1, 40)}"]),
            "PostalAddressLine1": _address(rng),
            "PostalAddressLine2": rng.choice([None, f"PO Box {rng.randint(100, 9999)}"]),
        }
        for index, name in enumerate(SUPPLIER_NAMES, start=1)
    ]
    supplier_ids = [supplier["SupplierID"] for supplier in suppliers]

    stock_items = [
        {
            "StockItemID": index,
            "StockItemName": name,
            "SupplierID": rng.choice(supplier_ids),
            "ColorID": rng.choice([None] + list(range(1, 11))),
            "Brand": rng.choice(BRANDS),
            "Size": rng.choice(SIZES),
            "LeadTimeDays": rng.randint(1, 10),
            "QuantityPerOrder": rng.randint(1, 100),
            "BuyingPrice": round(rng.uniform(1, 50), 4),
            "TypicalWeightPerUnit": round(rng.uniform(0.05, 5), 6),
            "MarketingComments": rng.choice([None, "Best-selling line, restock weekly."]),
        }
        for index, name in enumerate(PRODUCT_NAMES, start=1)
    ]

    # 1 numaralı kalem iki grupta (R4-9 gereği); diğerleri bir ya da iki grupta.
    stock_item_stock_groups = []
    link_id = 0
    for group_id in (1, 2):
        link_id += 1
        stock_item_stock_groups.append(
            {"StockItemStockGroupID": link_id, "StockItemID": 1, "StockGroupID": group_id}
        )
    for item_id in range(2, len(PRODUCT_NAMES) + 1):
        for group_id in rng.sample([1, 2, 3, 4], rng.randint(1, 2)):
            link_id += 1
            stock_item_stock_groups.append(
                {"StockItemStockGroupID": link_id, "StockItemID": item_id, "StockGroupID": group_id}
            )

    dataset = {
        "Application.Countries": countries,
        "Application.StateProvinces": provinces,
        "Application.Cities": cities,
        "Application.DeliveryMethods": delivery_methods,
        "Application.People": people,
        "Sales.BuyingGroups": buying_groups,
        "Sales.Customers": customers,
        "Sales.Orders": [],
        "Sales.OrderLines": [],
        "Sales.Invoices": [],
        "Sales.InvoiceLines": [],
        "Sales.CustomerTransactions": [],
        "Warehouse.StockGroups": stock_groups,
        "Warehouse.StockItems": stock_items,
        "Warehouse.StockItemStockGroups": stock_item_stock_groups,
        "Warehouse.StockItemTransactions": [],
        "Warehouse.StockItemHoldings": [],
        "Purchasing.Suppliers": suppliers,
        "Purchasing.PurchaseOrders": [],
        "Purchasing.PurchaseOrderLines": [],
    }
    purchase_orders, purchase_order_lines = _purchase_orders(rng, dataset)
    dataset["Purchasing.PurchaseOrders"] = purchase_orders
    dataset["Purchasing.PurchaseOrderLines"] = purchase_order_lines
    _sales(rng, dataset)
    return dataset


def build_db(seed: int, db_path, sql_path) -> str:
    """Kümenin iki fiziksel hedefini de kurar; SQLite sağlama toplamını döndürür."""
    dataset = generate(seed)
    schema = doc.load_schema(SCHEMA_PATH)
    build.write_sqlite(dataset, schema, db_path)
    build.write_mssql_script(dataset, schema, sql_path)
    return build.checksum(db_path)
