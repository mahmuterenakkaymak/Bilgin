# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T95: Run 3'ün uydurma PII verisi (PLAN R3-7) — kontrol haneleri her satırda, Run 1/Run 2 ise aynı.

Kişiler tamamen kurgudur; burada sayı değil yapı ölçülür: üretilen her TCKN/VKN 11 haneli kuralını,
her IBAN mod-97 kontrolünü tutar, bordro kalemleri bordronun netini tam verir ve `extend_run3`
Run 1/Run 2 satırlarına dokunmaz.
"""

import re
from collections import defaultdict

import pytest

from nl2sql.schema_map import doc, extra, generator

SUBE, PERSONEL, MAAS, MAASDETAY = "TBLCARISUBE", "TBLPERSONEL", "TBLMAAS", "TBLMAASDETAY"
PII_TABLES = (SUBE, PERSONEL, MAAS, MAASDETAY)
ILETISIM = ("ADRES", "TELEFON", "E_POSTA")
DONEM = ("2026-06", "2026-07", "2026-08", "2026-09")
TELEFON_DESENI = r"0\d{3} \d{3} \d{2} \d{2}"
SEEDS = (1, 7, 42, 2026)


@pytest.fixture(scope="module")
def columns_by_table():
    return {table["name"]: [c["name"] for c in table["columns"]] for table in doc.load_schema()["tables"]}


@pytest.fixture(scope="module", params=SEEDS, ids=str)
def dunya(request):
    """Her tohum bir kez üretilir; tohum numarası test kimliğinde görünür."""
    return generator.generate(request.param)


def tckn_mi(deger) -> bool:
    """11 hane, ilk hane 0 değil; 10. hane tek-çift ağırlık, 11. hane ilk on hanenin rakamlar toplamı."""
    if not isinstance(deger, str) or not re.fullmatch(r"[1-9]\d{10}", deger):
        return False
    hane = [int(karakter) for karakter in deger]
    return hane[9] == (sum(hane[0:9:2]) * 7 - sum(hane[1:8:2])) % 10 and hane[10] == sum(hane[:10]) % 10


def iban_mi(deger) -> bool:
    """TR + 2 kontrol hanesi + 22 hane; kontrol hanesiyle birlikte okunan sayı mod 97'de 1 verir."""
    if not isinstance(deger, str) or not re.fullmatch(r"TR\d{24}", deger):
        return False
    sayi = "".join(str(int(karakter, 36)) for karakter in f"{deger[4:]}TR{deger[2:4]}")
    return int(sayi) % 97 == 1


# ----------------------------------------------------------------- checksums


def test_every_generated_tckn_and_vkn_carries_a_valid_checksum(dunya):
    for kisi in dunya[PERSONEL]:
        assert tckn_mi(kisi["TCKN"]), kisi
        assert kisi["VKN"] is None or tckn_mi(kisi["VKN"]), kisi


def test_every_generated_iban_carries_a_valid_mod97_check(dunya):
    for kisi in dunya[PERSONEL]:
        assert iban_mi(kisi["IBAN"]), kisi


def test_no_two_people_share_a_tckn_or_an_iban(dunya):
    kisiler = dunya[PERSONEL]
    assert len({kisi["TCKN"] for kisi in kisiler}) == len(kisiler)
    assert len({kisi["IBAN"] for kisi in kisiler}) == len(kisiler)


# ----------------------------------------------------------------- rows


def test_the_pii_tables_have_rows(dunya):
    dataset = dunya
    assert 30 <= len(dataset[PERSONEL]) <= 60, len(dataset[PERSONEL])
    assert dataset[SUBE] and dataset[MAAS] and dataset[MAASDETAY]


@pytest.mark.parametrize("name", PII_TABLES)
def test_row_keys_are_the_schema_columns_in_order(dunya, columns_by_table, name):
    for row in dunya[name]:
        assert list(row) == columns_by_table[name], name


def test_personnel_cards_carry_fictional_identity_and_contact(dunya):
    for kisi in dunya[PERSONEL]:
        assert kisi["AD_SOYAD"] and kisi["GOREV_UNVANI"]
        assert kisi["ADRES"].startswith(kisi["IL"]), kisi
        assert kisi["TELEFON"] is None or re.fullmatch(TELEFON_DESENI, kisi["TELEFON"]), kisi
        assert kisi["E_POSTA"] is None or re.fullmatch(r"[\w.]+@[\w.]+\.\w+", kisi["E_POSTA"]), kisi


def test_the_branch_contact_columns_are_filled_on_the_existing_rows(dunya):
    for sube in dunya[SUBE]:
        assert sube["ADRES"].startswith(sube["IL"]), sube
        assert sube["TELEFON"] is None or re.fullmatch(TELEFON_DESENI, sube["TELEFON"]), sube
        assert sube["E_POSTA"] is None or "@" in sube["E_POSTA"], sube
    assert any(sube["TELEFON"] for sube in dunya[SUBE])
    assert any(sube["E_POSTA"] for sube in dunya[SUBE])


# ----------------------------------------------------------------- payslips


def test_one_payslip_per_person_for_every_period(dunya):
    donemler = defaultdict(list)
    for bordro in dunya[MAAS]:
        donemler[bordro["PERSONEL_KODU"]].append(bordro["DONEM"])
    assert set(donemler) == {kisi["PERSONEL_KODU"] for kisi in dunya[PERSONEL]}
    assert all(tuple(deger) == DONEM for deger in donemler.values())


def test_the_net_never_exceeds_the_gross_and_no_payslip_is_filed(dunya):
    for bordro in dunya[MAAS]:
        assert bordro["FISNO"] is None, bordro
        assert 0 < bordro["KESINTI_TUTAR"] <= bordro["BRUT_TUTAR"], bordro
        assert bordro["NET_TUTAR"] == pytest.approx(bordro["BRUT_TUTAR"] - bordro["KESINTI_TUTAR"], abs=0.01)


def test_every_payslip_has_two_to_four_lines_summing_to_its_net(dunya):
    kalemler = defaultdict(list)
    for kalem in dunya[MAASDETAY]:
        kalemler[kalem["MAAS_ID"]].append(kalem)
    assert set(kalemler) == {bordro["MAAS_ID"] for bordro in dunya[MAAS]}
    for bordro in dunya[MAAS]:
        satirlar = kalemler[bordro["MAAS_ID"]]
        assert 2 <= len(satirlar) <= 4, satirlar
        assert sum(1 for kalem in satirlar if kalem["TUR"] == "K") == 1, satirlar
        assert all(kalem["TUTAR"] > 0 and kalem["KALEM_ADI"] for kalem in satirlar), satirlar
        isaretli = sum(kalem["TUTAR"] if kalem["TUR"] == "K" else -kalem["TUTAR"] for kalem in satirlar)
        assert isaretli == pytest.approx(bordro["NET_TUTAR"], abs=0.01), bordro


# ----------------------------------------------------------------- streams


@pytest.mark.parametrize("seed", SEEDS)
def test_re_running_generate_replays_the_pii_rows(seed):
    for name in PII_TABLES:
        assert generator.generate(seed)[name] == generator.generate(seed)[name], name


def test_run3_touches_no_run1_or_run2_value(monkeypatch):
    """Run 3'ün kendi akışı vardır: PII tabloları eklenir, şube satırlarında yalnız yeni sütunlar dolar."""
    once = generator.generate(42)
    monkeypatch.setattr(extra, "extend_run3", lambda dataset, seed: None)
    once_before = generator.generate(42)

    for name, rows in once_before.items():
        if name in (PERSONEL, MAAS, MAASDETAY):
            assert rows == [], name
        elif name == SUBE:
            assert [{k: v for k, v in satir.items() if k not in ILETISIM} for satir in rows] == [
                {k: v for k, v in yeni.items() if k not in ILETISIM} for yeni in once[name]
            ], name
        else:
            assert rows == once[name], name
