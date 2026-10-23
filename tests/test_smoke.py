"""Baştan sona duman testi: üç komut da depo kökünden gerçek bir alt süreç olarak koşar.

Burada hiçbir şey yer değiştirmez: ``python -m nl2sql`` gerçekten çalışır, veritabanı
``data/test.db``'ye, rapor ``eval_out/``a, audit ``logs/``a yazılır — üçü de .gitignore'da, yani
test reponun kendi klasörlerini kurar ve temiz bırakır. Model ``--llm fake`` olduğu için ağ istemiyor;
skor yine de 10/10 olmak zorunda, çünkü altın SQL sahte cevaptan değil gerçek SQLite üzerinde
yürütülmüş sonuçlardan geçiyor. README'nin üç komutu da anlatması aynı testte duruyor: komut adı
dokümanda yoksa kullanıcı onu hiç bulamaz.
"""

import os
import subprocess
import sys

import pytest

from nl2sql import config
from nl2sql.eval import runner

GOLDEN = runner.load_golden()
SUBCOMMANDS = ("build-db", "ask", "eval")
SCORE = f"## Skor: {len(GOLDEN)}/{len(GOLDEN)}"


def run(*argv: str) -> subprocess.CompletedProcess:
    """Depo kökünde alt süreç. Ortam iki yerde sabitlenir: backend sqlite olsun (başka bir
    kabuktaki NL2SQL_BACKEND testi MSSQL'e bağlamaya çalışmasın) ve çıktı UTF-8 gelsin."""
    return subprocess.run(
        [sys.executable, "-m", "nl2sql", *argv],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "NL2SQL_BACKEND": "sqlite", "PYTHONIOENCODING": "utf-8"},
    )


@pytest.fixture(scope="module")
def built():
    """Modül boyunca tek ``build-db``: sonrakiler aynı data/test.db dosyasını okur."""
    result = run("build-db")
    assert result.returncode == 0, result.stdout + result.stderr
    return result


def test_build_db_creates_the_database_the_other_commands_read(built):
    assert config.DB_PATH.exists()
    assert str(config.DB_PATH) in built.stdout


def test_eval_scores_the_fake_model_full_marks(built):
    result = run("eval", "--llm", "fake")
    assert result.returncode == 0, result.stdout + result.stderr

    report = (config.EVAL_OUT / "latest" / "report.md").read_text(encoding="utf-8")
    assert f"Skor: {len(GOLDEN)}/{len(GOLDEN)}" in result.stdout
    assert SCORE in report
    assert "Devam" in report


@pytest.mark.parametrize("qid", ["Q01", "Q03"])
def test_ask_answers_a_golden_question_end_to_end(built, qid):
    line = next(entry for entry in GOLDEN if entry["id"] == qid)
    result = run("ask", line["question"], "--llm", "fake")

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"Soru: {line['question']}" in result.stdout
    assert line["sql"] in result.stdout
    assert "Sonuç:" in result.stdout


@pytest.mark.parametrize("command", SUBCOMMANDS)
def test_the_readme_documents_every_subcommand(command):
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    assert f"`{command}`" in readme
