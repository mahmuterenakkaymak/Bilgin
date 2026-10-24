"""Run 5'in dumanı: ``serve`` gerçek bir sunucu olarak ayağa kalkıyor mu?

``scripts/smoke_serve.py`` depo kökünden çağrılır; ondan önce aynı kökte ``build-db`` ve
``build-index --embed fake`` koşar, çünkü sunucu o dünyayı okur. Beklenen üç ✓ satırı sağlık,
cevaplanan altın soru ve BOM'la başlayan CSV — yani portu dinleyen bir API, uçtan uca bir cevap
ve o cevabın indirilebilir hali. Model ``fake``, dolayısıyla ağ istenmiyor. Dumanın yazdıkları
(``data/*.db``, ``index/``, ``logs/``) .gitignore'da kalmak zorunda; son test ``git check-ignore``
ile tek tek sınar (``test_smoke_run4`` ile aynı kapı).
"""

import os
import subprocess
import sys

import pytest

from nl2sql import config, datasets

PORT = "8779"
CHECKS = ("✓ sunucu hazır", "✓ soru cevaplandı", "✓ dışa aktarım")


def run(*argv: str) -> subprocess.CompletedProcess:
    """Depo kökünde alt süreç; backend sqlite ve çıktı UTF-8 (test_smoke ile aynı iki sabitleme)."""
    return subprocess.run(
        [sys.executable, *argv],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "NL2SQL_BACKEND": "sqlite", "PYTHONIOENCODING": "utf-8"},
    )


@pytest.fixture(scope="module")
def smoke():
    """Kurulu dünyanın üstünde tek duman koşusu; çıktısını tüm testler okur."""
    for argv in (
        ("-m", "nl2sql", "build-db"),
        ("-m", "nl2sql", "build-index", "--embed", "fake"),
    ):
        result = run(*argv)
        assert result.returncode == 0, f"{' '.join(argv)}: {result.stdout}{result.stderr}"
    return run("scripts/smoke_serve.py", "--port", PORT)


def test_serve_answers_a_golden_question_and_offers_its_csv(smoke):
    assert smoke.returncode == 0, smoke.stdout + smoke.stderr
    for line in CHECKS:
        assert line in smoke.stdout, f"{line} basılmadı"


def test_everything_the_serve_smoke_writes_is_gitignored(smoke):
    ds = datasets.load_dataset(config.DEFAULT_DATASET)
    for path in (
        ds.db_path,
        ds.index_dir / "meta.json",
        config.APP_DB_PATH,
        config.ASK_LOG,
        config.AUDIT_LOG,
    ):
        relative = path.relative_to(config.ROOT)
        result = subprocess.run(
            ["git", "check-ignore", "--no-index", "-q", relative.as_posix()],
            cwd=config.ROOT,
            capture_output=True,
            encoding="utf-8",
        )
        assert result.returncode == 0, f"{relative} .gitignore'da değil"
