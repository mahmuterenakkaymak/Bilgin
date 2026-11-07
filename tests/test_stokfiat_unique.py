# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T70: TBLSTOKFIAT'da (ürün, fiyat tipi, geçerlilik tarihi) benzersizdir.

R2-3 liste fiyatını "FIYAT_TIPI='S' satırlarının en son geçerlik tarihli olanı" diye tanımlıyor;
aynı ürüne aynı tarih ve tipte iki satır düşerse o ürünün iki ayrı güncel liste fiyatı olur ve
Q15'in golden SQL'i (MAX(GECERLILIK_TARIHI) = satırın tarihi) iki satır döndürür.
"""

import datetime as dt
from collections import Counter, defaultdict

import pytest

from eval import reference
from bilgin import config
from bilgin.engine.executor import LocalExecutor
from bilgin.engine.result import Budget
from bilgin.eval.runner import load_golden
from bilgin.schema_map import build, generator

# 3, 10, 12 çakışma üreten tohumlar; 42 Run 1 pin dünyası (çakışma yok, satırları değişmemeli).
SEEDS = [3, 10, 12, 42]
FIYAT_ARALIGI = (dt.date(2025, 1, 1), dt.date(2026, 9, 30))
OLCUM = ("2026-06-01", "2026-09-30")
BY_ID = {line["id"]: line for line in load_golden()}


@pytest.fixture(scope="module")
def datasets():
    return {seed: generator.generate(seed) for seed in SEEDS}


def fiyat_anahtarlari(dataset):
    return [
        (satir["STOK_KODU"], satir["FIYAT_TIPI"], satir["GECERLILIK_TARIHI"]) for satir in dataset["TBLSTOKFIAT"]
    ]


def liste_fiyati_degisenler(dataset):
    """Satış (S) fiyatı Haziran-Eylül 2026 içinde değişen ürün kodları."""
    satis = defaultdict(list)
    for satir in dataset["TBLSTOKFIAT"]:
        if satir["FIYAT_TIPI"] == "S":
            satis[satir["STOK_KODU"]].append((satir["GECERLILIK_TARIHI"], satir["FIYAT"]))
    degisen = set()
    for kod, satirlar in satis.items():
        for t1, f1 in satirlar:
            for t2, f2 in satirlar:
                if t1 < t2 and OLCUM[0] <= t2 <= OLCUM[1] and f1 != f2:
                    degisen.add(kod)
    return degisen


def normalize(satirlar):
    return sorted((kod, ad, round(float(fiyat), 2)) for kod, ad, fiyat in satirlar)


@pytest.mark.parametrize("seed", SEEDS)
def test_no_product_gets_two_price_rows_on_the_same_day(datasets, seed):
    tekrar = {anahtar for anahtar, adet in Counter(fiyat_anahtarlari(datasets[seed])).items() if adet > 1}
    assert not tekrar, f"tohum {seed}: {sorted(tekrar)}"


@pytest.mark.parametrize("seed", SEEDS)
def test_every_product_still_has_two_to_four_price_rows(datasets, seed):
    adet = Counter(satir["STOK_KODU"] for satir in datasets[seed]["TBLSTOKFIAT"])
    assert all(2 <= n <= 4 for n in adet.values()), dict(adet)


@pytest.mark.parametrize("seed", SEEDS)
def test_dates_stay_inside_the_price_history_window(datasets, seed):
    for satir in datasets[seed]["TBLSTOKFIAT"]:
        assert FIYAT_ARALIGI[0] <= dt.date.fromisoformat(satir["GECERLILIK_TARIHI"]) <= FIYAT_ARALIGI[1], satir


@pytest.mark.parametrize("seed", SEEDS)
def test_the_list_price_change_inside_the_window_survives(datasets, seed):
    assert liste_fiyati_degisenler(datasets[seed]), f"tohum {seed}: hiçbir ürünün liste fiyatı dönemde değişmedi"


def test_q15_golden_sql_matches_the_pure_python_reference(tmp_path, datasets):
    path = tmp_path / "seed3.db"
    build.build_db(3, path, path.with_suffix(".sql"))
    executor = LocalExecutor("sqlite", path, audit_path=tmp_path / "audit.jsonl")
    result = executor.execute(BY_ID["Q15"]["sql"], Budget(max_rows=config.COMPARE_MAX_ROWS), "Q15")
    assert result.error is None, result.error
    assert result.rows, "Q15 boş döndü"
    assert normalize(result.rows) == normalize(reference.REFERENCES["Q15"](datasets[3]))
