# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Tuzak testleri: her tuzak tohumda gerçekten kuruluyor mu ve saf SQL'i doğruldan saptırıyor mu?

Naive SQL, aynı sorunun tuzak farkında olmayan hali: golden ile aynı sütun sayısını üretir,
yani sonuç farkı biçimden değil tuzağın kendisinden gelir.
"""

import json
import sqlite3
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal

import pytest
from sqlglot import exp, parse, transpile

from eval import reference
from bilgin import config
from bilgin.schema_map import build, generator

FIELDS = {"trap", "qid", "naive_sql"}

# ASSUMPTION: PLAN Decision 5 Q02-Q10 için dokuz tuzak sayıyor (TASKS'daki "8" sayım hatası);
# golden.jsonl da dokuz tuzak taşıyor, bu yüzden traps.jsonl de dokuz satır.
# golden.jsonl'daki "trap" alanıyla birebir aynı adlar kullanılır.


def load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


GOLDEN = {line["id"]: line for line in load_jsonl(config.GOLDEN_PATH)}
TRAPS = load_jsonl(config.TRAPS_PATH)
BY_TRAP = {line["trap"]: line for line in TRAPS}
TRAP_NAMES = [line["trap"] for line in TRAPS]


# --------------------------------------------------------------------- dataset presence


def _in_span(value, span):
    return span[0] <= value < span[1]


def _ay(hareketler, span):
    return [h for h in hareketler if _in_span(h["STHAR_TARIH"], span)]


def _hareket_kumesi(dataset, alan, hturler, span=None):
    """ürün -> o hareket tiplerinde gördüğü değer kümesi (depot / fiyat / hareket tipi)."""
    kumeler: dict[str, set] = {}
    for hareket in dataset["TBLSTHAR"]:
        if hareket["STHAR_HTUR"] not in hturler:
            continue
        if span and not _in_span(hareket["STHAR_TARIH"], span):
            continue
        kumeler.setdefault(hareket["STOK_KODU"], set()).add(hareket[alan])
    return kumeler


PRESENCE = {
    # Q02: Eylül'de aynı ürün en az iki depodan çıkıyor.
    "cok_depo": lambda d: [
        kod
        for kod, depolar in _hareket_kumesi(d, "DEPO_KODU", ("S",), reference.SEP).items()
        if len(depolar) > 1
    ],
    # Q03: Ağustos'ta aynı ürün iki farklı net fiyatla satılıyor.
    "cok_fiyat": lambda d: [
        kod
        for kod, fiyatlar in _hareket_kumesi(d, "STHAR_NF", ("S",), reference.AUG).items()
        if len(fiyatlar) > 1
    ],
    # Q04: plasiyerli bir carinin Eylül'de iptal edilmiş satış faturası var.
    "iptal": lambda d: [
        f["FATIRS_NO"]
        for f in d["TBLFATUIRS"]
        if f["FTIRSIP"] == 1
        and f["IPTAL"] == "E"
        and _in_span(f["TARIH"], reference.SEP)
        and f["CARI_KODU"] in {c["CARI_KOD"] for c in d["TBLCASABIT"] if c["PLASIYER_KODU"]}
    ],
    # Q05: Ağustos'ta satış iadesi hareketi var.
    "iade": lambda d: [
        h["STHAR_ID"] for h in _ay(d["TBLSTHAR"], reference.AUG) if h["STHAR_HTUR"] == "I"
    ],
    # Q06: Temmuz'da iki ve üzeri satırlı, iptal edilmemiş fatura var.
    "fan_out": lambda d: [
        f["FATIRS_NO"]
        for f in d["TBLFATUIRS"]
        if f["IPTAL"] == "H"
        and _in_span(f["TARIH"], reference.JUL)
        and Counter(h["FISNO"] for h in d["TBLSTHAR"])[f["FATIRS_NO"]] > 1
    ],
    # Q07: faturasız (FISNO NULL) giriş hareketi var.
    "faturasiz_hareket": lambda d: [
        h["STHAR_ID"]
        for h in d["TBLSTHAR"]
        if h["STHAR_GCKOD"] == "G" and h["FISNO"] is None
    ],
    # Q08: H tipli cari iptal edilmemiş bir alış faturasında duruyor.
    "alici_satici": lambda d: [
        f["FATIRS_NO"]
        for f in d["TBLFATUIRS"]
        if f["FTIRSIP"] == 2
        and f["IPTAL"] == "H"
        and f["CARI_KODU"] in {c["CARI_KOD"] for c in d["TBLCASABIT"] if c["CARI_TIP"] == "H"}
    ],
    # Q09: teslim tarihi NULL olan sipariş satırı var.
    "null_teslim": lambda d: [
        s["SIPATRA_ID"] for s in d["TBLSIPATRA"] if s["TESLIM_TARIHI"] is None
    ],
    # Q10: hem satışı hem iadesi olan ürün var, yani oran kurulabiliyor.
    "kod_gckod": lambda d: [
        kod
        for kod, turler in _hareket_kumesi(d, "STHAR_HTUR", ("S", "I")).items()
        if turler == {"S", "I"}
    ],
}


# --------------------------------------------------------------------- fixtures / helpers


@pytest.fixture(scope="module")
def dataset():
    return generator.generate(config.SEED)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("traps") / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


def to_sqlite(sql):
    statements = transpile(sql, read="tsql", write="sqlite")
    assert len(statements) == 1
    return statements[0]


def run(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def cell(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    stable = Decimal(repr(round(float(value), 6)))
    return float(stable.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def comparable(rows, ordered):
    values = [tuple(map(cell, row)) for row in rows]
    return values if ordered else sorted(values, key=repr)


# ----------------------------------------------------------------- traps file shape


def test_traps_file_has_one_line_per_trap():
    assert len(TRAPS) == 9 and len(set(TRAP_NAMES)) == 9
    for line in TRAPS:
        assert set(line) == FIELDS, line
        assert line["naive_sql"].strip() and line["qid"] in GOLDEN, line


def test_one_naive_sql_per_trapped_question():
    assert {(line["trap"], line["qid"]) for line in TRAPS} == {
        (line["trap"], line["id"]) for line in GOLDEN.values() if line["trap"]
    }


@pytest.mark.parametrize("trap", TRAP_NAMES)
def test_naive_sql_is_a_single_tsql_select(trap):
    trees = parse(BY_TRAP[trap]["naive_sql"], read="tsql")
    assert len(trees) == 1 and isinstance(trees[0], exp.Select), trap


@pytest.mark.parametrize("trap", TRAP_NAMES)
def test_naive_sql_transpiles_to_one_sqlite_statement(trap):
    assert len(transpile(BY_TRAP[trap]["naive_sql"], read="tsql", write="sqlite")) == 1


@pytest.mark.parametrize("trap", TRAP_NAMES)
def test_naive_sql_answers_with_the_same_columns_as_the_golden(trap):
    """Fark biçimden değil tuzağın kendisinden gelmeli: sütun sayısı aynı kalmalı."""
    line = BY_TRAP[trap]
    naive = parse(line["naive_sql"], read="tsql")[0]
    golden = parse(GOLDEN[line["qid"]]["sql"], read="tsql")[0]
    assert len(naive.expressions) == len(golden.expressions), trap


# ----------------------------------------------------------------- trap is real, trap bites


@pytest.mark.parametrize("trap", TRAP_NAMES)
def test_every_trap_is_actually_built_in_the_dataset(trap, dataset):
    assert PRESENCE[trap](dataset), f"{trap} tuzağı tohumda kurulmamış"


@pytest.mark.parametrize("trap", TRAP_NAMES)
def test_naive_sql_result_differs_from_the_golden_result(trap, db, dataset):
    line = BY_TRAP[trap]
    golden = GOLDEN[line["qid"]]
    actual = comparable(run(db, to_sqlite(line["naive_sql"])), golden["ordered"])
    truth = comparable(reference.REFERENCES[line["qid"]](dataset), golden["ordered"])
    assert actual != truth, f"{trap} tuzağı {line['qid']} sonucunu değiştirmiyor"
