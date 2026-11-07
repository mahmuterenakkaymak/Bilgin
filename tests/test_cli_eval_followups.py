# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``eval --followups``: ardışık soru zincirlerinin ölçümü göründüğü her yerde (PLAN R7-14).

Koşum yine FakeLLM iledir; veritabanı, audit, konuşma deposu ve raporun hepsi tmp klasörde, yani
test repoya hiçbir şey yazmıyor. Zincirler altın koşumun üstüne eklenir, onun yerini almaz:
ekrandaki Skor ile report.json'un skoru altın setin, ``followups`` bloğu ise ayrı bir ölçümdür.
Üç doğruluk (tur / zincir / bağlam) ekranın toplam satırında, report.json'da ve report.md'nin
"Ardışık sorular" bölümünde aynı sayıyı söyler; zincirin her turu kendi sorusuyla tabloda durur.
İki arıza kullanıcının kendi düzelteceği şeylerdir ve iz dökümü değil tek cümledir: kümenin
ardışık seti yoktur (kod 2, rapor yazılmaz), ya da düz koşum hiç zincir ölçmez.
"""

import json

import pytest
from pathlib import Path

from bilgin import config, datasets
from bilgin.cli import main as cli
from bilgin.schema_map import build

DATASET = "synthetic_erp"
NO_FOLLOWUPS = "Bu veri kümesinde ardışık soru seti yok."


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modül boyunca tek kurulum: sentetik dünyanın veritabanı ve audit'i tek tmp klasörde."""
    paths = tmp_path_factory.mktemp("cli-eval-followups")
    database = paths / "test.db"
    build.build_db(config.SEED, database, paths / "test.sql")
    return database, paths / "audit.jsonl"


def run(world, tmp_path, **kwargs):
    """``evaluate``ın tek çağrısı; sahte istemci zincirleri de tanıdığı için her tur kendi golden'ı."""
    database, audit = world
    out_dir = tmp_path / "eval_out"
    ds = datasets.load_dataset(DATASET)
    code = cli.evaluate(
        cli.make_client("fake", "full", ds),
        db_path=database,
        audit_path=audit,
        out_dir=out_dir / "full",
        dataset=DATASET,
        **kwargs,
    )
    return code, out_dir


def written(out_dir) -> dict:
    return json.loads((out_dir / "full" / "latest" / "report.json").read_text(encoding="utf-8"))


def markdown(out_dir) -> str:
    return (out_dir / "full" / "latest" / "report.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ ardışık set


def test_the_chains_are_measured_everywhere_they_show_up(world, tmp_path, capsys):
    code, out_dir = run(world, tmp_path, followups=True)
    out = capsys.readouterr().out

    assert code == 0
    data = written(out_dir)
    followups = data["followups"]
    # Sahte istemci her turu kendi golden SQL'iyle ve golden uses_turns notuyla cevaplıyor (R7-13).
    assert followups["turn_accuracy"] == 1.0
    assert followups["chain_accuracy"] == 1.0
    assert followups["context_accuracy"] == 1.0
    assert data["score"]["passed"] == data["score"]["total"], "zincir altın setin yerine geçmez"

    chains = datasets.load_dataset(DATASET).followups()
    assert followups["chains"] == len(chains)
    assert followups["turns"] == sum(len(chain["turns"]) for chain in chains)

    text = markdown(out_dir)
    assert "## Ardışık sorular" in text
    assert "| Zincir | Tur | Soru | Sonuç | Bağlam |" in text
    for chain in chains:
        assert f"### {chain['id']}" in text
        for turn in chain["turns"]:
            assert turn["question"] in text, "tur kendi sorusuyla tabloda durur"

    assert "Ardışık sorular:" in out and "Toplam:" in out
    for chain in chains:
        assert chain["id"] in out, "zincir başına bir satır"


def test_a_dataset_without_the_set_names_the_missing_one(world, tmp_path, capsys, monkeypatch):
    # Updated 2026-10-26 (Eren: "otomatik olsun"): wwi gained this set for the visual flows (Run 8 brief); the mini fixture has none.
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(Path(__file__).parent / "fixtures" / "datasets"))
    out_dir = tmp_path / "eval_out"
    code = cli.evaluate(
        cli.make_client("fake"), out_dir=out_dir, dataset="mini", followups=True
    )
    out = capsys.readouterr().out

    assert code == 2
    assert NO_FOLLOWUPS in out and "Traceback" not in out
    assert "Skor:" not in out and not out_dir.exists(), "koşulmayan bir koşunun raporu yazılmaz"


def test_a_plain_run_measures_no_chains(world, tmp_path):
    code, out_dir = run(world, tmp_path)

    assert code == 0
    assert "followups" not in written(out_dir), "zincir koşulmayan koşuda anahtar hiç yazılmaz"
    assert "Ardışık sorular" not in markdown(out_dir)
