# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T35: 2025 stok arşivi ve muhasebe fişleri — tarih ve kodlar şema sınırında, fişler faturaya bağlı."""

import re
from collections import defaultdict

import pytest

from bilgin.schema_map import doc, generator

ARSIV = "TBLSTHAR_ARSIV"
MUHFIS = "TBLMUHFIS"
EYLUL = ("2026-09-01", "2026-09-30")
# Fatura tipinin gelir hesabı ve yönü; TBLSTHAR'ın hareket tipi/çıkış-giriş eşleşmesi (T hariç).
HESAP = {1: "600", 2: "153", 3: "610"}
YON = {1: "A", 2: "B", 3: "B"}
GCKOD = {"S": "C", "A": "G", "I": "G", "D": "G"}
SEEDS = [1, 7, 42, 2026]


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def columns_by_table(schema):
    return {table["name"]: [c["name"] for c in table["columns"]] for table in schema["tables"]}


@pytest.fixture(scope="module")
def coded_values(schema):
    return {
        (table["name"], column["name"]): set(column.get("values") or {})
        for table in schema["tables"]
        for column in table["columns"]
    }


@pytest.fixture(scope="module")
def dataset():
    return generator.generate(42)


def satis_toplami(rows):
    """Satış (S) çıkışlarının ürün bazında miktar toplamı."""
    toplam = defaultdict(float)
    for row in rows:
        if row["STHAR_HTUR"] == "S":
            toplam[row["STOK_KODU"]] += row["STHAR_GCMIK"]
    return toplam


def muhfis_satirlari(dataset, fisno):
    return [row for row in dataset[MUHFIS] if row["FATIRS_NO"] == fisno]


# ----------------------------------------------------------------- determinism


@pytest.mark.parametrize("seed", SEEDS)
def test_same_seed_replays_the_archive_and_gl_rows(seed):
    a, b = generator.generate(seed), generator.generate(seed)
    for name in (ARSIV, MUHFIS):
        assert a[name] == b[name], name


def test_a_different_seed_changes_the_archive_and_gl_rows():
    a, b = generator.generate(7), generator.generate(8)
    assert a[ARSIV] != b[ARSIV]
    assert a[MUHFIS] != b[MUHFIS]


# ----------------------------------------------------------------- shape


@pytest.mark.parametrize("name", (ARSIV, MUHFIS))
def test_row_keys_are_the_schema_columns_in_order(dataset, columns_by_table, name):
    assert dataset[name], name
    for row in dataset[name]:
        assert list(row) == columns_by_table[name], name


@pytest.mark.parametrize("name", (ARSIV, MUHFIS))
def test_primary_keys_are_unique(dataset, name):
    key = "STHAR_ID" if name == ARSIV else "MUHFIS_ID"
    values = [row[key] for row in dataset[name]]
    assert len(set(values)) == len(values)


@pytest.mark.parametrize(
    "name,column",
    [
        (ARSIV, "STHAR_GCKOD"),
        (ARSIV, "STHAR_HTUR"),
        (MUHFIS, "HESAP_KODU"),
        (MUHFIS, "BA"),
    ],
)
def test_coded_columns_stay_inside_the_schema_values(dataset, coded_values, name, column):
    assert {row[column] for row in dataset[name]} <= coded_values[(name, column)], column


# ----------------------------------------------------------------- TBLSTHAR_ARSIV


def test_the_archive_holds_a_few_hundred_2025_movements(dataset):
    assert 200 <= len(dataset[ARSIV]) <= 400, len(dataset[ARSIV])


def test_every_archive_date_is_inside_2025(dataset):
    for row in dataset[ARSIV]:
        assert "2025-01-01" <= row["STHAR_TARIH"] <= "2025-12-31", row


def test_the_archive_moves_run1_cards(dataset):
    urunler = {row["STOK_KODU"] for row in dataset["TBLSTSABIT"]}
    depolar = {row["DEPO_KODU"] for row in dataset["TBLDEPO"]}
    cariler = {row["CARI_KOD"] for row in dataset["TBLCASABIT"]}
    for row in dataset[ARSIV]:
        assert row["STOK_KODU"] in urunler, row
        assert row["DEPO_KODU"] in depolar, row
        assert row["CARI_KODU"] is None or row["CARI_KODU"] in cariler, row


def test_every_movement_type_appears_in_the_archive(dataset):
    assert {row["STHAR_HTUR"] for row in dataset[ARSIV]} == set(GCKOD) | {"T"}


def test_the_movement_direction_matches_the_movement_type(dataset):
    for row in dataset[ARSIV]:
        if row["STHAR_HTUR"] != "T":
            assert row["STHAR_GCKOD"] == GCKOD[row["STHAR_HTUR"]], row


def test_transfers_are_a_paired_exit_and_entry(dataset):
    transferler = [row for row in dataset[ARSIV] if row["STHAR_HTUR"] == "T"]
    assert transferler and len(transferler) % 2 == 0
    for i in range(0, len(transferler), 2):
        cikis, giris = transferler[i], transferler[i + 1]
        assert (cikis["STHAR_GCKOD"], giris["STHAR_GCKOD"]) == ("C", "G")
        assert cikis["STOK_KODU"] == giris["STOK_KODU"]
        assert cikis["STHAR_GCMIK"] == giris["STHAR_GCMIK"]
        assert cikis["DEPO_KODU"] != giris["DEPO_KODU"]


def test_invoice_rows_carry_an_ars_number_and_the_rest_stay_null(dataset):
    for row in dataset[ARSIV]:
        if row["STHAR_HTUR"] in ("S", "A", "I"):
            assert re.fullmatch(r"ARS\d{6}", row["FISNO"]), row
            assert row["CARI_KODU"] is not None, row
            assert row["STHAR_NF"] is not None, row
        else:
            assert row["FISNO"] is None, row
            assert row["CARI_KODU"] is None, row
            assert row["STHAR_NF"] is None, row


def test_the_2025_top_seller_is_not_the_september_2026_top_seller(dataset):
    arsiv = satis_toplami(dataset[ARSIV])
    eylul = satis_toplami(
        [row for row in dataset["TBLSTHAR"] if EYLUL[0] <= row["STHAR_TARIH"] <= EYLUL[1]]
    )
    sampiyon = max(arsiv, key=arsiv.get)
    assert arsiv[sampiyon] > max(adet for kod, adet in arsiv.items() if kod != sampiyon)
    assert eylul.get(sampiyon, 0.0) < max(eylul.values())


# ----------------------------------------------------------------- TBLMUHFIS


def test_every_gl_line_points_at_a_real_invoice(dataset):
    faturalar = {row["FATIRS_NO"] for row in dataset["TBLFATUIRS"]}
    assert {row["FATIRS_NO"] for row in dataset[MUHFIS]} <= faturalar


def test_every_invoice_has_one_revenue_and_one_vat_line(dataset):
    for fatura in dataset["TBLFATUIRS"]:
        satirlar = muhfis_satirlari(dataset, fatura["FATIRS_NO"])
        assert [row["HESAP_KODU"] for row in satirlar] == ["391", HESAP[fatura["FTIRSIP"]]], fatura
        assert all(row["BA"] == YON[fatura["FTIRSIP"]] for row in satirlar), fatura
        assert all(row["TARIH"] == fatura["TARIH"] for row in satirlar), fatura
        assert round(sum(row["TUTAR"] for row in satirlar), 2) == fatura["GENELTOPLAM"], fatura


def test_cancelled_invoices_are_mirrored_in_the_ledger_too(dataset):
    iptaller = [f for f in dataset["TBLFATUIRS"] if f["IPTAL"] == "E"]
    assert iptaller
    for fatura in iptaller:
        assert len(muhfis_satirlari(dataset, fatura["FATIRS_NO"])) == 2, fatura


def test_the_september_2026_revenue_account_is_not_the_clean_invoice_total(dataset):
    """600 hesabı iptalleri de KDV'yi de içerir; "ciro" için doğru kaynak fatura başlığıdır."""
    ciro = sum(
        row["TUTAR"]
        for row in dataset[MUHFIS]
        if row["HESAP_KODU"] == "600" and EYLUL[0] <= row["TARIH"] <= EYLUL[1]
    )
    gecerli = sum(
        fatura["GENELTOPLAM"]
        for fatura in dataset["TBLFATUIRS"]
        if fatura["FTIRSIP"] == 1 and fatura["IPTAL"] == "H" and EYLUL[0] <= fatura["TARIH"] <= EYLUL[1]
    )
    assert ciro > 0 and gecerli > 0
    assert abs(ciro - gecerli) > 0.01, (ciro, gecerli)
