# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T39: kurulu dünya — şemanın her tablosu iki hedefte de vardır, distractor satırları türe uygundur
ve kurulum ekranı tablo sayılarını ile şema metninin bağlam maliyetini söyler.
"""

import re
import sqlite3

import pytest
from sqlglot import parse

from nl2sql import config
from nl2sql.cli import main as cli
from nl2sql.schema_map import build, doc, extra, generator

EYLUL = ("2026-09-01", "2026-09-30")
SEEDS = (1, 7, 42, 2026)


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def dataset_and_schema(schema):
    return generator.generate(config.SEED), schema


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Tohum 42'nin kurulu hali: SQLite dosyası ve T-SQL betiği, betiğin metniyle birlikte."""
    paths = tmp_path_factory.mktemp("world")
    database, script = paths / "test.db", paths / "test.sql"
    build.build_db(config.SEED, database, script)
    return database, script.read_text(encoding="utf-8")


def query(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def statements(script):
    """GO ile ayrılmış ifadeler; açıklama satırları düşürülür."""
    return [
        "\n".join(line for line in chunk.splitlines() if not line.startswith("--")).strip()
        for chunk in script.split("\nGO\n\n")
    ]


def sales_total(rows):
    """Eylül 2026 satış (S) hareketlerinin miktar toplamı."""
    return round(
        sum(r["STHAR_GCMIK"] for r in rows if r["STHAR_HTUR"] == "S" and EYLUL[0] <= r["STHAR_TARIH"] <= EYLUL[1]),
        2,
    )


def distractors(schema):
    return [table for table in schema["tables"] if table.get("kind") == "distractor"]


# ----------------------------------------------------------------- both targets


def test_every_schema_table_is_created_in_sqlite(world, schema):
    database, _ = world
    created = {
        row[0]
        for row in query(database, "SELECT name FROM sqlite_master WHERE type = 'table'")
        if not row[0].startswith("sqlite_")
    }
    assert created == {table["name"] for table in schema["tables"]}


def test_every_schema_table_is_created_by_the_script(world, schema):
    _, script = world
    created = {statement.split()[2] for statement in statements(script) if statement.startswith("CREATE TABLE")}
    assert created == {table["name"] for table in schema["tables"]}


def test_every_script_statement_parses_as_tsql(world, schema):
    _, script = world
    bodies = [statement for statement in statements(script) if statement]
    assert sum(1 for statement in bodies if statement.startswith("CREATE TABLE")) == len(schema["tables"])
    assert any(statement.startswith("INSERT INTO") for statement in bodies)
    for statement in bodies:
        result = parse(statement, read="tsql")
        assert len(result) == 1 and result[0] is not None, statement[:80]


# ----------------------------------------------------------------- near duplicates


@pytest.mark.parametrize("seed", SEEDS)
def test_near_duplicate_tables_have_rows(seed):
    dataset = generator.generate(seed)
    for name in extra.YAKIN_KOPYALAR:
        assert dataset[name], f"{name} boş"


def test_near_duplicate_rows_are_in_the_built_database(world):
    database, _ = world
    for name in extra.YAKIN_KOPYALAR:
        assert query(database, f'SELECT COUNT(*) FROM "{name}"')[0][0] > 0, name


@pytest.mark.parametrize("seed", SEEDS)
def test_the_log_table_answers_differently_than_the_real_one(seed):
    dataset = generator.generate(seed)
    assert sales_total(dataset["TBLSTHAR_LOG"]) != sales_total(dataset["TBLSTHAR"])


def test_the_log_answer_differs_in_sql_too(world):
    database, _ = world
    where = f"WHERE STHAR_HTUR = 'S' AND STHAR_TARIH >= '{EYLUL[0]}' AND STHAR_TARIH <= '{EYLUL[1]}'"

    def toplam(table):
        return query(database, f"SELECT SUM(STHAR_GCMIK) FROM {table} {where}")[0][0]

    assert toplam("TBLSTHAR_LOG") != toplam("TBLSTHAR")


def test_the_backup_card_table_disagrees_about_the_city(dataset_and_schema):
    """TBLCASABIT_YEDEK tuzağını kurmalı: en az bir yedeğin ili güncel kartla uyuşmamalı."""
    dataset, _ = dataset_and_schema
    il = {row["CARI_KOD"]: row["IL"] for row in dataset["TBLCASABIT"]}
    assert any(row["IL"] != il[row["CARI_KOD"]] for row in dataset["TBLCASABIT_YEDEK"])


# ----------------------------------------------------------------- filler rows


def test_other_distractors_stay_empty_by_default(dataset_and_schema):
    dataset, schema = dataset_and_schema
    assert extra.DISTRACTOR_ROWS == 0
    assert all(
        dataset[table["name"]] == [] for table in distractors(schema) if table["name"] not in extra.YAKIN_KOPYALAR
    )


def test_filler_rows_follow_the_column_types(monkeypatch, schema):
    monkeypatch.setattr(extra, "DISTRACTOR_ROWS", 5)
    dataset = generator.generate(42)
    kodlar = {
        "STOK_KODU": {row["STOK_KODU"] for row in dataset["TBLSTSABIT"]},
        "CARI_KOD": {row["CARI_KOD"] for row in dataset["TBLCASABIT"]},
        "CARI_KODU": {row["CARI_KOD"] for row in dataset["TBLCASABIT"]},
        "DEPO_KODU": {row["DEPO_KODU"] for row in dataset["TBLDEPO"]},
    }
    dolu = 0
    for table in distractors(schema):
        if table["name"] in extra.YAKIN_KOPYALAR:
            continue
        rows = dataset[table["name"]]
        assert len(rows) <= 5, table["name"]
        dolu += 1 if rows else 0
        for row in rows:
            assert list(row) == [c["name"] for c in table["columns"]], table["name"]
            for column in table["columns"]:
                _degeri_kontrol(row, column, kodlar, table["name"])
    assert dolu, "DISTRACTOR_ROWS=5 iken hiçbir distractor dolmadı"


def _degeri_kontrol(row, column, kodlar, table):
    deger = row[column["name"]]
    tip = column["type"].split("(")[0].upper()
    if deger is None:
        assert column["nullable"], f"{table}.{column['name']} NULL olamaz"
        return
    if tip == "INT":
        assert isinstance(deger, int), (table, column["name"], deger)
    elif tip == "DECIMAL":
        assert isinstance(deger, float), (table, column["name"], deger)
    elif tip == "DATE":
        assert re.fullmatch(r"2026-\d\d-\d\d", deger), (table, column["name"], deger)
    else:
        assert isinstance(deger, str), (table, column["name"], deger)
    if column["values"]:
        assert str(deger) in column["values"], (table, column["name"], deger)
    if column["name"] in kodlar:
        assert deger in kodlar[column["name"]], (table, column["name"], deger)


# ----------------------------------------------------------------- determinism


@pytest.mark.parametrize("seed", SEEDS[:2])
def test_the_distractor_rows_are_seeded(seed):
    a, b = generator.generate(seed), generator.generate(seed)
    for name in extra.YAKIN_KOPYALAR:
        assert a[name] == b[name], name


# ----------------------------------------------------------------- build-db report


def test_build_db_reports_the_table_counts_and_the_schema_text(tmp_path, capsys, schema):
    database, script = tmp_path / "test.db", tmp_path / "test.sql"
    assert cli.build_database(seed=7, db_path=database, sql_path=script) == 0
    out = capsys.readouterr().out

    toplam = len(schema["tables"])
    assert re.search(rf"Tablolar: {toplam} \(veri \d+, şema-yalnız \d+\)", out), out
    veri, yalniz = re.search(r"Tablolar: \d+ \(veri (\d+), şema-yalnız (\d+)\)", out).groups()
    assert int(veri) + int(yalniz) == toplam
    assert int(veri) >= len(extra.YAKIN_KOPYALAR), "yakın kopyalar kurulmadı"

    metin = doc.full_text(schema)
    assert f"Şema metni (full mod): {len(metin)} karakter ≈ {doc.estimate_tokens(metin)} token" in out
