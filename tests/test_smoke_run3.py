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
MAP = "tests/fixtures/map_erp_style.xlsx"

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


def test_import_map_accept_writes_the_schema_the_next_commands_read(world):
    assert config.IMPORTED_PATH.exists(), "import-map --accept şemayı yazmadı"
    assert "Şema yazıldı" in world["import-map"].stdout


def test_introspect_writes_the_skeleton_eval_reads(world):
    assert config.SKELETON_PATH.exists(), "introspect iskeleti yazmadı"
    assert "İskelet:" in world["introspect"].stdout


def test_diff_map_compares_the_map_against_the_live_database(world):
    result = run("diff-map", "--excel", "schema/imported.json", "--db")
    assert result.returncode == 0, result.stdout + result.stderr

    assert config.DIFF_JSON_PATH.exists() and config.DIFF_MD_PATH.exists()
    assert "JSON:" in result.stdout and "Markdown:" in result.stdout


def test_merge_map_writes_a_merged_schema_to_out(world, tmp_path):
    out = tmp_path / "merged.json"
    result = run("merge-map", "--excel", "schema/imported.json", "--db", "--out", str(out))
    assert result.returncode == 0, result.stdout + result.stderr

    assert out.exists(), "merge-map --outa yazmadı"
    assert "Birleşik şema yazıldı" in result.stdout


def test_make_login_script_writes_the_readonly_login(world):
    result = run("make-login-script")
    assert result.returncode == 0, result.stdout + result.stderr

    assert config.LOGIN_SCRIPT_PATH.exists()
    assert "Betik:" in result.stdout


def test_eval_measures_against_the_skeleton_schema(world):
    result = run("eval", "--schema", "skeleton", "--llm", "fake")
    assert result.returncode == 0, result.stdout + result.stderr

    assert "skeleton.json" in result.stdout, "ölçüm iskelet şemayla koşulduğunu söylemedi"
    assert "Skor:" in result.stdout
    assert (config.EVAL_OUT / "full" / "latest" / "report.json").exists()


def test_compare_with_repeat_runs_every_mode_twice(world):
    result = run("eval", "--compare", "--repeat", "2", "--llm", "fake")
    assert result.returncode == 0, result.stdout + result.stderr

    assert "Tekrar: her mod 2 kez koşuluyor" in result.stdout
    assert "Karar:" in result.stdout


def test_eval_retrieval_measures_the_three_variants(world):
    result = run("eval-retrieval", "--embed", "fake")
    assert result.returncode == 0, result.stdout + result.stderr

    assert "Ortalama:" in result.stdout
    assert "taban" in result.stdout and "+komşu" in result.stdout and "+eşanlam" in result.stdout
    assert (config.EVAL_OUT / "retrieval" / "latest" / "report.md").exists()


def test_ask_in_auto_mode_prints_the_resolution(world):
    result = run("ask", QUESTION, "--llm", "fake")
    assert result.returncode == 0, result.stdout + result.stderr

    assert "Mod: auto ->" in result.stdout, "auto çözümü ekrana basılmadı"
    assert GOLDEN_SQL in result.stdout


@pytest.mark.parametrize("command", SUBCOMMANDS)
def test_the_readme_documents_every_subcommand(command):
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    assert f"`{command}`" in readme, f"{command} README'de yok"


@pytest.mark.parametrize("flag", FLAGS)
def test_the_readme_documents_every_flag(flag):
    readme = (config.ROOT / "README.md").read_text(encoding="utf-8")
    assert flag in readme, f"{flag} README'de yok"
