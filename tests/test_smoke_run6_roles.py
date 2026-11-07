# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Run 6'nın rol dumanı: ``--roles`` gerçek bir sunucuda rol kapılarını gerçekten koşuyor mu?

Test sunucu açmaz; ``scripts/smoke_serve.py --roles``ı alt süreç olarak koşar, yani ölçtüğü şey
betiğin kendi çıkış kodu ve bastığı ✓ satırlarıdır. Öncesinde aynı kökte ``build-db`` ve
``build-index --embed fake`` (``test_smoke_run5`` ile aynı iki hazırlık): sunucu o dünyayı okur.
Satırların adı iddiaların adıdır — yöneticinin açtığı kullanıcı, onun girişi, kuralda 403,
yöneticinin çıktısında 404 ve kişiye özel geçmiş. Model ``fake``, dolayısıyla ağ istenmiyor.
"""

import os
import subprocess
import sys

import pytest

from bilgin import config

PORT = "8781"
CHECKS = (
    "✓ yönetici kullanıcısı",
    "✓ kullanıcı girişi",
    "✓ kural yazımı 403",
    "✓ yönetici çıktısı 404",
    "✓ geçmiş kişiye özel",
)


def run(*argv: str) -> subprocess.CompletedProcess:
    """Depo kökünde alt süreç; backend sqlite ve çıktı UTF-8 (test_smoke_run5 ile aynı iki sabitleme)."""
    return subprocess.run(
        [sys.executable, *argv],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "BILGIN_BACKEND": "sqlite", "PYTHONIOENCODING": "utf-8"},
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
    return run("scripts/smoke_serve.py", "--port", PORT, "--roles")


def test_the_roles_smoke_walks_every_role_gate(smoke):
    assert smoke.returncode == 0, smoke.stdout + smoke.stderr
    for line in CHECKS:
        assert line in smoke.stdout, f"{line} basılmadı"
