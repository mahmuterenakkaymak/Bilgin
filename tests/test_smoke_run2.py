"""Run 2'nin duman testi: beş komut da depo kökünden gerçek bir alt süreç olarak koşar.

``test_smoke.py``nin Run 2 karşılığı; burada da hiçbir şey yer değiştirmez: veritabanı
``data/test.db``'ye, indeks ``index/``e, raporlar ``eval_out/``a yazılır — üçü de .gitignore'da.
Model de embedder de ``fake`` olduğu için ağ istemiyor; ``--compare``ın üç modu da 40/40 geçmesi yine
de bir şey söylüyor, çünkü skor sahte cevaptan değil gerçek SQLite üzerinde yürütülen altın SQL'den
geliyor. README'nin komutları ve bayrakları aynı testte duruyor: dokümanda yazılı olmayan bir bayrak
kullanıcının elinde yok sayılır.
"""

import os
import re
import subprocess
import sys

import pytest

from nl2sql import config
from nl2sql.eval import runner

GOLDEN = runner.load_golden()
Q04 = next(line for line in GOLDEN if line["id"] == "Q04")
MODES = list(config.MODES)
SUBCOMMANDS = ("build-db", "build-index", "eval-retrieval", "ask", "eval")
FLAGS = ("--seed", "--embed", "--k", "--llm", "--mode", "--tag", "--only", "--compare", "--fresh")
VERDICT = "Karar:"
README_MARKS = (
    "8891",
    "NL2SQL_EMBED_BASE_URL",
    "NL2SQL_EMBED_MODEL",
    "NL2SQL_EMBED_API_KEY",
    "python -m eval.review",
    "eval/REVIEW.md",
    "EmbeddingGemma",
    "bge-m3",
    VERDICT,
)


def run(*argv: str) -> subprocess.CompletedProcess:
    """Depo kökünde alt süreç; backend sqlite ve çıktı UTF-8 (test_smoke ile aynı iki sabitleme)."""
    return subprocess.run(
        [sys.executable, "-m", "nl2sql", *argv],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "NL2SQL_BACKEND": "sqlite", "PYTHONIOENCODING": "utf-8"},
    )


@pytest.fixture(scope="module")
def world():
    """Modül boyunca tek kurulum: ``build-db`` ve ``build-index --embed fake``; sonrakiler aynı
    dosyaları okur, yani indeksin bayat olup olmadığını da gerçekten sınamış olurlar."""
    result = None
    for argv in (("build-db",), ("build-index", "--embed", "fake")):
        result = run(*argv)
        assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_build_index_writes_the_files_the_agent_reads(world):
    for name in ("docs.json", "vectors.json", "meta.json"):
        assert (config.INDEX_DIR / name).exists(), f"{name} yazılmadı"
    assert "Embedder: fake:" in world.stdout
    assert str(config.INDEX_DIR) in world.stdout


def test_compare_runs_three_modes_and_prints_a_verdict(world):
    result = run("eval", "--compare", "--llm", "fake")
    assert result.returncode == 0, result.stdout + result.stderr

    markdown = (config.EVAL_OUT / "compare" / "latest" / "report.md").read_text(encoding="utf-8")
    assert VERDICT in result.stdout
    assert VERDICT in markdown
    for mode in MODES:
        assert f"| {mode} |" in markdown, f"{mode} karşılaştırma tablosunda yok"
        assert re.search(
            rf"^{mode}\s+{len(GOLDEN)}/{len(GOLDEN)}", result.stdout, re.MULTILINE
        ), f"{mode} satırı ekranda yok: {result.stdout}"


def test_eval_retrieval_measures_recall_without_a_model_or_an_index_on_disk(world):
    result = run("eval-retrieval", "--embed", "fake")
    assert result.returncode == 0, result.stdout + result.stderr

    assert "Ortalama:" in result.stdout
    report = (config.EVAL_OUT / "retrieval" / "latest" / "report.md").read_text(encoding="utf-8")
    assert f"Soru: {len(GOLDEN)}" in report


def test_ask_in_rag_mode_searches_before_it_answers(world):
    result = run("ask", Q04["question"], "--llm", "fake", "--mode", "rag")
    assert result.returncode == 0, result.stdout + result.stderr

    assert "Mod: rag" in result.stdout
    assert "search_schema" in result.stdout, "arama adımı dökülmedi"
    assert Q04["sql"] in result.stdout


@pytest.mark.parametrize("command", SUBCOMMANDS + FLAGS)
def test_the_readme_documents_every_subcommand_and_flag(command):
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    assert f"`{command}`" in readme


@pytest.mark.parametrize("mark", README_MARKS)
def test_the_readme_documents_the_run_2_setup(mark):
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    assert mark in readme
