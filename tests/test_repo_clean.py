# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T120: depo kaydı — T101'in geçici dizini depoya süpürülmüştü.

d702360 (T102) ``_t101check/`` scratch dizinini de depoya aldı: HEAD'den alınmış yedekler (schema.json,
policy.py, README, testler), HEAD kopyalarını yazan kurulum betiği ve iki .xlsx ikilisi. Bir daha
sürüklenmemesi için durum test altında: ne git indeksinde ne çalışma ağacında tek dosya kalmamalı.
"""

import subprocess

from nl2sql import config

SCRATCH = "_t101check"


def git(*argv: str) -> subprocess.CompletedProcess:
    """Depo kökünde git; iddia listelenen yollarda olduğu için çıktı yakalanır."""
    return subprocess.run(
        ["git", *argv], cwd=config.ROOT, capture_output=True, encoding="utf-8"
    )


def test_the_scratch_directory_is_not_tracked():
    assert git("ls-files", "--", SCRATCH).stdout.split() == []


def test_the_scratch_directory_is_absent_from_the_working_tree():
    assert not (config.ROOT / SCRATCH).exists()
