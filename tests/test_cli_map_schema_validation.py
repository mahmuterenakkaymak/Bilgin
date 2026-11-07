# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``merge-map``/``diff-map`` şema olmayan dosyayı kabul etmez (T115, PLAN R3-5).

``import-map``ın yazdığı eşleme dosyası da üst düzey bir JSON nesnesi, ama şema değil: ``sheets``
taşır, ``tables`` değil. Eskiden iki komut da onu sessizce yutuyordu - ``merge-map`` "Birleşik şema
yazıldı" deyip yalnızca iskeleti yazıyor, ``diff-map`` her tabloyu veritabanına özgü sayıp Excel
tarafını kaybediyordu. Artık üçü de (``eval`` dahil) aynı tek cümleyle, iz dökümü olmadan çıkar.
"""

import json

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.cli import main as cli
from nl2sql.schema_map import build, introspect

UNREADABLE = "Şema dosyası okunamadı"


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    """Modül boyunca tek veritabanı: iskelet ondan üretiliyor, ``eval`` de onu kullanıyor."""
    paths = tmp_path_factory.mktemp("map-schema")
    db = paths / "test.db"
    build.build_db(config.SEED, db, paths / "test.sql")
    return db


def mapping_file(path):
    """Eşleme dosyasının biçimi: üst düzey nesne, ``sheets`` var, ``tables`` yok."""
    path.write_text(
        json.dumps(
            {"sheets": [{"sheet": "Müşteri", "table": "TBLMUSTERI", "columns": []}]},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def skeleton_file(path, database):
    """Gerçek bir iskelet: reddin eşleme dosyasından geldiği belli olsun, okunamayan yoldan değil."""
    path.write_text(
        json.dumps(introspect.sqlite_skeleton(database), ensure_ascii=False), encoding="utf-8"
    )
    return path


def test_merge_map_refuses_a_mapping_as_the_excel_side(database, tmp_path, capsys):
    mapping = mapping_file(tmp_path / "mapping.json")
    skeleton = skeleton_file(tmp_path / "iskelet.json", database)
    out = tmp_path / "merged.json"

    assert cli.merge_map(mapping, db_schema=skeleton, out=out) == 2
    printed = capsys.readouterr().out
    assert f"{UNREADABLE}: {mapping}" in printed and "Traceback" not in printed
    assert not out.exists(), "reddedilen koşu birleşik şema yazmaz"


def test_merge_map_refuses_a_mapping_as_the_database_side(tmp_path, capsys):
    mapping = mapping_file(tmp_path / "mapping.json")
    out = tmp_path / "merged.json"

    assert cli.merge_map(config.SCHEMA_PATH, db_schema=mapping, out=out) == 2
    printed = capsys.readouterr().out
    assert f"{UNREADABLE}: {mapping}" in printed and "Traceback" not in printed
    assert not out.exists()


def test_diff_map_refuses_a_mapping_and_writes_no_report(database, tmp_path, capsys):
    mapping = mapping_file(tmp_path / "mapping.json")
    skeleton = skeleton_file(tmp_path / "iskelet.json", database)
    json_out = tmp_path / "diff.json"
    md_out = tmp_path / "diff.md"

    assert cli.diff_map(mapping, db_schema=skeleton, json_out=json_out, md_out=md_out) == 2
    printed = capsys.readouterr().out
    assert f"{UNREADABLE}: {mapping}" in printed and "Traceback" not in printed
    assert not json_out.exists() and not md_out.exists(), "fark raporu yazılmaz"


def test_evaluate_refuses_a_tables_field_that_is_not_a_list(database, tmp_path, capsys):
    bad = tmp_path / "schema.json"
    bad.write_text(json.dumps({"tables": "x"}), encoding="utf-8")
    out_dir = tmp_path / "eval_out"

    code = cli.evaluate(
        fake.FakeLLM([]),
        db_path=database,
        audit_path=tmp_path / "audit.jsonl",
        out_dir=out_dir,
        schema_path=bad,
    )
    printed = capsys.readouterr().out

    assert code == 2
    assert f"{UNREADABLE}: {bad}" in printed and "Traceback" not in printed
    assert "Mod:" not in printed and not out_dir.exists()
