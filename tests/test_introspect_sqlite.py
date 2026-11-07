# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T86: sqlite_skeleton over a real build_db file against the committed schema.json."""

import sqlite3

import pytest

from bilgin.schema_map import build, doc, introspect


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("introspect") / "test.db"
    build.build_db(db_path=path, sql_path=path.with_name("build_test_db.sql"))
    return path


@pytest.fixture(scope="module")
def skeleton(db):
    return introspect.sqlite_skeleton(db)


def _affinity(type_name: str) -> str:
    """The SQLite type build.py gives a T-SQL type - all a SQLite file can carry back."""
    return build.SQLITE_TYPES[type_name.split("(")[0].upper()]


def _columns(skeleton, schema):
    for table, skel_table in zip(schema["tables"], skeleton["tables"]):
        for column, skel_column in zip(table["columns"], skel_table["columns"]):
            yield f"{table['name']}.{column['name']}", column, skel_column


def test_skeleton_lists_every_schema_table_in_order(skeleton, schema):
    assert [table["name"] for table in skeleton["tables"]] == [table["name"] for table in schema["tables"]]


def test_skeleton_lists_every_column_in_order(skeleton, schema):
    for table, skel_table in zip(schema["tables"], skeleton["tables"]):
        assert [c["name"] for c in skel_table["columns"]] == [c["name"] for c in table["columns"]], table["name"]


def test_skeleton_types_invert_the_build_type_mapping(skeleton, schema):
    for where, column, skel_column in _columns(skeleton, schema):
        assert _affinity(skel_column["type"]) == _affinity(column["type"]), where


def test_skeleton_nullability_matches_the_schema(skeleton, schema):
    for where, column, skel_column in _columns(skeleton, schema):
        assert skel_column["nullable"] is column["nullable"], where


def test_skeleton_carries_no_meaning(skeleton):
    for table in skeleton["tables"]:
        assert table["kind"] == "unknown"
        assert table["description"] == ""
        for column in table["columns"]:
            assert column["description"] == ""
            assert column["values"] == {}
            # build.py declares no FOREIGN KEY constraints, so the built file has no fk to read back.
            assert column["fk"] is None


def test_normalize_type_inverts_the_build_type_mapping():
    for tsql_type, sqlite_type in build.SQLITE_TYPES.items():
        assert _affinity(introspect.normalize_type(sqlite_type)) == sqlite_type, tsql_type


def test_normalize_type_keeps_a_declared_length():
    assert introspect.normalize_type("varchar(20)") == "VARCHAR(20)"
    assert introspect.normalize_type("decimal(18,2)") == "DECIMAL(18,2)"
    assert introspect.normalize_type("TEXT") == "VARCHAR"
    assert introspect.normalize_type("INT") == "INT"
    assert introspect.normalize_type("datetime") == "DATETIME"


def test_foreign_keys_come_back_as_table_dot_column(tmp_path):
    path = tmp_path / "fk.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        'CREATE TABLE "TBLSTGRUP" ("GRUP_KODU" TEXT NOT NULL, PRIMARY KEY ("GRUP_KODU"));\n'
        'CREATE TABLE "TBLSTSABIT" ("STOK_KODU" TEXT NOT NULL, "GRUP_KODU" TEXT NOT NULL, '
        'FOREIGN KEY ("GRUP_KODU") REFERENCES "TBLSTGRUP" ("GRUP_KODU"));'
    )
    conn.commit()
    conn.close()

    tables = {table["name"]: table for table in introspect.sqlite_skeleton(path)["tables"]}
    assert tables["TBLSTGRUP"]["columns"][0]["fk"] is None
    assert tables["TBLSTSABIT"]["columns"][1]["fk"] == "TBLSTGRUP.GRUP_KODU"
