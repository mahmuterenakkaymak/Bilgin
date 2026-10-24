"""T140: WWI kuralları ve join profili (PLAN R4-9).

Kural dosyası `rules.load_rules` ile Contracts varsayılanlarını alarak yüklenir, profil
`load_profile` ile doğrulanır; ikisi de `build_graph`'a verilince şemanın fk'ları ile birleşen
join graphı üç taşıyıcı bağlantıyı kurar. Python'da ERP kuralı yok - adları dosyalar söyler.
"""

import re

from nl2sql.datasets import load_dataset
from nl2sql.graph.graph import build_graph
from nl2sql.graph.profile import load_profile
from nl2sql.schema_map import rules

DATASET = load_dataset("wwi")
SCHEMA = DATASET.schema()
RULES = rules.load_rules(DATASET.rules_path)
PROFILE = load_profile(DATASET.profile_path)
GRAPH = build_graph(SCHEMA, PROFILE)
TABLE_NAMES = {table["name"] for table in SCHEMA["tables"]}
COLUMNS = {column["name"] for table in SCHEMA["tables"] for column in table["columns"]}

# R4-9: Q01-Q26'nın kuracağı on iş terimi.
R4_9_RULE_IDS = [
    "ciro",
    "net_satis",
    "brut_kar",
    "eldeki_stok",
    "geciken_teslimat",
    "faturalanmamis_siparis",
    "geri_siparis",
    "alacak_bakiye",
    "gecen_ay",
    "bu_yil",
]

# R4-9: profilin taşıyacağı on bir kolon çifti.
R4_9_PAIRS = {
    ("CustomerID", "CustomerID"),
    ("StockItemID", "StockItemID"),
    ("SupplierID", "SupplierID"),
    ("OrderID", "OrderID"),
    ("InvoiceID", "InvoiceID"),
    ("PurchaseOrderID", "PurchaseOrderID"),
    ("DeliveryMethodID", "DeliveryMethodID"),
    ("SalespersonPersonID", "PersonID"),
    ("PrimaryContactPersonID", "PersonID"),
    ("DeliveryCityID", "CityID"),
    ("PostalCityID", "CityID"),
}

# build_graph'ın kurması beklenen üç bağlantı (fk + profil birleşimi).
REQUIRED_PATHS = [
    ("Sales.Invoices", "Application.People"),
    ("Sales.Customers", "Application.Countries"),
    ("Purchasing.Suppliers", "Warehouse.StockItems"),
]


# ------------------------------------------------------------------ rules

def test_rules_load_through_the_loader_with_contract_defaults():
    assert RULES, "kural dosyası boş"
    for rule in RULES:
        assert rule["id"].strip()
        assert rule["term"].strip()
        assert rule["definition"].strip()
        assert isinstance(rule["sql_hint"], str)
        for field in ("synonyms", "tables", "markers"):
            assert isinstance(rule[field], list)


def test_dataset_rules_helper_matches_the_loader():
    assert DATASET.rules() == RULES


def test_rule_ids_are_the_r4_9_terms():
    assert [rule["id"] for rule in RULES] == R4_9_RULE_IDS


def test_rule_ids_are_unique():
    ids = [rule["id"] for rule in RULES]
    assert len(ids) == len(set(ids))


def test_every_rule_table_is_in_the_wwi_schema():
    for rule in RULES:
        assert rule["tables"], f"{rule['id']} tablosuz"
        for table in rule["tables"]:
            assert table in TABLE_NAMES, f"{rule['id']} -> {table}"


def test_every_marker_compiles_and_is_not_blank():
    for rule in RULES:
        assert rule["markers"], f"{rule['id']} işaretcisiz"
        for marker in rule["markers"]:
            assert marker.strip(), f"{rule['id']} boş işaretçi"
            re.compile(marker)


# ------------------------------------------------------------------ profile

def test_load_profile_is_valid():
    assert PROFILE, "profil boş"
    for pair in PROFILE:
        assert 0 < pair["confidence"] < 1


def test_profile_pairs_are_the_r4_9_pairs():
    assert {(pair["left"], pair["right"]) for pair in PROFILE} == R4_9_PAIRS


def test_every_profile_pair_names_a_column_the_schema_has():
    for pair in PROFILE:
        assert pair["left"] in COLUMNS, pair["left"]
        assert pair["right"] in COLUMNS, pair["right"]


# ------------------------------------------------------------------ graph

def test_the_graph_connects_the_required_tables():
    for start, target in REQUIRED_PATHS:
        path = GRAPH.find_join_path([start, target])
        assert start in path.tables and target in path.tables, (start, target)
