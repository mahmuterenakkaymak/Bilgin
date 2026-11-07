# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T04: belge tablolarının şekli, tüm tablolar arası FK bütünlüğü ve tuzakların her tohumda kurulduğu."""

import functools
from collections import defaultdict

import pytest

from nl2sql import config
from nl2sql.schema_map import doc, generator

DOC_TABLES = ["TBLFATUIRS", "TBLSTHAR", "TBLCAHAR", "TBLSIPAMAS", "TBLSIPATRA"]
ALL_TABLES = ["TBLSTGRUP", "TBLSTSABIT", "TBLDEPO", "TBLPLASIYER", "TBLCASABIT"] + DOC_TABLES
PRIMARY_KEYS = {
    "TBLFATUIRS": "FATIRS_NO",
    "TBLSTHAR": "STHAR_ID",
    "TBLCAHAR": "CAHAR_ID",
    "TBLSIPAMAS": "SIPARIS_NO",
    "TBLSIPATRA": "SIPATRA_ID",
}
DATE_COLUMNS = [
    ("TBLFATUIRS", "TARIH"),
    ("TBLSTHAR", "STHAR_TARIH"),
    ("TBLCAHAR", "TARIH"),
    ("TBLSIPAMAS", "TARIH"),
    ("TBLSIPATRA", "TESLIM_TARIHI"),
]
OPTIONAL_COLUMNS = [
    ("TBLSTHAR", "STHAR_NF"),
    ("TBLSTHAR", "FISNO"),
    ("TBLSTHAR", "CARI_KODU"),
    ("TBLCAHAR", "FISNO"),
    ("TBLCAHAR", "ACIKLAMA"),
    ("TBLSIPATRA", "TESLIM_TARIHI"),
]
PERIOD = ("2026-06-01", "2026-09-30")
SEEDS = [1, 7, 42, 2026]


@functools.lru_cache(maxsize=None)
def data(seed):
    return generator.generate(seed)


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def columns_by_table(schema):
    return {table["name"]: [c["name"] for c in table["columns"]] for table in schema["tables"]}


@pytest.fixture(scope="module")
def foreign_keys(schema):
    return [
        (table["name"], column["name"], column["fk"])
        for table in schema["tables"]
        for column in table["columns"]
        if column["fk"]
    ]


def invoices(dataset):
    return {row["FATIRS_NO"]: row for row in dataset["TBLFATUIRS"]}


def lines_of(dataset, fisno):
    return [row for row in dataset["TBLSTHAR"] if row["FISNO"] == fisno]


# ----------------------------------------------------------------- shape


@pytest.mark.parametrize("seed", SEEDS)
def test_document_tables_are_present_and_filled(seed):
    dataset = data(seed)
    for name in ALL_TABLES:
        assert dataset.get(name), name


@pytest.mark.parametrize("seed", SEEDS)
def test_row_keys_equal_schema_columns_in_order(seed, columns_by_table):
    for name in DOC_TABLES:
        for row in data(seed)[name]:
            assert list(row) == columns_by_table[name], name


@pytest.mark.parametrize("seed", SEEDS)
def test_values_are_plain_scalars(seed):
    for name in DOC_TABLES:
        for row in data(seed)[name]:
            for column, value in row.items():
                assert value is None or isinstance(value, (int, float, str)), (name, column, value)


@pytest.mark.parametrize("seed", SEEDS)
def test_primary_keys_unique(seed):
    for name, key in PRIMARY_KEYS.items():
        codes = [row[key] for row in data(seed)[name]]
        assert len(set(codes)) == len(codes), name


@pytest.mark.parametrize("seed", SEEDS)
def test_required_columns_are_never_null(seed, schema):
    for table in schema["tables"]:
        if table["name"] not in DOC_TABLES:
            continue
        for column in table["columns"]:
            if column["nullable"]:
                continue
            for row in data(seed)[table["name"]]:
                assert row[column["name"]] is not None, (table["name"], column["name"])


@pytest.mark.parametrize("seed", SEEDS)
def test_optional_columns_carry_nulls_and_values(seed):
    for table, column in OPTIONAL_COLUMNS:
        seen = {row[column] for row in data(seed)[table]}
        assert None in seen, (table, column)
        assert len(seen) > 1, (table, column)


@pytest.mark.parametrize("seed", SEEDS)
def test_coded_columns_stay_within_the_schema_doc(seed, schema):
    for table in schema["tables"]:
        if table["name"] not in DOC_TABLES:
            continue
        for column in table["columns"]:
            if not column["values"]:
                continue
            seen = {
                str(row[column["name"]]) for row in data(seed)[table["name"]] if row[column["name"]] is not None
            }
            assert seen <= set(column["values"]), (table["name"], column["name"], seen)


@pytest.mark.parametrize("seed", SEEDS)
def test_all_three_invoice_types_exist(seed):
    assert {row["FTIRSIP"] for row in data(seed)["TBLFATUIRS"]} == {1, 2, 3}


@pytest.mark.parametrize("seed", SEEDS)
def test_movements_stay_inside_the_measurement_period(seed):
    assert PERIOD[1] == config.AS_OF
    for table, column in DATE_COLUMNS:
        for row in data(seed)[table]:
            value = row[column]
            if value is None:
                continue
            assert PERIOD[0] <= value <= PERIOD[1], (table, column, value)


@pytest.mark.parametrize("seed", SEEDS)
def test_movement_volume_is_a_few_hundred(seed):
    assert 200 <= len(data(seed)["TBLSTHAR"]) <= 900


# ----------------------------------------------------------------- relations


@pytest.mark.parametrize("seed", SEEDS)
def test_every_foreign_key_resolves(seed, foreign_keys):
    dataset = data(seed)
    for table, column, reference in foreign_keys:
        target_table, target_column = reference.split(".")
        allowed = {row[target_column] for row in dataset[target_table]}
        values = [row[column] for row in dataset[table]]
        assert not values or any(value is not None for value in values), (table, column)
        for value in values:
            assert value is None or value in allowed, (table, column, value)


@pytest.mark.parametrize("seed", SEEDS)
def test_movement_type_matches_its_direction(seed):
    yon = {"S": {"C"}, "A": {"G"}, "I": {"G"}, "D": {"G"}, "T": {"C", "G"}}
    for hareket in data(seed)["TBLSTHAR"]:
        assert hareket["STHAR_GCKOD"] in yon[hareket["STHAR_HTUR"]], hareket


@pytest.mark.parametrize("seed", SEEDS)
def test_invoice_movements_share_the_invoice_cari_and_date(seed):
    belgeler = invoices(data(seed))
    for hareket in data(seed)["TBLSTHAR"]:
        if hareket["FISNO"] is None:
            continue
        belge = belgeler[hareket["FISNO"]]
        assert hareket["CARI_KODU"] == belge["CARI_KODU"], hareket
        assert hareket["STHAR_TARIH"] == belge["TARIH"], hareket


@pytest.mark.parametrize("seed", SEEDS)
def test_every_valid_invoice_has_lines_with_a_positive_total(seed):
    dataset = data(seed)
    for belge in dataset["TBLFATUIRS"]:
        if belge["IPTAL"] == "H":
            assert lines_of(dataset, belge["FATIRS_NO"]), belge
        assert belge["GENELTOPLAM"] > 0, belge


@pytest.mark.parametrize("seed", SEEDS)
def test_header_total_matches_the_sum_of_its_lines(seed):
    dataset = data(seed)
    kdv = {row["STOK_KODU"]: row["KDV_ORANI"] for row in dataset["TBLSTSABIT"]}
    for belge in dataset["TBLFATUIRS"]:
        satirlar = lines_of(dataset, belge["FATIRS_NO"])
        if not satirlar:
            continue
        beklenen = sum(
            round(round(h["STHAR_GCMIK"] * h["STHAR_NF"], 2) * (1 + kdv[h["STOK_KODU"]] / 100.0), 2)
            for h in satirlar
        )
        assert abs(beklenen - belge["GENELTOPLAM"]) < 0.01, belge


@pytest.mark.parametrize("seed", SEEDS)
def test_cari_cards_come_from_invoices_and_manual_entries(seed):
    kayitlar = data(seed)["TBLCAHAR"]
    assert any(row["FISNO"] is not None for row in kayitlar)
    assert any(row["FISNO"] is None for row in kayitlar)
    assert {row["BA"] for row in kayitlar} == {"B", "A"}
    assert all(row["TUTAR"] > 0 for row in kayitlar)


# ----------------------------------------------------------------- traps


@pytest.mark.parametrize("seed", SEEDS)
def test_sales_returns_exist_as_incoming_movements(seed):
    dataset = data(seed)
    belgeler = invoices(dataset)
    iadeler = [row for row in dataset["TBLSTHAR"] if row["STHAR_HTUR"] == "I"]
    assert iadeler
    assert all(row["STHAR_GCKOD"] == "G" for row in iadeler)
    assert all(belgeler[row["FISNO"]]["FTIRSIP"] == 3 for row in iadeler)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_product_has_a_high_and_a_low_return_ratio(seed):
    dataset = data(seed)
    satis = defaultdict(float)
    iade = defaultdict(float)
    for hareket in dataset["TBLSTHAR"]:
        if hareket["STHAR_HTUR"] == "S":
            satis[hareket["STOK_KODU"]] += hareket["STHAR_GCMIK"]
        elif hareket["STHAR_HTUR"] == "I":
            iade[hareket["STOK_KODU"]] += hareket["STHAR_GCMIK"]
    oran = {kod: iade[kod] / miktar for kod, miktar in satis.items() if miktar}
    assert any(deger > 0.10 for deger in oran.values()), oran
    assert any(0 < deger < 0.10 for deger in oran.values()), oran
    assert all(iade[kod] <= satis[kod] + 0.01 for kod in satis), (dict(satis), dict(iade))


@pytest.mark.parametrize("seed", SEEDS)
def test_cancelled_invoices_are_priced_but_have_no_movements(seed):
    dataset = data(seed)
    iptaller = [row for row in dataset["TBLFATUIRS"] if row["IPTAL"] == "E"]
    assert iptaller
    assert any(row["TARIH"].startswith("2026-09") for row in iptaller), "Eylül'de iptal fatura yok"
    assert all(row["GENELTOPLAM"] > 0 for row in iptaller)
    assert all(not lines_of(dataset, row["FATIRS_NO"]) for row in iptaller)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_product_is_sold_from_several_depots_in_september(seed):
    depolar = defaultdict(set)
    for hareket in data(seed)["TBLSTHAR"]:
        if hareket["STHAR_HTUR"] == "S" and hareket["STHAR_TARIH"].startswith("2026-09"):
            depolar[hareket["STOK_KODU"]].add(hareket["DEPO_KODU"])
    assert any(len(küme) >= 2 for küme in depolar.values()), dict(depolar)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_product_carries_several_net_prices_in_august(seed):
    fiyatlar = defaultdict(set)
    for hareket in data(seed)["TBLSTHAR"]:
        if hareket["STHAR_TARIH"].startswith("2026-08") and hareket["STHAR_NF"] is not None:
            fiyatlar[hareket["STOK_KODU"]].add(hareket["STHAR_NF"])
    assert any(len(küme) >= 2 for küme in fiyatlar.values()), dict(fiyatlar)


@pytest.mark.parametrize("seed", SEEDS)
def test_a_both_types_cari_has_sales_and_purchases(seed):
    dataset = data(seed)
    tipler = {row["CARI_KOD"]: row["CARI_TIP"] for row in dataset["TBLCASABIT"]}
    gecerli = [row for row in dataset["TBLFATUIRS"] if row["IPTAL"] == "H"]
    satis = {row["CARI_KODU"] for row in gecerli if row["FTIRSIP"] == 1}
    alis = {row["CARI_KODU"] for row in gecerli if row["FTIRSIP"] == 2}
    assert {kod for kod in satis & alis if tipler[kod] == "H"}, "H tipli caride hem satış hem alış yok"


@pytest.mark.parametrize("seed", SEEDS)
def test_transfers_and_counts_have_no_invoice(seed):
    dataset = data(seed)
    transfers = [row for row in dataset["TBLSTHAR"] if row["STHAR_HTUR"] == "T"]
    assert transfers
    assert all(row["FISNO"] is None and row["CARI_KODU"] is None and row["STHAR_NF"] is None for row in transfers)
    cikis = sum(1 for row in transfers if row["STHAR_GCKOD"] == "C")
    giris = sum(1 for row in transfers if row["STHAR_GCKOD"] == "G")
    assert cikis == giris, (cikis, giris)
    sayim = [row for row in dataset["TBLSTHAR"] if row["STHAR_HTUR"] == "D"]
    assert sayim
    assert all(row["FISNO"] is None and row["STHAR_GCKOD"] == "G" for row in sayim)
    faturasiz_giris = [
        row for row in dataset["TBLSTHAR"] if row["STHAR_GCKOD"] == "G" and row["FISNO"] is None
    ]
    assert len(faturasiz_giris) >= 10, len(faturasiz_giris)


@pytest.mark.parametrize("seed", SEEDS)
def test_an_invoice_has_at_least_three_lines(seed):
    dataset = data(seed)
    adetler = [len(lines_of(dataset, row["FATIRS_NO"])) for row in dataset["TBLFATUIRS"]]
    assert max(adetler) >= 3, adetler


@pytest.mark.parametrize("seed", SEEDS)
def test_order_lines_without_a_delivery_date(seed):
    dataset = data(seed)
    cariler = {row["SIPARIS_NO"]: row["CARI_KODU"] for row in dataset["TBLSIPAMAS"]}
    belirsiz = {cariler[row["SIPARIS_NO"]] for row in dataset["TBLSIPATRA"] if row["TESLIM_TARIHI"] is None}
    belirli = {cariler[row["SIPARIS_NO"]] for row in dataset["TBLSIPATRA"] if row["TESLIM_TARIHI"] is not None}
    assert len(belirsiz) >= 3, belirsiz
    assert belirsiz & belirli, "hiç caride hem belirsiz hem belirli satır yok"


@pytest.mark.parametrize("seed", SEEDS)
def test_order_header_matches_its_lines(seed):
    dataset = data(seed)
    kdv = {row["STOK_KODU"]: row["KDV_ORANI"] for row in dataset["TBLSTSABIT"]}
    for siparis in dataset["TBLSIPAMAS"]:
        satirlar = [row for row in dataset["TBLSIPATRA"] if row["SIPARIS_NO"] == siparis["SIPARIS_NO"]]
        assert satirlar, siparis
        beklenen = sum(
            round(row["TUTAR"] * (1 + kdv[row["STOK_KODU"]] / 100.0), 2) for row in satirlar
        )
        assert abs(beklenen - siparis["TOPLAM_TUTAR"]) < 0.01, siparis
        for row in satirlar:
            assert abs(row["TUTAR"] - round(row["MIKTAR"] * row["BIRIM_FIYAT"], 2)) < 0.01, row
