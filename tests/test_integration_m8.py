# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T92: M8 entegrasyonu — gerçek SQLite iskeleti, gerçek Excel dönüşümü, gerçek merge/diff ve CLI.

Elle yapılmış sahte yok: iskelet gerçek ``build_db`` dosyasından ``sqlite_skeleton`` ile, Excel tarafı
gerçek ``convert`` ile üretilir; ``diff_map`` ve ``merge_map`` bu iki gerçek nesne üzerinde koşar.
Müşteri haritası veritabanının tamamını kapsadığı için yapısal bir düşüş yoktur; tek kayma SQLite'a
gidiş-dönüşün kendisidir (uzunluklu tip çıplak affinity'ye iner, SQLite dosyası foreign key taşımaz).
Son test aynı zinciri alt süreçte koşar: ``introspect`` iskeleti yazar, ``eval --schema <iskelet>
--llm fake`` onu ölçer ve rapora şemanın yolu ile imzasını geçirir (R3-5).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from bilgin import config
from bilgin.schema_map import build, doc, excel, introspect, merge

FIXTURES = Path(__file__).parent / "fixtures"
MESSY = str(FIXTURES / "map_customer_map.xlsx")


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def skeleton(tmp_path_factory):
    """Gerçek bir kurulumdan yoklanmış iskelet: build_db -> sqlite_skeleton, tmp dosya üzerinde."""
    path = tmp_path_factory.mktemp("m8") / "test.db"
    build.build_db(config.SEED, path, path.with_name("build.sql"))
    return introspect.sqlite_skeleton(path)


@pytest.fixture(scope="module")
def messy():
    """Dağınık müşteri haritası gerçek sözlük eşlemesiyle gerçek ``convert``ten geçmiş hâliyle."""
    return excel.convert(MESSY, excel.fallback_mapping(excel.read_workbook(MESSY)))["schema"]


def _affinity(tsql_type: str) -> str:
    """A T-SQL type's SQLite affinity - all a built SQLite file can carry back (build.SQLITE_TYPES)."""
    return build.SQLITE_TYPES[str(tsql_type).split("(")[0].upper()]


def _skeleton_type(tsql_type: str) -> str:
    """sqlite_skeleton's type name for a schema type: the affinity collapsed back to its T-SQL name."""
    return introspect.normalize_type(_affinity(tsql_type))


def _refs(items: list) -> set:
    return {(item["table"], item["column"]) for item in items}


# ------------------------------------------------------------------ iskelet == şema (yapı)


def test_skeleton_reproduces_the_schema_structure(skeleton, schema):
    assert [table["name"] for table in skeleton["tables"]] == [
        table["name"] for table in schema["tables"]
    ]
    for skel_table, table in zip(skeleton["tables"], schema["tables"]):
        assert [c["name"] for c in skel_table["columns"]] == [c["name"] for c in table["columns"]]
        for skel_column, column in zip(skel_table["columns"], table["columns"]):
            where = f"{table['name']}.{column['name']}"
            assert _affinity(skel_column["type"]) == _affinity(column["type"]), where
            assert skel_column["nullable"] is column["nullable"], where
            # build.py declares no FOREIGN KEY constraints, so the built file has no fk to read back.
            assert skel_column["fk"] is None, where


# ------------------------------------------------------------------ diff: harita ile veritabanı


def test_diff_reports_exactly_the_drift_between_the_map_and_the_database(messy, skeleton, schema):
    report = merge.diff_map(messy, skeleton)
    # The customer map covers the whole database: no table or column sits on only one side.
    assert report["excel_only_tables"] == []
    assert report["db_only_tables"] == []
    assert report["excel_only_columns"] == []
    assert report["db_only_columns"] == []
    # The only type drift is the SQLite round-trip: exactly the columns whose declared T-SQL type
    # collapses onto a bare affinity (VARCHAR(20) -> VARCHAR, DATE -> VARCHAR), and nothing else.
    expected_types = {
        (table["name"], column["name"])
        for table in schema["tables"]
        for column in table["columns"]
        if column["type"].upper() != _skeleton_type(column["type"]).upper()
    }
    assert _refs(report["type_mismatches"]) == expected_types
    # The built file declares no FK constraints, so every reference the map claims is missing in the DB.
    expected_fks = {
        (table["name"], column["name"])
        for table in schema["tables"]
        for column in table["columns"]
        if column.get("fk")
    }
    assert _refs(report["fk_missing_in_db"]) == expected_fks


# ------------------------------------------------------------------ merge: varlık DB'den, anlam Excel'den


def test_merge_keeps_every_database_table_with_the_maps_meaning(messy, skeleton):
    merged = merge.merge_map(messy, skeleton)
    assert [table["name"] for table in merged["tables"]] == [
        table["name"] for table in skeleton["tables"]
    ]
    excel_tables = {table["name"]: table for table in messy["tables"]}
    db_tables = {table["name"]: table for table in skeleton["tables"]}
    for table in merged["tables"]:
        name = table["name"]
        assert [c["name"] for c in table["columns"]] == [
            c["name"] for c in db_tables[name]["columns"]
        ], "varlık ve sıralama veritabanının"
        assert table["description"] == excel_tables[name]["description"], "tablo anlamı Excel'den"
        excel_columns = {c["name"]: c for c in excel_tables[name]["columns"]}
        db_columns = {c["name"]: c for c in db_tables[name]["columns"]}
        for column in table["columns"]:
            # the map's description where it kept one (empty where the fixture dropped it), never the DB's
            assert column["description"] == excel_columns[column["name"]]["description"]
            assert column["type"] == db_columns[column["name"]]["type"], "tip veritabanının"
            assert column["fk"] == db_columns[column["name"]]["fk"], "fk veritabanının"


# ------------------------------------------------------------------ CLI alt süreç: introspect -> eval


@pytest.fixture(scope="module")
def built_database(tmp_path_factory):
    """Alt süreç ``config.DB_PATH``ı okur (yol için ortam değişkeni yok); ``build-db``nin yazdığı yer."""
    build.build_db(config.SEED, config.DB_PATH, tmp_path_factory.mktemp("m8-cli") / "build.sql")
    return config.DB_PATH


def test_cli_introspect_then_eval_scores_the_skeleton(built_database, tmp_path):
    skeleton_path = tmp_path / "iskelet.json"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

    introspect_run = subprocess.run(
        [sys.executable, "-m", "bilgin", "introspect", "--out", str(skeleton_path)],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        env=env,
    )
    assert introspect_run.returncode == 0, introspect_run.stdout + introspect_run.stderr
    assert skeleton_path.is_file()

    eval_run = subprocess.run(
        [sys.executable, "-m", "bilgin", "eval", "--schema", str(skeleton_path), "--llm", "fake"],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        env=env,
    )
    assert eval_run.returncode == 0, eval_run.stdout + eval_run.stderr

    report = json.loads(
        (config.EVAL_OUT / "full" / "latest" / "report.json").read_text(encoding="utf-8")
    )
    assert report["schema"]["path"] == str(skeleton_path)
    assert len(report["schema"]["hash"]) == 64
    assert f"Şema: {skeleton_path} ({report['schema']['hash'][:8]})" in eval_run.stdout
    assert report["score"]["total"] > 0
    assert report["score"]["passed"] == report["score"]["total"]
