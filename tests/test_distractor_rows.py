# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T69: DISTRACTOR_ROWS gerçekten dolgunun üst sınırıdır — varsayılan 0 iken yakın kopyalar
dışındaki hiçbir distractor satır almaz (kurulum ekranı bunu şema-yalnız diye söyler),
5 iken hiçbiri beşi geçmez.
"""

import re
import sqlite3

import pytest

from bilgin import config
from bilgin.cli import main as cli
from bilgin.schema_map import doc, extra, generator

SEED = config.SEED


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def dataset_and_schema(schema):
    return generator.generate(SEED), schema


def filler_tables(schema):
    """Sayısı DISTRACTOR_ROWS'tan gelen distractorlar; yakın kopyalar her zaman doludur."""
    return [
        table
        for table in schema["tables"]
        if table.get("kind") == "distractor" and table["name"] not in extra.YAKIN_KOPYALAR
    ]


def sqlite_tables(path):
    conn = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            if not row[0].startswith("sqlite_")
        }
    finally:
        conn.close()


def script_tables(script):
    return set(re.findall(r"^CREATE TABLE (\w+)", script, re.MULTILINE))


def test_default_leaves_every_non_near_copy_distractor_empty(dataset_and_schema, schema):
    dataset, _ = dataset_and_schema
    assert extra.DISTRACTOR_ROWS == 0
    assert all(dataset[table["name"]] == [] for table in filler_tables(schema))


def test_near_copies_keep_their_rows(dataset_and_schema):
    dataset, _ = dataset_and_schema
    assert all(dataset[name] for name in extra.YAKIN_KOPYALAR)


def test_build_db_counts_the_schema_only_tables_and_still_creates_them_all(tmp_path, capsys, schema):
    database, script = tmp_path / "test.db", tmp_path / "test.sql"
    assert cli.build_database(seed=SEED, db_path=database, sql_path=script) == 0
    out = capsys.readouterr().out

    yalniz = int(re.search(r"şema-yalnız (\d+)\)", out).group(1))
    names = {table["name"] for table in schema["tables"]}
    # Structure, not a fixed count (it was `>= 60`, written with 62 distractors; Run 3 gave the personnel and salary
    # tables rows -> 59). Fixed 2026-10-24 with Eren's approval: the printed number equals the empty tables in the
    # built file, and the schema-only tables are still the majority (the "kafa karıştırıcı şema" property).
    with sqlite3.connect(database) as con:
        empty = sum(1 for name in names if con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0] == 0)
    assert yalniz == empty, out
    assert yalniz * 2 > len(names), out

    assert sqlite_tables(database) == names
    assert script_tables(script.read_text(encoding="utf-8")) == names


def test_filler_rows_are_capped_at_five(monkeypatch, schema):
    monkeypatch.setattr(extra, "DISTRACTOR_ROWS", 5)
    dataset = generator.generate(42)
    satirlar = [dataset[table["name"]] for table in filler_tables(schema)]
    assert all(len(rows) <= 5 for rows in satirlar)
    assert any(satirlar), "DISTRACTOR_ROWS=5 iken hiçbir distractor dolmadı"
    assert not all(satirlar), "DISTRACTOR_ROWS=5 iken her distractor doldu"
