# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``--dataset``: komutun her varsayılanı kümenin kendi tanımıdır (R4-4, R4-14).

Küme adı verilince tohum, şema, kurallar, profil, altın sorular ve indeks klasörü config'den
değil o klasörden gelir; böylece ikinci bir dünya (mini) gerçek şemanın yanına kendi dosyalarını
elle kopyalamadan ölçülebilir. Küme adı verilmediğinde ekran hiçbir şey söylemez — iki küme
arasında seçim yapan bir komut hangi dünyayı ölçtüğünü ilk satırda söyler, ama tek kümeyle
çalışan bir koşumda bu satır gürültüdür. Açıkça verilen yol her zaman kazanır, o yüzden testler
yollarını kendileri verir ve repoya yazmaz.
"""

import json
import sqlite3
from pathlib import Path

import pytest
import sqlglot

from nl2sql.cli import main as cli
from nl2sql.datasets import load_dataset
from nl2sql.engine import login_script

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"


@pytest.fixture
def mini(monkeypatch):
    """Mini kümesi tek bilinen klasör: komutlar onu ortam değişkeni üzerinden bulur."""
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    return load_dataset("mini", root=FIXTURE_ROOT)


def tables(path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
    finally:
        conn.close()


# ------------------------------------------------------------------ build-db


def test_build_db_builds_the_datasets_own_tables(mini, tmp_path, capsys):
    database, script = tmp_path / "mini.db", tmp_path / "mini.sql"

    assert cli.build_database(db_path=database, sql_path=script, dataset="mini") == 0
    out = capsys.readouterr().out

    assert out.startswith(f"Veri kümesi: {mini.display_name} (mini)")
    assert f"Tohum: {mini.seed}" in out
    assert tables(database) == {table["name"] for table in mini.schema()["tables"]}
    assert "[Sales].[Customers]" in script.read_text(encoding="utf-8")
    assert "Tablolar: 4 (veri 4, şema-yalnız 0)" in out


# ------------------------------------------------------------------ build-index


def test_build_index_writes_the_datasets_name_and_its_own_schema(mini, tmp_path, capsys):
    index_dir = tmp_path / "index"

    assert cli.build_index("fake", index_dir=index_dir, dataset="mini") == 0
    out = capsys.readouterr().out
    meta = json.loads((index_dir / "meta.json").read_text(encoding="utf-8"))

    assert meta["dataset"] == "mini"
    assert meta["counts"]["tables"] == len(mini.schema()["tables"])
    assert f"Şema: {mini.schema_path}" in out and f"İndeks: {index_dir}" in out
    assert out.startswith("Veri kümesi: Mini (Satış/Depo) (mini)")


# ------------------------------------------------------------------ eval-retrieval


def test_eval_retrieval_measures_the_datasets_golden_questions(mini, tmp_path, capsys):
    out_dir = tmp_path / "retrieval"

    assert cli.eval_retrieval("fake", out_dir=out_dir, dataset="mini") == 0
    out = capsys.readouterr().out
    data = json.loads((out_dir / "latest" / "report.json").read_text(encoding="utf-8"))

    for line in mini.golden():
        assert line["id"] in out, f"{line['id']} satırda yok"
    # Ölçülen sorular kümenin kendi altını: wwi'nin onlariyla karışsaydı sayı tutmazdı.
    assert [question["id"] for question in data["questions"]] == [
        line["id"] for line in mini.golden()
    ]
    assert data["questions"][0]["requires"] == ["Sales.OrderLines"]


# ------------------------------------------------------------------ make-login-script


def test_make_login_script_denies_the_datasets_pii_column(mini, tmp_path, capsys):
    out = tmp_path / "ro.sql"

    assert cli.make_login_script(login="ro_x", out=out, dataset="mini") == 0
    script = out.read_text(encoding="utf-8")

    sqlglot.parse(script, read="tsql")
    assert "DENY SELECT (PhoneNumber) ON [Sales].[Customers]" in script
    assert "Allowlist: 4 tablo" in capsys.readouterr().out


# ------------------------------------------------------------------ bilinmeyen küme


@pytest.mark.parametrize(
    "argv",
    [
        ["build-db"],
        ["build-index", "--embed", "fake"],
        ["eval-retrieval", "--embed", "fake"],
        ["make-login-script"],
    ],
)
def test_an_unknown_dataset_is_refused_by_name(mini, argv, capsys):
    assert cli.main(argv + ["--dataset", "yok-boyle-bir-kume"]) == 2
    out = capsys.readouterr().out

    assert "Bilinmeyen veri kümesi: yok-boyle-bir-kume" in out
    assert "mini" in out, "bilinenler de sayılmalı"
    assert "Traceback" not in out and "Veri kümesi:" not in out


# ------------------------------------------------------------------ varsayılan ve geçiş


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (["build-db", "--dataset", "mini"], {"dataset": "mini"}),
        (["build-db", "--dataset", "mini", "--seed", "7"], {"seed": 7, "dataset": "mini"}),
        (["build-index", "--embed", "fake", "--dataset", "mini"], {"embed": "fake", "dataset": "mini"}),
        (
            ["make-login-script", "--dataset", "mini"],
            {"login": login_script.DEFAULT_LOGIN, "dataset": "mini"},
        ),
    ],
)
def test_main_passes_the_dataset_and_nothing_the_user_left_out(monkeypatch, argv, expected):
    seen = {}
    monkeypatch.setattr(cli, "build_database", lambda **kwargs: seen.update(kwargs) or 0)
    monkeypatch.setattr(cli, "build_index", lambda **kwargs: seen.update(kwargs) or 0)
    monkeypatch.setattr(cli, "make_login_script", lambda **kwargs: seen.update(kwargs) or 0)

    assert cli.main(argv) == 0
    assert seen == expected
