# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T88: iskelete örnek değer ipuçları (R3-4).

Veri ve kapı gerçek: ``build_db`` ile kurulmuş dosya, sorgular ``LocalExecutor`` üzerinden
yürüdüğü için politika ve denetim kaydı model sorgularıyla aynı. İpucu bir açıklama değil
gözlemdir: ne kadar değer toplanabildiyse o yazılır, hiç toplanamazsa kolon boş kalır.
"""

import copy
import json

import pytest

from bilgin import config
from bilgin.cli import main as cli
from bilgin.engine.executor import LocalExecutor
from bilgin.schema_map import build, introspect

PII_CLASS = "address"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("sample") / "test.db"
    build.build_db(db_path=path, sql_path=path.with_name("build_test_db.sql"))
    return path


@pytest.fixture(scope="module")
def skeleton(db):
    return introspect.sqlite_skeleton(db)


@pytest.fixture(scope="module")
def sampled(db, skeleton, tmp_path_factory):
    """Tüm iskelet üzerinden tek tam geçiş: ipuçları ve o geçişin denetim kaydı."""
    audit = tmp_path_factory.mktemp("sample-audit") / "audit.jsonl"
    executor = LocalExecutor(db_path=db, audit_path=audit)
    return introspect.sample_hints(db, copy.deepcopy(skeleton), executor), audit


@pytest.fixture
def audit(tmp_path):
    return tmp_path / "audit.jsonl"


@pytest.fixture
def executor(db, audit):
    return LocalExecutor(db_path=db, audit_path=audit)


def _column(schema: dict, table: str, column: str) -> dict:
    for candidate in schema["tables"]:
        if candidate["name"] == table:
            return next(item for item in candidate["columns"] if item["name"] == column)
    raise AssertionError(f"{table}.{column} şemada yok")


def _only(skeleton: dict, table: str) -> dict:
    """Tek tablolarlık kopya: küçük geçişler için, alanları gerçek iskeletten gelir."""
    return {"tables": [copy.deepcopy(t) for t in skeleton["tables"] if t["name"] == table]}


def _sampled(schema: dict) -> dict:
    return {
        f"{table['name']}.{column['name']}": column["sample"]
        for table in schema["tables"]
        for column in table["columns"]
        if "sample" in column
    }


def _entries(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_short_text_columns_carry_hints(sampled):
    schema, _ = sampled
    hints = _sampled(schema)
    assert hints["TBLCARISUBE.IL"]
    for column in ("SUBE_KODU", "CARI_KOD", "SUBE_ADI", "ILCE", "AKTIF"):
        assert hints[f"TBLCARISUBE.{column}"], column


def test_hints_are_capped_distinct_non_null_and_short_text(skeleton, sampled):
    schema, _ = sampled
    hints = _sampled(schema)
    assert hints
    for name, values in hints.items():
        table, column = name.split(".")
        assert len(values) <= config.SAMPLE_HINT_N, name
        assert len(set(values)) == len(values), name
        assert None not in values, name
        declared = _column(skeleton, table, column)["type"]
        assert declared.split("(")[0] in introspect.TEXT_TYPES, name


def test_pii_column_gets_no_hint_and_is_never_queried(db, skeleton, executor, audit):
    schema = _only(skeleton, "TBLCARISUBE")
    _column(schema, "TBLCARISUBE", "IL")["pii"] = PII_CLASS
    introspect.sample_hints(db, schema, executor)

    assert "sample" not in _column(schema, "TBLCARISUBE", "IL")
    assert "sample" in _column(schema, "TBLCARISUBE", "AKTIF")
    assert not [entry for entry in _entries(audit) if "[IL]" in entry["sql"]]


def test_long_text_columns_are_left_out(db, executor, audit):
    schema = {
        "tables": [
            {
                "name": "TBLCARISUBE",
                "columns": [
                    {"name": "SUBE_ADI", "type": "NVARCHAR(1000)"},
                    {"name": "ACIKLAMA", "type": "VARCHAR(MAX)"},
                ],
            }
        ]
    }
    introspect.sample_hints(db, schema, executor)

    assert all("sample" not in column for column in schema["tables"][0]["columns"])
    assert not audit.exists()


def test_a_failing_query_leaves_no_hint_and_never_raises(db, executor, audit):
    schema = {"tables": [{"name": "TBLOLMAYAN", "columns": [{"name": "IL", "type": "VARCHAR(40)"}]}]}
    introspect.sample_hints(db, schema, executor)

    assert "sample" not in schema["tables"][0]["columns"][0]
    assert [entry["outcome"] for entry in _entries(audit)] == ["policy"]


def test_audit_holds_every_sample_query(sampled):
    _, audit = sampled
    entries = _entries(audit)
    head = f"SELECT DISTINCT TOP {config.SAMPLE_HINT_N} [IL] FROM [TBLCARISUBE]"

    assert entries
    assert all(entry["source"] == introspect.SAMPLE_SOURCE for entry in entries)
    assert all("DISTINCT" in entry["sql"] and entry["outcome"] == "ok" for entry in entries)
    assert sum(1 for entry in entries if entry["sql"].startswith(head)) == 1
    assert all(entry["row_count"] <= config.SAMPLE_HINT_N for entry in entries)


def test_cli_writes_the_skeleton_and_says_so(db, tmp_path, capsys):
    out = tmp_path / "skeleton.json"
    code = cli.introspect_schema(
        out=out, sample=True, db_path=db, audit_path=tmp_path / "audit.jsonl"
    )
    written = json.loads(out.read_text(encoding="utf-8"))
    tables = written["tables"]

    assert code == 0
    assert (
        f"İskelet: {len(tables)} tablo, "
        f"{sum(len(table['columns']) for table in tables)} kolon -> {out}"
    ) in capsys.readouterr().out
    assert _sampled(written)["TBLCARISUBE.IL"]


def test_the_introspect_flags_reach_the_command(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "introspect_schema", lambda **kwargs: seen.update(kwargs) or 0)

    assert cli.main(["introspect", "--out", "iskelet.json", "--sample"]) == 0
    assert seen == {"out": "iskelet.json", "sample": True}
