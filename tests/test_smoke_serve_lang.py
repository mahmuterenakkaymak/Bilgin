"""İngilizce duman: ``--lang en`` gerçek bir sunucuda arayüz dilini gerçekten konuşturuyor mu?

Test sunucu açmaz; ``scripts/smoke_serve.py --lang en``ı alt süreç olarak koşar, yani ölçtüğü şey
betiğin kendi çıkış kodu ve bastığı ✓ satırlarıdır (``test_smoke_run7``ın deseni). Öncesinde
``build-db --dataset wwi`` + ``build-index --embed fake --dataset wwi``: ``--lang`` İngilizce altın
kümeyi ölçtüğü için kümesini kendisi söyler ve sunucu o dünyayı okur. Satırların adı iddiaların
adıdır -- ``PUT /api/auth/me``le yazılan tercih, cevabı İngilizce olan ilk İngilizce altın soru
(E01), İngilizce konuşan 400 ve sayfa adları İngilizce inen şablon. Port boşta bir numaradır
(``socket``e 0 sorulur), model ``fake``, dolayısıyla ağ istenmiyor.
"""

import os
import socket
import subprocess
import sys

import pytest

from nl2sql import config

CHECKS = (
    "✓ kullanıcının dili en",
    "✓ sunucu hazır",
    "✓ soru cevaplandı",
    "✓ boş sorunun en reddi",
    "✓ şablonun en sayfaları",
)


def run(*argv: str) -> subprocess.CompletedProcess:
    """Depo kökünde alt süreç; backend sqlite ve çıktı UTF-8 (test_smoke_run7 ile aynı iki sabitleme)."""
    return subprocess.run(
        [sys.executable, *argv],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "NL2SQL_BACKEND": "sqlite", "PYTHONIOENCODING": "utf-8"},
    )


def free_port() -> str:
    """Boşta bir port: numara işletim sistemine sorulur ve hemen bırakılır, sunucuyu açan betik alır."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return str(sock.getsockname()[1])


@pytest.fixture(scope="module")
def smoke():
    """İngilizce altın kümesinin üstünde tek duman koşusu; çıktısını test okur."""
    for argv in (
        ("-m", "nl2sql", "build-db", "--dataset", "wwi"),
        ("-m", "nl2sql", "build-index", "--embed", "fake", "--dataset", "wwi"),
    ):
        result = run(*argv)
        assert result.returncode == 0, f"{' '.join(argv)}: {result.stdout}{result.stderr}"
    return run("scripts/smoke_serve.py", "--port", free_port(), "--lang", "en")


def test_the_english_smoke_walks_the_api_in_english(smoke):
    assert smoke.returncode == 0, smoke.stdout + smoke.stderr
    for line in CHECKS:
        assert line in smoke.stdout, f"{line} basılmadı"


def test_the_english_question_is_answered_in_english(smoke):
    """Cevabın dili satırda okunur: İngilizce sorulan E01'in cevabı İngilizcedir (R8-6)."""
    line = next(line for line in smoke.stdout.splitlines() if line.startswith("✓ soru cevaplandı"))
    assert " en · " in line, f"cevabın dili satırda yok: {line}"
