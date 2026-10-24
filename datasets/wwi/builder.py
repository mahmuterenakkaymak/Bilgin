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


def generate(seed: int) -> dict[str, list[dict]]:
    """Tohumun dünyası: her şema tablosuna bir anahtar, ana kayıtlar dolu, işlem tabloları boş."""
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

    return {
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
