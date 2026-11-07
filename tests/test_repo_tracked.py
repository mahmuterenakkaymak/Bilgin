# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Depo kaydı: ``nl2sql/index`` izlenir, kökteki çalışma zamanı indeks klasörü izlenmez.

İndeks paketinin yedi dosyası .gitignore'daki ``index/`` satırına takılıyordu; o satır çalışma
zamanı indeksinin (depo kökündeki ``index/``) yazdığı dosyalar için yazılmıştı, ama kalıp yolu
sınırlamadığı için ``nl2sql/index/`` de eleniyordu ve temiz bir kurulum ``ModuleNotFoundError:
nl2sql.index`` ile düşüyordu. Test iki tarafı birlikte tutuyor: paketin modülleri izlenmeli,
çalışma zamanı klasörü yine izlenmemeli.
"""

import subprocess

from nl2sql import config

INDEX_PACKAGE = "nl2sql/index"
RUNTIME_DOC = "index/docs.json"
PACKAGE_FILES = {"__init__.py", "text.py", "embed.py", "docs.py", "bm25.py", "store.py", "search.py"}


def git(*argv: str) -> subprocess.CompletedProcess:
    """Depo kökünde git; iddia dönüş kodunda ve listelenen yollarda olduğu için çıktı yakalanır."""
    return subprocess.run(
        ["git", *argv], cwd=config.ROOT, capture_output=True, encoding="utf-8"
    )


def test_the_index_package_is_not_ignored():
    assert git("check-ignore", "-q", f"{INDEX_PACKAGE}/search.py").returncode != 0


def test_every_index_module_is_tracked():
    tracked = {
        line.rsplit("/", 1)[-1]
        for line in git("ls-files", INDEX_PACKAGE).stdout.split()
        if line.strip()
    }
    assert not PACKAGE_FILES - tracked, f"izlenmeyen indeks modülleri: {sorted(PACKAGE_FILES - tracked)}"


def test_the_runtime_index_directory_stays_ignored():
    assert git("check-ignore", "-q", RUNTIME_DOC).returncode == 0
