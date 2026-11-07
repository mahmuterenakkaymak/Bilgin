# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Run 5'in dumanı: ``serve`` gerçek bir sunucu olarak ayağa kalkıyor mu?

``scripts/smoke_serve.py`` depo kökünden çağrılır; ondan önce aynı kökte ``build-db`` ve
``build-index --embed fake`` koşar, çünkü sunucu o dünyayı okur. Beklenen üç ✓ satırı sağlık,
cevaplanan altın soru ve BOM'la başlayan CSV — yani portu dinleyen bir API, uçtan uca bir cevap
ve o cevabın indirilebilir hali. ``--ui`` bir satır daha ister: ``npm --prefix web run build``ın
çıktısı ``/``da ve onun ``/assets``inde görünmeli. Model ``fake``, dolayısıyla ağ istenmiyor.
Dumanın yazdıkları (``data/*.db``, ``index/``, ``logs/``) .gitignore'da kalmak zorunda; son test
``git check-ignore`` ile tek tek sınar (``test_smoke_run4`` ile aynı kapı).
"""

import os
import shutil
import subprocess
import sys

import pytest

from bilgin import config, datasets

PORT = "8779"
PORT_UI = "8780"
CHECKS = ("✓ sunucu hazır", "✓ soru cevaplandı", "✓ dışa aktarım")
# --ui aynı üç satırı bir dördüncüsüyle birlikte ister: ekran ve onun hashli dosyası.
UI_CHECKS = ("✓ sunucu hazır", "✓ derlenmiş ekran", "✓ soru cevaplandı", "✓ dışa aktarım")


def run(*argv: str) -> subprocess.CompletedProcess:
    """Depo kökünde alt süreç; backend sqlite ve çıktı UTF-8 (test_smoke ile aynı iki sabitleme)."""
    return subprocess.run(
        [sys.executable, *argv],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "BILGIN_BACKEND": "sqlite", "PYTHONIOENCODING": "utf-8"},
    )


def run_npm(*argv: str) -> subprocess.CompletedProcess:
    """Depo kökünde npm; Windows'ta ``npm`` bir .cmd, o yüzden tam yolla çağrılır."""
    return subprocess.run(
        [shutil.which("npm") or "npm", *argv],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture(scope="module")
def smoke():
    """Kurulu dünyanın üstünde tek duman koşusu; çıktısını tüm testler okur."""
    for argv in (
        ("-m", "bilgin", "build-db"),
        ("-m", "bilgin", "build-index", "--embed", "fake"),
    ):
        result = run(*argv)
        assert result.returncode == 0, f"{' '.join(argv)}: {result.stdout}{result.stderr}"
    return run("scripts/smoke_serve.py", "--port", PORT)


@pytest.fixture(scope="module")
def smoke_ui(smoke):
    """Aynı dünyanın üstünde ekranlı duman; ``smoke`` db ve indeksi kurar, derleme de oradan gelir."""
    build = run_npm("--prefix", "web", "run", "build")
    assert build.returncode == 0, f"npm run build: {build.stdout}{build.stderr}"
    return run("scripts/smoke_serve.py", "--port", PORT_UI, "--ui")


def test_serve_answers_a_golden_question_and_offers_its_csv(smoke):
    assert smoke.returncode == 0, smoke.stdout + smoke.stderr
    for line in CHECKS:
        assert line in smoke.stdout, f"{line} basılmadı"


def test_the_built_screen_is_the_page_serve_serves(smoke_ui):
    assert smoke_ui.returncode == 0, smoke_ui.stdout + smoke_ui.stderr
    for line in UI_CHECKS:
        assert line in smoke_ui.stdout, f"{line} basılmadı"


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
