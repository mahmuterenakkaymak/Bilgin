# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Depo kökü: ``index/`` kalıbı yalnızca kökteki çalışma zamanı indeksini eler.

``index/`` satırı yolu sınırlamadığı için ``nl2sql/index/`` paketini de eliyordu; yedi dosya
zorla eklendiği için izleniyor görünüyordu ve ``git check-ignore`` izlenen yolları sorgulamadığın-
dan test_repo_tracked bunu yakalayamıyordu. ``--no-index`` elenme kurallarını izlenmiş olsun
olmasın her yolda sınar, bu yüzden paketin mevcut bir modülüyle yeni bir modül adı birlikte
deneniyor: kalıp ``/index/`` iken hiçbir ``nl2sql/index`` yolu eşleşmemeli, kök eşleşmeye devam etmeli.
"""

import subprocess

from nl2sql import config

RUNTIME_DOC = "index/docs.json"
PACKAGE_MODULE = "nl2sql/index/search.py"
PACKAGE_NEW_MODULE = "nl2sql/index/new_module.py"


def check_ignore(path: str) -> int:
    """Yol depo köküne göre elenme kuralına mı takılıyor; 0 = eleniyor, 1 = elenmiyor."""
    return subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
    ).returncode


def test_index_package_paths_are_not_ignored():
    assert check_ignore(PACKAGE_MODULE) != 0
    assert check_ignore(PACKAGE_NEW_MODULE) != 0


def test_root_runtime_index_is_still_ignored():
    assert check_ignore(RUNTIME_DOC) == 0
