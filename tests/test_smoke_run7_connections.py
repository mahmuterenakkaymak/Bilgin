"""Run 7'nin bağlantı dumanı: ``--connections`` formu gerçekten yokluyor mu, sırrı gerçekten gizliyor mu?

Test sunucu açmaz; ``scripts/smoke_serve.py --connections``ı alt süreç olarak koşar, yani ölçtüğü şey
betiğin kendi çıkış kodu ve bastığı ✓ satırlarıdır. Öncesinde ``test_smoke_run7_start`` ile aynı iki
hazırlık (``build-db`` + ``build-index --embed fake``): dumanın ilk adımları bir soruyu gerçekten
koşuyor. Sunucu yoklamayı geçici bir dosyadan okuyor (``serve --db-probe-file``), dolayısıyla ne canlı
bir SQL Server ne bir sürücü gerekir; model de ``fake``, yani ağ istenmiyor.

Satırların adı iddiaların adıdır: yazabilen girişin reddi ve ardından depoda satır kalmaması, salt
okunur girişin kaydıyla sırrın yalnız ``has_secret`` olarak konuşması, parolanın görülen hiçbir cevap
gövdesinde geçmemesi ve kullanıcının çipinin yöneticiye ayrılmış satırları okumaması. Port boşta bir
numaradır (``socket``e 0 sorulur), böylece aynı anda koşan iki duman birbirinin portunu çalmaz.
"""

import os
import socket
import subprocess
import sys

import pytest

from nl2sql import config

CHECKS = (
    "✓ yazabilen giriş 409",
    "✓ salt okunur girişin kaydı",
    "✓ parolanın hiçbir gövdede çıkmaması",
    "✓ kullanıcının veritabanı çipi",
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


def free_port() -> str:
    """Boşta bir port: numara işletim sistemine sorulur ve hemen bırakılır, sunucuyu açan betik alır."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return str(sock.getsockname()[1])


@pytest.fixture(scope="module")
def smoke():
    """Kurulu dünyanın üstünde tek duman koşusu; çıktısını test okur."""
    for argv in (
        ("-m", "nl2sql", "build-db"),
        ("-m", "nl2sql", "build-index", "--embed", "fake"),
    ):
        result = run(*argv)
        assert result.returncode == 0, f"{' '.join(argv)}: {result.stdout}{result.stderr}"
    return run("scripts/smoke_serve.py", "--port", free_port(), "--connections")


def test_the_connections_smoke_walks_the_form_on_a_live_server(smoke):
    assert smoke.returncode == 0, smoke.stdout + smoke.stderr
    for line in CHECKS:
        assert line in smoke.stdout, f"{line} basılmadı"
