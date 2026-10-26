"""Run 6'nın onboarding dumanı: ``scripts/smoke_onboard.py`` şablondan yeni bir kümeye uçtan uca
gidiyor mu?

Test sunucu açmaz; betiği alt süreç olarak koşar, yani ölçtüğü şey betiğin çıkış kodu ve bastığı
✓ satırlarıdır. Öncesinde ``test_smoke_run5`` ile aynı iki hazırlık (``build-db`` + ``build-index
--embed fake``): sunucu o dünyayı okur. Satırlar iddiaların adıdır -- giriş, inen şablon, hatasız
önizleme, uygulanan küme, kurulan indeks, şemadan doğan SQLite dosyası, etkin küme ve cevaplanan
soru. Son test depo kökündeki ``real_datasets/`` ağacının dumanın öncesine birebir döndüğünü ölçer:
duman geçici bir gerçek-kümeler kökü kullanır, depo köküne küme eklemez. Model ``fake``, dolayısıyla
ağ istenmiyor.
"""

import hashlib
import os
import subprocess
import sys

import pytest

from nl2sql import config

PORT = "8780"
CHECKS = (
    "✓ giriş",
    "✓ şablon indirildi",
    "✓ önizleme temiz",
    "✓ uygulandı",
    "✓ indeks hazır",
    "✓ veritabanı kuruldu",
    "✓ küme etkin",
    "✓ soru cevaplandı",
)


def run(*argv: str) -> subprocess.CompletedProcess:
    """Depo kökünde alt süreç; backend sqlite ve çıktı UTF-8 (test_smoke_run5 ile aynı iki sabitleme)."""
    return subprocess.run(
        [sys.executable, *argv],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "NL2SQL_BACKEND": "sqlite", "PYTHONIOENCODING": "utf-8"},
    )


def real_datasets_tree() -> dict:
    """Depo kökündeki gerçek kümelerin imzası: göreli yol -> içerik özeti (klasör yoksa boş)."""
    root = config.REAL_DATASETS_DIR
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


@pytest.fixture(scope="module")
def smoke():
    """Kurulu dünyanın üstünde tek duman koşusu; öncesi/sonrası imzayı da taşıyan üçlü."""
    before = real_datasets_tree()
    for argv in (
        ("-m", "nl2sql", "build-db"),
        ("-m", "nl2sql", "build-index", "--embed", "fake"),
    ):
        result = run(*argv)
        assert result.returncode == 0, f"{' '.join(argv)}: {result.stdout}{result.stderr}"
    result = run("scripts/smoke_onboard.py", "--port", PORT)
    return result, before, real_datasets_tree()


def test_the_onboarding_smoke_walks_template_to_answer(smoke):
    result, _, _ = smoke
    assert result.returncode == 0, result.stdout + result.stderr
    for line in CHECKS:
        assert line in result.stdout, f"{line} basılmadı"


def test_the_smoke_leaves_the_repo_real_datasets_untouched(smoke):
    _, before, after = smoke
    assert after == before
