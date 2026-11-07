# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T413: compare ve follow-up ölçümlerinin dili (R8-12).

Karşılaştırma, model-karşılaştırma ve geri çağırma ekranı ile markdown'ı artık kataloğun
``compare.*`` / ``retrieval.*`` anahtarlarından kuruluyor; diskteki rapor hangi dille yazıldığını
``lang`` alanıyla kendisi söylüyor. Test üç şeyi sabitliyor: ``--lang en`` koşan bir karşılaştırma
İngilizce metin üretir ve raporu ``lang: "en"`` taşır, Türkçe varsayılan rapora ``lang`` anahtarı
yazılmaz (Run 2'nin anahtar kümesi korunur), ve beş modülün kullanıcıya bakan Türkçe sabiti kalmadı.
"""

import json

import pytest

from bilgin import config
from bilgin.agent import fake
from bilgin.cli import main as cli
from bilgin.eval import runner
from bilgin.i18n.detect import TURKISH_LETTERS
from bilgin.i18n.scan import user_literals
from bilgin.schema_map import build

GOLDEN = runner.load_golden()
MODES = list(config.MODES)
MODULES = ["compare", "compare_models", "compare_modes", "retrieval", "followups"]


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modül boyunca tek kurulum: veritabanı, sahte indeks ve audit tek tmp klasörde."""
    paths = tmp_path_factory.mktemp("compare-lang")
    database = paths / "test.db"
    build.build_db(config.SEED, database, paths / "test.sql")
    cli.build_index("fake", index_dir=paths / "index")
    return database, paths / "index", paths / "audit.jsonl"


def compare(world, tmp_path, **kwargs):
    database, index, audit = world
    out_dir = tmp_path / "eval_out"
    code = cli.compare_modes(
        lambda mode: fake.for_golden(GOLDEN, mode=mode),
        db_path=database,
        audit_path=audit,
        out_dir=out_dir,
        index_dir=index,
        **kwargs,
    )
    return code, out_dir


def comparison(out_dir) -> dict:
    latest = out_dir / "compare" / "latest"
    return json.loads((latest / "report.json").read_text(encoding="utf-8"))


def markdown(out_dir) -> str:
    return (out_dir / "compare" / "latest" / "report.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ compare --lang en


def test_compare_in_english_reports_its_lang_and_prints_english(world, tmp_path, capsys):
    code, out_dir = compare(world, tmp_path, lang="en")
    out = capsys.readouterr().out
    data = comparison(out_dir)

    assert code == 0
    assert data["lang"] == "en"
    assert data["verdict"]["line"].startswith("Verdict:")
    assert data["verdict"]["line"] in out
    assert "Mode comparison" in markdown(out_dir)
    assert "context" in out and "tools" in out, "mod satırının etiketleri İngilizce"
    assert not any(char in TURKISH_LETTERS for char in out), f"Türkçe harf sızdı: {out}"


def test_compare_default_turkish_report_carries_no_lang_key(world, tmp_path):
    """Run 2'nin raporu ``lang`` taşımıyordu; Türkçe varsayılan o anahtarı yazmamaya devam eder."""
    compare(world, tmp_path)
    assert "lang" not in comparison(tmp_path / "eval_out")


# ------------------------------------------------------------------ eval-retrieval --lang en


def test_eval_retrieval_in_english(tmp_path, capsys):
    out_dir = tmp_path / "retrieval"
    code = cli.eval_retrieval("fake", out_dir=out_dir, lang="en")
    out = capsys.readouterr().out

    assert code == 0
    assert "Question" in out and "missing" in out
    assert "Average:" in out and "Tag averages" in out
    assert "Ortalama:" not in out and "eksik" not in out
    md = (out_dir / "latest" / "report.md").read_text(encoding="utf-8")
    assert not any(char in TURKISH_LETTERS for char in md)
    assert "lang" not in json.loads((out_dir / "latest" / "report.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ modüllerin sabitleri


@pytest.mark.parametrize("module", MODULES)
def test_module_has_no_turkish_user_literals(module):
    assert user_literals(f"bilgin/eval/{module}.py") == []
