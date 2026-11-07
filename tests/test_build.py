# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

import inspect
import shutil
import sqlite3

import pytest
from sqlglot import exp, parse

from bilgin import config
from bilgin.schema_map import build, doc, generator


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def dataset():
    return generator.generate()


@pytest.fixture(scope="module")
def sqlite_db(tmp_path_factory, dataset, schema):
    path = tmp_path_factory.mktemp("sqlite") / "test.db"
    build.write_sqlite(dataset, schema, path)
    return path


@pytest.fixture(scope="module")
def mssql_script(tmp_path_factory, dataset, schema):
    path = tmp_path_factory.mktemp("mssql") / "build_test_db.sql"
    build.write_mssql_script(dataset, schema, path)
    return path.read_text(encoding="utf-8")


def build_pair(tmp_path, seed):
    """build_db into a private db/script pair; returns the db path."""
    db_path = tmp_path / f"seed-{seed}.db"
    build.build_db(seed, db_path, db_path.with_suffix(".sql"))
    return db_path


def query(path, sql, args=()):
    conn = sqlite3.connect(path)
    try:
        rows = conn.execute(sql, args).fetchall()
        conn.commit()
        return rows
    finally:
        conn.close()


def statements_of(script):
    """The GO-separated statements, without the header comment lines."""
    bodies = []
    for chunk in script.split("\nGO\n\n"):
        body = "\n".join(line for line in chunk.splitlines() if not line.startswith("--")).strip()
        if body:
            bodies.append(body)
    return bodies


def create_statements(script):
    return [statement for statement in statements_of(script) if statement.startswith("CREATE TABLE")]


def parsed(script):
    return [(statement, parse(statement, read="tsql")[0]) for statement in statements_of(script)]


# ----------------------------------------------------------------- determinism


def test_same_seed_gives_the_same_checksum(tmp_path):
    assert build.checksum(build_pair(tmp_path, config.SEED)) == build.checksum(
        build_pair(tmp_path, config.SEED)
    )


def test_other_seed_gives_a_different_checksum(tmp_path):
    base = build.checksum(build_pair(tmp_path, 1))
    assert base != build.checksum(build_pair(tmp_path, 2))
    assert base != build.checksum(build_pair(tmp_path, 3))


def test_checksum_changes_when_a_cell_changes(sqlite_db, tmp_path):
    copy = tmp_path / "copy.db"
    shutil.copy(sqlite_db, copy)
    before = build.checksum(copy)
    query(copy, "UPDATE TBLSTGRUP SET GRUP_ISIMI = GRUP_ISIMI || '?' WHERE GRUP_KODU = 'GRP01'")
    assert build.checksum(copy) != before


# ----------------------------------------------------------------- sqlite target


def test_row_counts_match_the_dataset(sqlite_db, dataset, schema):
    for table in schema["tables"]:
        name = table["name"]
        assert len(query(sqlite_db, f'SELECT * FROM "{name}"')) == len(dataset[name]), name


def test_columns_and_their_order_follow_the_schema(sqlite_db, schema):
    for table in schema["tables"]:
        names = [row[1] for row in query(sqlite_db, f'PRAGMA table_info("{table["name"]}")')]
        assert names == [column["name"] for column in table["columns"]], table["name"]


def test_values_survive_the_round_trip(sqlite_db, dataset):
    for row in dataset["TBLFATUIRS"][:5]:
        stored = query(
            sqlite_db,
            "SELECT TARIH, GENELTOPLAM, IPTAL FROM TBLFATUIRS WHERE FATIRS_NO = ?",
            (row["FATIRS_NO"],),
        )
        assert stored == [(row["TARIH"], row["GENELTOPLAM"], row["IPTAL"])]


def test_turkish_text_and_nulls_are_kept(sqlite_db, dataset):
    assert {row["CARI_ISIM"] for row in dataset["TBLCASABIT"]} == {
        row[0] for row in query(sqlite_db, "SELECT CARI_ISIM FROM TBLCASABIT")
    }
    aciklamalar = [row[0] for row in query(sqlite_db, "SELECT ACIKLAMA FROM TBLSTGRUP")]
    assert None in aciklamalar and any(aciklamalar)


def test_not_null_columns_hold_no_nulls(sqlite_db, schema):
    for table in schema["tables"]:
        required = [column["name"] for column in table["columns"] if not column["nullable"]]
        assert required, table["name"]
        where = " AND ".join(f"{name} IS NULL" for name in required)
        assert query(sqlite_db, f'SELECT COUNT(*) FROM "{table["name"]}" WHERE {where}') == [(0,)], table["name"]


# ----------------------------------------------------------------- t-sql target


def test_every_statement_parses_as_tsql(mssql_script):
    statements = statements_of(mssql_script)
    assert len(statements) > len(create_statements(mssql_script))
    for statement in statements:
        result = parse(statement, read="tsql")
        assert len(result) == 1 and result[0] is not None, statement[:80]


def test_script_creates_every_table_then_inserts_every_row(mssql_script, dataset, schema):
    created, inserted = [], {}
    for statement, tree in parsed(mssql_script):
        table = tree.find(exp.Table).name
        if isinstance(tree, exp.Create):
            created.append(table)
        else:
            values = len(tree.find(exp.Values).expressions)
            inserted[table] = inserted.get(table, 0) + values
    assert created == [item["name"] for item in schema["tables"]]
    assert inserted == {name: len(rows) for name, rows in dataset.items() if rows}


def test_inserts_are_batched(mssql_script):
    sizes = [
        len(tree.find(exp.Values).expressions)
        for _, tree in parsed(mssql_script)
        if isinstance(tree, exp.Insert)
    ]
    assert max(sizes) <= build.INSERT_BATCH_ROWS
    assert any(size > 1 for size in sizes), "satırlar toplu eklenmiyor"


def test_literals_are_unicode_null_and_iso_date(mssql_script, dataset):
    city = dataset["TBLCASABIT"][0]["IL"]
    assert f"N'{city}'" in mssql_script
    assert f"'{dataset['TBLFATUIRS'][0]['TARIH']}'" in mssql_script
    assert "NULL" in mssql_script


def test_text_literals_are_escaped(tmp_path, schema):
    path = tmp_path / "escape.sql"
    build.write_mssql_script(
        {"TBLSTGRUP": [{"GRUP_KODU": "GRP01", "GRUP_ISIMI": "O'Brien [özel]", "ACIKLAMA": None}]},
        schema,
        path,
    )
    script = path.read_text(encoding="utf-8")
    assert "N'O''Brien [özel]'" in script
    assert len(parse(statements_of(script)[0], read="tsql")) == 1


# ----------------------------------------------------------------- build_db


def test_build_db_writes_both_targets_and_returns_the_checksum(tmp_path):
    db_path = tmp_path / "test.db"
    sql_path = tmp_path / "build_test_db.sql"
    digest = build.build_db(5, db_path, sql_path)
    assert db_path.exists() and sql_path.exists()
    assert digest == build.checksum(db_path)
    assert "CREATE TABLE TBLSTHAR" in sql_path.read_text(encoding="utf-8")


def test_paths_default_to_config():
    assert inspect.signature(build.write_sqlite).parameters["path"].default is config.DB_PATH
    assert inspect.signature(build.write_mssql_script).parameters["path"].default is config.MSSQL_SCRIPT
    assert inspect.signature(build.checksum).parameters["path"].default is config.DB_PATH
    params = inspect.signature(build.build_db).parameters
    assert (params["seed"].default, params["db_path"].default, params["sql_path"].default) == (
        config.SEED,
        config.DB_PATH,
        config.MSSQL_SCRIPT,
    )
