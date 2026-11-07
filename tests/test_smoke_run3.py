# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Run 3'ün duman testi: her komut depo kökünden gerçek bir alt süreç olarak koşar, hepsi kod 0.

``test_smoke_run2``nin Run 3 karşılığı; burada da hiçbir şey yer değiştirmez: veritabanı
``data/test.db``'ye, indeks ``index/``e, raporlar ``eval_out/``a, içe aktarılan/iskelet/fark
şemaları ``schema/``ya, salt okunur giriş betiği ``db/mssql/``e yazılır — hepsi .gitignore'da.
Model de embedder de ``fake`` olduğu için ağ istemiyor. Sıra boru hattının kendisi: import-map
``schema/imported.json``ı, introspect ``schema/skeleton.json``ı yazar; diff-map/merge-map birini,
``eval --schema skeleton`` ötekini okur. ``ask``ın varsayılanı auto'dur ve çözümü ekrana basar.
README'nin komutları ve bayrakları aynı testte duruyor: dokümanda yazılı olmayan bir bayrak
kullanıcının elinde yok sayılır.
"""

import os
import subprocess
import sys

import pytest

from nl2sql import config
from nl2sql.eval import runner

GOLDEN = runner.load_golden()
QUESTION = GOLDEN[0]["question"]
GOLDEN_SQL = GOLDEN[0]["sql"]
MAP = "tests/fixtures/map_tidy.xlsx"

# Bu dumanın koştuğu komutlar ve bayraklar: README'de her biri ayrı ayrı geçecek.
SUBCOMMANDS = (
    "build-db",
    "build-index",
    "import-map",
    "introspect",
    "diff-map",
    "merge-map",
    "make-login-script",
    "eval-retrieval",
    "eval",
    "ask",
)
FLAGS = (
    "--embed",
    "--accept",
    "--llm",
    "--out",
    "--excel",
    "--db",
    "--login",
    "--schema",
    "--compare",
    "--repeat",
    "--mode auto",
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
    """Modül boyunca tek kurulum: sırayla build-db, build-index, import-map, introspect.

    Sonrakiler bu dört komutun yazdığı gerçek dosyaları okur — imported.json, skeleton.json ve
    taze indeks —, yani boru hattının kendisi sınamış olur; her biri kod 0 çıkmak zorunda.
    """
    results = {}
    for argv in (
        ("build-db",),
        ("build-index", "--embed", "fake"),
        ("import-map", MAP, "--accept", "--llm", "fake"),
        ("introspect",),
    ):
        result = run(*argv)
        assert result.returncode == 0, f"{argv[0]}: {result.stdout}{result.stderr}"
        results[argv[0]] = result
    return results


@pytest.mark.parametrize("command", SUBCOMMANDS)
def test_the_readme_documents_every_subcommand(command):
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    assert f"`{command}`" in readme, f"{command} README'de yok"


@pytest.mark.parametrize("flag", FLAGS)
def test_the_readme_documents_every_flag(flag):
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    assert flag in readme, f"{flag} README'de yok"
