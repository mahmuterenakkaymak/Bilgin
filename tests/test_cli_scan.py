# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T414: CLI taraması - ``nl2sql/cli/main.py``'de Türkçe kullanıcı satırı kalmadı (R8-4).

``user_literals`` yalnız model-facing bir sabiti affeder: ``sample_values`` aracının modele giden
çıktısını eşleştiren ``VALUE_COUNT`` regexi. Geri kalan her print/raise reddin cümledir ve kataloğa
taşındı. İkinci test gerçek giriş noktasını ``--lang en``le koşar: ``--help`` çıktısı Türkçe harf
taşımaz.
"""

import os
import subprocess
import sys

from nl2sql import config
from nl2sql.i18n.scan import user_literals

TURKISH = set("çğıöşüÇĞİÖŞÜ")
# VALUE_COUNT: ``sample_values`` çıktısındaki "Değerler (N)" satırını eşleştiren model-facing regex;
# ekran satırı değil, çevrilmez.
ALLOW = ("VALUE_COUNT",)


def test_main_has_no_turkish_user_literals():
    assert user_literals("nl2sql/cli/main.py", allow=ALLOW) == []


def test_en_help_output_has_no_turkish_letter():
    result = subprocess.run(
        [sys.executable, "-m", "nl2sql", "--lang", "en", "--help"],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "NL2SQL_BACKEND": "sqlite", "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert not set(result.stdout) & TURKISH, sorted(set(result.stdout) & TURKISH)
