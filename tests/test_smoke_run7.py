# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Run 7'nin konuşma dumanı: ``--conversation`` gerçek bir sunucuda zinciri gerçekten koşuyor mu?

Test sunucu açmaz; ``scripts/smoke_serve.py --conversation``ı alt süreç olarak koşar, yani ölçtüğü şey
betiğin kendi çıkış kodu ve bastığı ✓ satırlarıdır. Öncesinde ``test_smoke_run5`` ile aynı iki hazırlık
(``build-db`` + ``build-index --embed fake``): sunucu o dünyayı okur. Satırların adı iddiaların adıdır --
kimliği cevapta doğan ilk tur, birinci turu sayan bağlam, modeli hiç koşurmayan sunum değişikliği ve
deposunda üç tur duran konuşma. Port boşta bir numaradır (``socket``e 0 sorulur), böylece aynı anda koşan
iki duman birbirinin portunu çalmaz. Model ``fake``, dolayısıyla ağ istenmiyor.
"""

import os
import socket
import subprocess
import sys

import pytest

from nl2sql import config

CHECKS = (
    "✓ konuşmanın ilk turu",
    "✓ bağlamlı ikinci tur",
    "✓ modelsiz sunum değişikliği",
    "✓ konuşmanın üç turu",
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
    return run("scripts/smoke_serve.py", "--port", free_port(), "--conversation")


def test_the_conversation_smoke_walks_a_chain_on_a_live_server(smoke):
    assert smoke.returncode == 0, smoke.stdout + smoke.stderr
    for line in CHECKS:
        assert line in smoke.stdout, f"{line} basılmadı"
