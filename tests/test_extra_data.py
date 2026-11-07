# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T34: Run 2 ek verisi — FK'lar Run 1 tablolarına bağlanır, tohum deterministiktir, şekiller kurulur."""

import datetime as dt
from collections import defaultdict

import pytest

from bilgin.schema_map import doc, extra, generator

EXTRA_TABLES = ("TBLSTOKFIAT", "TBLDOVKUR", "TBLCARISUBE", "TBLKAMPANYA")
RUN1_TABLES = (
    "TBLSTGRUP",
    "TBLSTSABIT",
    "TBLDEPO",
    "TBLPLASIYER",
    "TBLCASABIT",
    "TBLFATUIRS",
    "TBLSTHAR",
    "TBLCAHAR",
    "TBLSIPAMAS",
    "TBLSIPATRA",
)
OLCUM = ("2026-06-01", "2026-09-30")
SEEDS = [1, 7, 42, 2026]


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def columns_by_table(schema):
    return {table["name"]: [c["name"] for c in table["columns"]] for table in schema["tables"]}


@pytest.fixture(scope="module")
def dataset():
    return generator.generate(42)


def values(rows, column):
    return [row[column] for row in rows]


def list_price_changes(dataset):
    """Satış (S) fiyatı Haziran-Eylül 2026 içinde değişen ürün kodları."""
    satis = defaultdict(list)
    for row in dataset["TBLSTOKFIAT"]:
        if row["FIYAT_TIPI"] == "S":
            satis[row["STOK_KODU"]].append((row["GECERLILIK_TARIHI"], row["FIYAT"]))
    degisen = set()
    for kod, satirlar in satis.items():
        for t1, f1 in satirlar:
            for t2, f2 in satirlar:
                if t1 < t2 and OLCUM[0] <= t2 <= OLCUM[1] and f1 != f2:
                    degisen.add(kod)
    return degisen


# ----------------------------------------------------------------- determinism


@pytest.mark.parametrize("seed", SEEDS)
def test_same_seed_replays_the_extra_rows(seed):
    a, b = generator.generate(seed), generator.generate(seed)
    for name in EXTRA_TABLES:
        assert a[name] == b[name], name


def test_a_different_seed_changes_the_extra_rows():
    a, b = generator.generate(7), generator.generate(8)
    assert any(a[name] != b[name] for name in EXTRA_TABLES)


def test_extend_never_touches_the_run1_rows():
    dataset = generator.generate(42)
    once = {name: [{**row} for row in dataset[name]] for name in RUN1_TABLES}
    extra.extend(dataset, 42)
    assert {name: dataset[name] for name in RUN1_TABLES} == once


# ----------------------------------------------------------------- shape


@pytest.mark.parametrize("name", EXTRA_TABLES)
def test_row_keys_are_the_schema_columns_in_order(dataset, columns_by_table, name):
    assert dataset[name], name
    for row in dataset[name]:
        assert list(row) == columns_by_table[name], name


@pytest.mark.parametrize("name", EXTRA_TABLES)
def test_values_are_plain_scalars(dataset, name):
    for row in dataset[name]:
        for column, value in row.items():
            assert value is None or isinstance(value, (int, float, str)), (name, column, value)


# ----------------------------------------------------------------- foreign keys


def test_price_rows_point_at_real_products(dataset):
    urunler = set(values(dataset["TBLSTSABIT"], "STOK_KODU"))
    assert set(values(dataset["TBLSTOKFIAT"], "STOK_KODU")) <= urunler


def test_branches_point_at_real_caris(dataset):
    cariler = set(values(dataset["TBLCASABIT"], "CARI_KOD"))
    assert set(values(dataset["TBLCARISUBE"], "CARI_KOD")) <= cariler


def test_campaigns_point_at_real_products(dataset):
    urunler = set(values(dataset["TBLSTSABIT"], "STOK_KODU"))
    assert set(values(dataset["TBLKAMPANYA"], "STOK_KODU")) <= urunler


def test_primary_keys_are_unique(dataset):
    for name, key in [("TBLSTOKFIAT", "FIAT_ID"), ("TBLCARISUBE", "SUBE_KODU"), ("TBLKAMPANYA", "KAMPANYA_KODU")]:
        kodlar = values(dataset[name], key)
        assert len(set(kodlar)) == len(kodlar), name


# ----------------------------------------------------------------- TBLSTOKFIAT


def test_every_product_has_two_to_four_price_rows(dataset):
    adet = defaultdict(int)
    for row in dataset["TBLSTOKFIAT"]:
        adet[row["STOK_KODU"]] += 1
    assert set(adet) == {row["STOK_KODU"] for row in dataset["TBLSTSABIT"]}
    assert all(2 <= n <= 4 for n in adet.values()), dict(adet)


def test_price_type_and_effective_date_stay_in_range(dataset):
    for row in dataset["TBLSTOKFIAT"]:
        assert row["FIYAT_TIPI"] in {"S", "A"}, row
        assert "2025-01-01" <= row["GECERLILIK_TARIHI"] <= "2026-09-30", row
        assert row["FIYAT"] > 0, row


def test_a_product_list_price_changes_inside_the_window(dataset):
    assert list_price_changes(dataset), "Hiçbir ürünün liste fiyatı Haziran-Eylül 2026 içinde değişmedi"


# ----------------------------------------------------------------- TBLDOVKUR


def test_daily_rates_cover_every_day_for_both_currencies(dataset):
    gorulen = defaultdict(set)
    for row in dataset["TBLDOVKUR"]:
        assert row["DOVIZ_KODU"] in {"USD", "EUR"}, row
        assert OLCUM[0] <= row["KUR_TARIH"] <= OLCUM[1], row
        assert 0 < row["ALIS"] < row["SATIS"], row
        gorulen[row["KUR_TARIH"]].add(row["DOVIZ_KODU"])
    gun = dt.date.fromisoformat(OLCUM[0])
    while gun <= dt.date.fromisoformat(OLCUM[1]):
        assert gorulen[gun.isoformat()] == {"USD", "EUR"}, gun
        gun += dt.timedelta(days=1)


def test_one_rate_row_per_day_and_currency(dataset):
    anahtar = [(row["KUR_TARIH"], row["DOVIZ_KODU"]) for row in dataset["TBLDOVKUR"]]
    assert len(set(anahtar)) == len(anahtar)


# ----------------------------------------------------------------- TBLCARISUBE


def test_branch_count_per_cari_stays_within_three(dataset):
    adet = defaultdict(int)
    for row in dataset["TBLCARISUBE"]:
        adet[row["CARI_KOD"]] += 1
    assert all(1 <= n <= 3 for n in adet.values()), dict(adet)


def test_branch_cities_come_from_the_city_list(dataset):
    assert set(values(dataset["TBLCARISUBE"], "IL")) <= set(generator.CITIES)


def test_a_cari_has_a_branch_outside_its_own_city(dataset):
    il = {row["CARI_KOD"]: row["IL"] for row in dataset["TBLCASABIT"]}
    assert any(row["IL"] != il[row["CARI_KOD"]] for row in dataset["TBLCARISUBE"]), "her şube carinin kendi ilinde"


def test_a_closed_branch_exists(dataset):
    aktifler = set(values(dataset["TBLCARISUBE"], "AKTIF"))
    assert aktifler <= {"E", "H"}
    assert "H" in aktifler


# ----------------------------------------------------------------- TBLKAMPANYA


def test_between_five_and_eight_campaigns(dataset):
    assert 5 <= len(dataset["TBLKAMPANYA"]) <= 8


def test_campaigns_sit_inside_the_window_with_a_valid_discount(dataset):
    for row in dataset["TBLKAMPANYA"]:
        assert OLCUM[0] <= row["BASLANGIC"] <= row["BITIS"] <= OLCUM[1], row
        assert 5 <= row["INDIRIM_ORANI"] <= 30, row
