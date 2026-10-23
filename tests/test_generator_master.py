import inspect
import random

import pytest

from nl2sql import config
from nl2sql.schema_map import doc, generator

MASTER_TABLES = ["TBLSTGRUP", "TBLSTSABIT", "TBLDEPO", "TBLPLASIYER", "TBLCASABIT"]
PRIMARY_KEYS = {
    "TBLSTGRUP": "GRUP_KODU",
    "TBLSTSABIT": "STOK_KODU",
    "TBLDEPO": "DEPO_KODU",
    "TBLPLASIYER": "PLASIYER_KODU",
    "TBLCASABIT": "CARI_KOD",
}
NAME_COLUMNS = {
    "TBLSTGRUP": "GRUP_ISIMI",
    "TBLSTSABIT": "STOK_ADI",
    "TBLDEPO": "DEPO_ISIMI",
    "TBLPLASIYER": "AD_SOYAD",
    "TBLCASABIT": "CARI_ISIM",
}
OPTIONAL_COLUMNS = [
    ("TBLSTGRUP", "ACIKLAMA"),
    ("TBLSTSABIT", "BIRIM_FIYAT"),
    ("TBLDEPO", "IL"),
    ("TBLPLASIYER", "IL"),
    ("TBLPLASIYER", "TELEFON"),
    ("TBLCASABIT", "PLASIYER_KODU"),
]


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def columns_by_table(schema):
    return {table["name"]: [c["name"] for c in table["columns"]] for table in schema["tables"]}


@pytest.fixture(scope="module")
def dataset():
    return generator.generate()


def values_of(dataset, table, column):
    return [row[column] for row in dataset[table]]


# ----------------------------------------------------------------- determinism


def test_same_seed_gives_equal_dataset():
    assert generator.generate(7) == generator.generate(7)


def test_different_seed_gives_different_dataset():
    base = generator.generate(1)
    assert base != generator.generate(2)
    assert base != generator.generate(3)


def test_default_seed_is_config_seed():
    assert inspect.signature(generator.generate).parameters["seed"].default == config.SEED
    assert generator.generate() == generator.generate(config.SEED)


def test_generator_has_its_own_random():
    random.seed(1234)
    first = generator.generate(5)
    random.seed(987654)
    assert generator.generate(5) == first


# ----------------------------------------------------------------- shape


def test_master_tables_are_present_and_filled(dataset):
    for name in MASTER_TABLES:
        assert name in dataset, name
        assert dataset[name], name


def test_row_keys_equal_schema_columns_in_order(dataset, columns_by_table):
    for name in MASTER_TABLES:
        for row in dataset[name]:
            assert list(row) == columns_by_table[name], name


def test_values_are_plain_scalars(dataset):
    for name in MASTER_TABLES:
        for row in dataset[name]:
            for column, value in row.items():
                assert value is None or isinstance(value, (int, float, str)), (name, column, value)


def test_names_are_non_empty_text(dataset):
    for name, column in NAME_COLUMNS.items():
        for value in values_of(dataset, name, column):
            assert isinstance(value, str) and value.strip(), (name, value)


# ----------------------------------------------------------------- keys and relations


def test_primary_keys_unique(dataset):
    for name, key in PRIMARY_KEYS.items():
        codes = values_of(dataset, name, key)
        assert len(set(codes)) == len(codes), name


def test_foreign_keys_resolve(dataset):
    groups = set(values_of(dataset, "TBLSTGRUP", "GRUP_KODU"))
    assert set(values_of(dataset, "TBLSTSABIT", "GRUP_KODU")) <= groups
    reps = set(values_of(dataset, "TBLPLASIYER", "PLASIYER_KODU"))
    assigned = {v for v in values_of(dataset, "TBLCASABIT", "PLASIYER_KODU") if v is not None}
    assert assigned <= reps
    assert assigned, "hiç cariye plasiyer atanmamış"


def test_required_columns_are_never_null(dataset, schema):
    for table in schema["tables"]:
        if table["name"] not in MASTER_TABLES:
            continue
        for column in table["columns"]:
            if column["nullable"]:
                continue
            for value in values_of(dataset, table["name"], column["name"]):
                assert value is not None, (table["name"], column["name"])


def test_optional_columns_carry_nulls_and_values(dataset):
    for table, column in OPTIONAL_COLUMNS:
        seen = set(values_of(dataset, table, column))
        assert None in seen, (table, column)
        assert len(seen) > 1, (table, column)


# ----------------------------------------------------------------- coded values


def test_coded_columns_stay_within_the_schema_doc(dataset, schema):
    for table in schema["tables"]:
        if table["name"] not in MASTER_TABLES:
            continue
        for column in table["columns"]:
            if not column["values"]:
                continue
            seen = {value for value in values_of(dataset, table["name"], column["name"]) if value is not None}
            assert seen <= set(column["values"]), (table["name"], column["name"], seen)


def test_cari_tip_covers_buyers_sellers_and_both(dataset):
    assert {value for value in values_of(dataset, "TBLCASABIT", "CARI_TIP")} == {"A", "S", "H"}


def test_products_use_documented_units_and_vat(dataset):
    assert set(values_of(dataset, "TBLSTSABIT", "OLCU_BR1")) <= {"ADET", "KG", "M"}
    assert set(values_of(dataset, "TBLSTSABIT", "KDV_ORANI")) <= {10.0, 20.0}


def test_card_prices_are_positive_two_decimal_amounts(dataset):
    for value in values_of(dataset, "TBLSTSABIT", "BIRIM_FIYAT"):
        if value is None:
            continue
        assert round(value, 2) == value, value
        assert 0.0 < value < 10000.0, value


def test_at_least_one_passive_card_exists(dataset):
    assert "H" in set(values_of(dataset, "TBLSTSABIT", "AKTIF"))


# ----------------------------------------------------------------- trap support


def test_several_cities_each_with_a_buyer(dataset):
    cities = set(values_of(dataset, "TBLCASABIT", "IL"))
    assert len(cities) >= 5
    assert "ANKARA" in cities
    assert all(city.isupper() for city in cities), cities
    buyers = {row["IL"] for row in dataset["TBLCASABIT"] if row["CARI_TIP"] == "A"}
    assert cities <= buyers


def test_several_depots_with_one_default(dataset):
    assert len(dataset["TBLDEPO"]) >= 3
    assert sum(1 for row in dataset["TBLDEPO"] if row["VARSAYILAN"] == "E") == 1
