"""Run 4'ün duman testi: iki dünya da depo kökünden gerçek bir alt süreç olarak koşar, hepsi kod 0.

``test_smoke_run3``ün Run 4 karşılığı; farkı ``--dataset``: aynı beş komut hem ``synthetic_erp``i
hem ``wwi``yi kuruyor ve ölçüyor. Yine hiçbir şey yer değiştirmez — veritabanı ``data/<küme>.db``ye,
indeks ``index/<küme>/``e, raporlar ``eval_out/<küme>/``e gider (``synthetic_erp`` kökün
varsayılanlarıdır) ve hepsi .gitignore'da; son test bunu ``git check-ignore`` ile tek tek sınar.
Model de embedder de ``fake``, yani ağ istemiyor; ``--models``ın iki penceresi de uç nokta
yoklamasız koşuyor (R4-13), dolayısıyla 16K'lık profilin taşmaları bile bir sonuçtur, hata değil.
"""

import json
import os
import subprocess
import sys

import pytest

from nl2sql import config, datasets

DATASETS = ("synthetic_erp", "wwi")
MODELS = "strata,qwen27b-16k"
MODES = "full_rules,rag"
PIPELINE = (
    ("build-db",),
    ("build-index", "--embed", "fake"),
    ("eval-retrieval", "--embed", "fake"),
    ("eval", "--llm", "fake", "--mode", "rag"),
)
WWI_FIRST = datasets.load_dataset("wwi").golden()[0]


def run(*argv: str) -> subprocess.CompletedProcess:
    """Depo kökünde alt süreç; backend sqlite ve çıktı UTF-8 (test_smoke ile aynı iki sabitleme)."""
    return subprocess.run(
        [sys.executable, "-m", "nl2sql", *argv],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "NL2SQL_BACKEND": "sqlite", "PYTHONIOENCODING": "utf-8"},
    )


def check_ignore(path) -> int:
    """Yol elenme kuralına mı takılıyor; 0 = eleniyor (test_gitignore_root ile aynı kapı)."""
    return subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path.as_posix()],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
    ).returncode


def latest_compare(name: str) -> tuple:
    """O kümenin son model-karşılaştırma raporu: adlar zaman damgalı, sözlük sırası en yenisi."""
    files = sorted(datasets.load_dataset(name).eval_out.glob(f"compare_{name}_*.json"))
    assert files, f"compare_{name}_*.json yazılmadı"
    return files[-1], json.loads(files[-1].read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def world():
    """Modül boyunca tek kurulum: her iki kümenin dört komutu kendi sırasında, hepsi kod 0.

    Sonrakiler bu komutların yazdığı gerçek dosyaları okuyor — ``data/<küme>.db``, taze indeks,
    ``eval_out/<küme>/rag/latest`` —, yani boru hattının kendisi sınamış oluyor.
    """
    results = {}
    for name in DATASETS:
        for argv in PIPELINE:
            result = run(*argv, "--dataset", name)
            assert result.returncode == 0, f"{argv[0]} ({name}): {result.stdout}{result.stderr}"
            results[(name, argv[0])] = result
    return results


@pytest.mark.parametrize("name", DATASETS)
def test_build_db_writes_the_datasets_own_database_and_script(world, name):
    ds = datasets.load_dataset(name)
    assert ds.db_path.exists(), f"{ds.db_path} kurulmadı"
    assert ds.mssql_script.exists(), f"{ds.mssql_script} yazılmadı"

    stdout = world[(name, "build-db")].stdout
    assert f"({name})" in stdout, "küme satırı ekrana basılmadı"
    assert "Sağlama (sha256):" in stdout


@pytest.mark.parametrize("name", DATASETS)
def test_build_index_writes_an_index_the_same_dataset_reads(world, name):
    ds = datasets.load_dataset(name)
    for file in ("docs.json", "vectors.json", "meta.json"):
        assert (ds.index_dir / file).exists(), f"{name}: {file} yazılmadı"

    stdout = world[(name, "build-index")].stdout
    assert "Embedder: fake:" in stdout
    assert str(ds.index_dir) in stdout, "indeks klasörü kümenin klasörü değil"


@pytest.mark.parametrize("name", DATASETS)
def test_eval_retrieval_measures_the_dataset_and_writes_its_own_report(world, name):
    ds = datasets.load_dataset(name)
    report = ds.eval_out / "retrieval" / "latest" / "report.md"
    assert report.exists(), f"{report} yazılmadı"

    stdout = world[(name, "eval-retrieval")].stdout
    assert "Ortalama:" in stdout
    assert str(ds.eval_out) in stdout, "rapor kümenin kendi klasörüne yazılmadı"


@pytest.mark.parametrize("name", DATASETS)
def test_eval_rag_runs_every_golden_question_of_the_dataset(world, name):
    ds = datasets.load_dataset(name)
    report = json.loads(
        (ds.eval_out / "rag" / "latest" / "report.json").read_text(encoding="utf-8")
    )
    stdout = world[(name, "eval")].stdout

    assert report["dataset"] == name, "rapor başka bir kümeyi ölçmüş"
    assert report["score"]["total"] == len(ds.golden()), "altın soruların tamamı koşulmadı"
    assert f"Skor: {report['score']['passed']}/" in stdout


def test_ask_answers_a_wwi_golden_question_through_rag(world):
    result = run("ask", WWI_FIRST["question"], "--llm", "fake", "--dataset", "wwi", "--mode", "rag")
    assert result.returncode == 0, result.stdout + result.stderr

    assert "Veri kümesi:" in result.stdout
    assert "Mod: rag" in result.stdout
    assert "search_schema" in result.stdout, "arama adımı dökülmedi"
    assert WWI_FIRST["sql"] in result.stdout


@pytest.mark.parametrize("name", DATASETS)
def test_compare_models_runs_both_windows_over_both_modes(world, name):
    result = run(
        "eval",
        "--compare",
        "--models",
        MODELS,
        "--modes",
        MODES,
        "--dataset",
        name,
        "--llm",
        "fake",
    )
    assert result.returncode == 0, result.stdout + result.stderr

    path, report = latest_compare(name)
    assert report["dataset"] == name
    assert report["models"] == list(MODELS.split(","))
    assert report["modes"] == list(MODES.split(","))
    for model in report["models"]:
        for mode in report["modes"]:
            assert report["cells"][model][mode], f"{model}/{mode} hücresi yok"
    assert path.stem in result.stdout, "raporun yolu ekranda değil"  # ekran .mdyi söyler, jsonu değil


def test_every_output_the_run_4_pipeline_writes_is_gitignored():
    for name in DATASETS:
        ds = datasets.load_dataset(name)
        for path in (
            ds.db_path,
            ds.mssql_script,
            ds.index_dir / "meta.json",
            ds.eval_out / "rag" / "latest" / "report.json",
            ds.eval_out / f"compare_{name}_20260101-000000.json",
        ):
            relative = path.relative_to(config.ROOT)
            assert check_ignore(relative) == 0, f"{relative} .gitignore'da değil"
