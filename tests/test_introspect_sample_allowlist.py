"""T113: ``--sample`` örnek sorguları yoklanan veritabanının kendi allowlist'i ile yürür (R3-14).

Bir ERP kopyasında ilk adım introspect'tir; o anda schema.json bu veritabanını henüz
anlatmaz. Örnekleme varsayılan listeyi kullanırsa her sorgu politika reddine düşer, hiç ipucu
toplanmaz ve CLI yine de "N tablo, M kolon" der. Burada dosya elle kurulur: tablo adı hiçbir
şemada yoktur, yani red değil kabul beklenir.
"""

import json
import sqlite3

import pytest

from nl2sql.cli import main as cli
from nl2sql.schema_map import doc, introspect

TABLE = "TBLMUSTERI"
COLUMNS = ("MUSTERI_KOD", "ILCE")
ROWS = [("M001", "Kadıköy"), ("M002", "Beşiktaş"), ("M003", "Kadıköy")]


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "erp-copy.db"
    conn = sqlite3.connect(path)
    conn.execute(f'CREATE TABLE "{TABLE}" ("{COLUMNS[0]}" TEXT, "{COLUMNS[1]}" TEXT)')
    conn.executemany(f'INSERT INTO "{TABLE}" VALUES (?, ?)', ROWS)
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def audit(tmp_path):
    return tmp_path / "audit.jsonl"


@pytest.fixture
def run(db, tmp_path, audit, capsys):
    out = tmp_path / "skeleton.json"
    code = cli.introspect_schema(out=out, sample=True, db_path=db, audit_path=audit)
    written = json.loads(out.read_text(encoding="utf-8"))
    return code, written, out, capsys.readouterr().out


def _columns(skeleton: dict) -> dict:
    return {column["name"]: column for column in skeleton["tables"][0]["columns"]}


def test_the_database_is_outside_the_committed_schema():
    assert TABLE not in doc.allowlist(doc.load_schema())


def test_cli_reports_the_skeleton_and_every_text_column_carries_values(run):
    code, skeleton, out, printed = run
    columns = _columns(skeleton)

    assert code == 0
    assert [table["name"] for table in skeleton["tables"]] == [TABLE]
    assert f"İskelet: 1 tablo, 2 kolon -> {out}" in printed
    for name in COLUMNS:
        assert columns[name]["sample"], name
    assert set(columns[COLUMNS[0]]["sample"]) == {row[0] for row in ROWS}


def test_sample_queries_pass_the_policy_and_are_audited_ok(run, audit):
    entries = [json.loads(line) for line in audit.read_text(encoding="utf-8").splitlines()]

    assert [entry["outcome"] for entry in entries] == ["ok", "ok"]
    assert all(entry["source"] == introspect.SAMPLE_SOURCE for entry in entries)
    assert all(TABLE in entry["sql"] for entry in entries)
