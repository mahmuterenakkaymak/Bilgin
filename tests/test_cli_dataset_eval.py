# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``ask``, ``eval`` ve ``eval --compare`` için ``--dataset``: ölçüm kümenin dünyasıyla yapılır (R4-4).

Küme adı verilince şema, kurallar, join profili, altın sorular, veritabanı, indeks, rapor klasörü
ve referans tarihi o klasörden gelir; ekran hangi dünyanın ölçüldüğünü ilk satırda söyler. Küme
adının söylenmediği koşum Run 3'ü olduğu gibi bırakır: rapor kendi kümesini adıyla yazar ama
imzası Run 3'ün anahtarlarıdır — imza değişseydi diskteki ``latest``ler bir daha hiç yeniden
kullanılamazdı. Başka bir kümenin indeksi ilk soru koşmadan reddedilir (R4-8). Açıkça verilen her
yol kümenin önüne geçtiği için testler veritabanını, indeksi ve çıktıyı kendi tmp klasörlerinde kurar.
"""

import json
from pathlib import Path

import pytest

from bilgin import config
from bilgin.cli import main as cli
from bilgin.datasets import load_dataset
from bilgin.schema_map import build

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
# Run 3'ün imzası: ``dataset`` anahtarı yalnız kümenin adı varsayılandan farklıysa yazılır (R4-4).
RUN3_KEYS = {
    "mode",
    "llm",
    "model",
    "question_ids",
    "golden_hash",
    "schema_hash",
    "rules_hash",
    "index_hash",
    "max_tool_calls",
}


@pytest.fixture
def world(monkeypatch, tmp_path, capsys):
    """Mini kümesinin tmp dünyası: veritabanı, indeks ve audit repoya yazmaz."""
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(FIXTURE_ROOT))
    ds = load_dataset("mini", root=FIXTURE_ROOT)
    database = tmp_path / "mini.db"
    assert cli.build_database(db_path=database, sql_path=tmp_path / "mini.sql", dataset="mini") == 0
    index = tmp_path / "index"
    assert cli.build_index("fake", index_dir=index, dataset="mini") == 0
    capsys.readouterr()
    return ds, database, index, tmp_path / "audit.jsonl"


@pytest.fixture(scope="module")
def synthetic(tmp_path_factory):
    """Küme söylenmeyen koşumun dünyası: config'in şemasıyla kurulmuş veritabanı ve audit."""
    paths = tmp_path_factory.mktemp("dataset-eval-synthetic")
    database = paths / "test.db"
    build.build_db(config.SEED, database, paths / "test.sql")
    return database, paths / "audit.jsonl"


def written(directory) -> dict:
    return json.loads((directory / "latest" / "report.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ eval


@pytest.mark.parametrize("mode", ["full_rules", "rag"])
def test_every_mini_question_passes_in_its_own_mode(world, tmp_path, mode, capsys):
    ds, database, index, audit = world
    out_dir = tmp_path / "eval_out" / mode

    code = cli.evaluate(
        cli.make_client("fake", mode, ds),
        mode=mode,
        db_path=database,
        audit_path=audit,
        out_dir=out_dir,
        index_dir=index,
        dataset="mini",
    )
    out = capsys.readouterr().out
    data = written(out_dir)

    assert code == 0
    assert out.startswith(f"Veri kümesi: {ds.display_name} (mini)")
    assert f"Skor: {len(ds.golden())}/{len(ds.golden())}" in out
    # Ölçülen sorular kümenin kendi altını; synthetic_erp'nin onlarıyla karışsaydı sayı tutmazdı.
    assert [question["id"] for question in data["questions"]] == [
        line["id"] for line in ds.golden()
    ]
    assert data["dataset"] == "mini"
    assert data["schema"]["path"] == str(ds.schema_path)
    assert data["config"]["fingerprint"]["dataset"] == "mini"


def test_a_run_without_a_dataset_keeps_the_run_3_fingerprint(synthetic, tmp_path, capsys):
    database, audit = synthetic
    out_dir = tmp_path / "eval_out" / "full_rules"

    code = cli.evaluate(
        cli.make_client("fake", "full_rules"),
        mode="full_rules",
        db_path=database,
        audit_path=audit,
        out_dir=out_dir,
    )
    out = capsys.readouterr().out
    data = written(out_dir)

    assert code == 0
    assert data["dataset"] == config.DEFAULT_DATASET
    assert set(data["config"]["fingerprint"]) == RUN3_KEYS
    assert "Veri kümesi" not in out, "tek kümeyle çalışan bir koşumda bu satır gürültüdür"


# ------------------------------------------------------------------ compare


def test_compare_writes_its_report_under_the_out_dir(world, tmp_path, capsys):
    ds, database, index, audit = world
    out_dir = tmp_path / "eval_out"

    code = cli.compare_modes(
        lambda mode: cli.make_client("fake", mode, ds),
        db_path=database,
        audit_path=audit,
        out_dir=out_dir,
        index_dir=index,
        dataset="mini",
    )
    out = capsys.readouterr().out
    data = written(out_dir / "compare")

    assert code == 0
    assert out.startswith(f"Veri kümesi: {ds.display_name} (mini)")
    assert list(data["modes"]) == list(config.MODES)
    for mode in config.MODES:
        assert data["modes"][mode]["score"] == {
            "passed": len(ds.golden()),
            "total": len(ds.golden()),
        }
        assert written(out_dir / mode)["dataset"] == "mini"
    assert str(out_dir / "compare") in out


# ------------------------------------------------------------------ ask


def test_ask_prints_the_qualified_sql_and_its_table(world, capsys):
    ds, database, index, audit = world
    line = ds.golden()[0]

    code = cli.ask(
        line["question"],
        cli.make_client("fake", "rag", ds),
        mode="rag",
        db_path=database,
        audit_path=audit,
        index_dir=index,
        dataset="mini",
    )
    out = capsys.readouterr().out

    assert code == 0
    assert out.startswith(f"Veri kümesi: {ds.display_name} (mini)")
    assert "Mod: rag" in out and f"Soru: {line['question']}" in out
    assert line["sql"] in out and "FROM Sales.OrderLines" in out
    assert "Sonuç:" in out and "CIRO" in out, "cevabın tablosu ekranda durmalı"


# ------------------------------------------------------------------ R4-8: indeksin sahibi


def test_a_synthetic_index_is_refused_before_the_first_question(world, tmp_path, capsys):
    ds, database, _, audit = world
    index = tmp_path / "synthetic-index"
    assert cli.build_index("fake", index_dir=index) == 0
    capsys.readouterr()
    out_dir = tmp_path / "eval_out"

    code = cli.evaluate(
        cli.make_client("fake", "rag", ds),
        mode="rag",
        db_path=database,
        audit_path=audit,
        out_dir=out_dir / "rag",
        index_dir=index,
        dataset="mini",
    )
    out = capsys.readouterr().out

    assert code == 2
    assert "İndeks başka veri kümesine ait: synthetic_erp (istenen mini)" in out
    assert "Traceback" not in out and "Skor:" not in out
    assert not out_dir.exists(), "reddedilen koşunun raporu yazılmaz"


# ------------------------------------------------------------------ söz dizimi


@pytest.mark.parametrize("argv", [["ask", "Soru?"], ["eval"], ["eval", "--compare"]])
def test_an_unknown_dataset_is_refused_before_anything_runs(monkeypatch, argv, capsys):
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(FIXTURE_ROOT))

    assert cli.main(argv + ["--llm", "fake", "--dataset", "yok-boyle-bir-kume"]) == 2
    out = capsys.readouterr().out

    assert "Bilinmeyen veri kümesi: yok-boyle-bir-kume" in out
    assert "Traceback" not in out and "Veri kümesi:" not in out


def test_main_leaves_an_unnamed_schema_to_the_dataset(monkeypatch):
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(FIXTURE_ROOT))
    seen = {}
    monkeypatch.setattr(cli, "evaluate", lambda **kwargs: seen.update(kwargs) or 0)

    assert cli.main(["eval", "--llm", "fake", "--dataset", "mini"]) == 0
    assert seen["dataset"] == "mini" and "schema_path" not in seen

    assert cli.main(["eval", "--llm", "fake", "--dataset", "mini", "--schema", "skeleton"]) == 0
    assert seen["schema_path"] == "skeleton"
