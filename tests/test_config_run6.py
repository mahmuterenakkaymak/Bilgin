# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Run 6 config: doğrulma/oturum/limit ve şema haritası sabitleri, yeni yollar ve okuyucular.

``MAP_PREVIEWS_DIR`` ``data/`` altındadır ve elenir, ``MAP_CHANGES_LOG`` ``logs/`` ile birlikte
elenir. ``real_datasets/*`` müşteri haritalarını eler, ``!real_datasets/wwi_real/`` ile WWI
örneği depoda kalır. ``app_db_path()`` ve ``real_datasets_dir()`` ``datasets_dir()`` gibi çağrı
anında okunur, böylece testler ``data/bilgin.db``ye hiç dokunmadan geçici yollarla çalışır.
"""

import subprocess

import pytest

from nl2sql import config


def check_ignore(path: str) -> int:
    """Yol depo köküne göre elenme kuralına mı takılıyor; 0 = eleniyor, 1 = elenmiyor."""
    return subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
    ).returncode


def test_run6_tunables_match_plan():
    assert config.PASSWORD_MIN_LEN == 10
    assert config.SCRYPT_N == 2**14
    assert config.SCRYPT_R == 8
    assert config.SCRYPT_P == 1
    assert config.SESSION_HOURS == 12
    assert config.SESSION_COOKIE == "bilgin_oturum"
    assert config.LOGIN_MAX_FAILURES == 5
    assert config.LOGIN_WINDOW_MIN == 15
    assert config.LOCKOUT_MIN == 15
    assert config.DEV_ADMIN_ENV == "NL2SQL_DEV_ADMIN_PASSWORD"
    assert config.MAP_MAX_BYTES == 5 * 1024 * 1024
    assert config.MAP_PREVIEW_TTL_MIN == 30
    assert config.TEMPLATE_FILENAME == "bilgin-veritabani-sablonu.xlsx"
    assert config.TEMPLATE_VERSION == "1"
    assert config.DATASET_NAME_RE == r"^[a-z][a-z0-9_]{2,30}$"


@pytest.mark.parametrize(
    "name",
    [
        "PASSWORD_MIN_LEN",
        "SCRYPT_N",
        "SCRYPT_R",
        "SCRYPT_P",
        "SESSION_HOURS",
        "LOGIN_MAX_FAILURES",
        "LOGIN_WINDOW_MIN",
        "LOCKOUT_MIN",
        "MAP_PREVIEW_TTL_MIN",
    ],
)
def test_run6_counts_are_ints(name):
    value = getattr(config, name)
    assert isinstance(value, int) and not isinstance(value, bool), name


@pytest.mark.parametrize(
    "name",
    [
        "SESSION_COOKIE",
        "DEV_ADMIN_ENV",
        "TEMPLATE_FILENAME",
        "TEMPLATE_VERSION",
        "DATASET_NAME_RE",
    ],
)
def test_run6_names_are_strings(name):
    assert isinstance(getattr(config, name), str), name


def test_run6_paths_absolute_and_named():
    expected = {
        "MAP_PREVIEWS_DIR": "data/map_previews",
        "MAP_CHANGES_LOG": "logs/map_changes.jsonl",
        "REAL_DATASETS_DIR": "real_datasets",
    }
    for name, relative in expected.items():
        path = getattr(config, name)
        assert path.is_absolute(), name
        assert path.relative_to(config.ROOT).as_posix() == relative, name


def test_run6_paths_do_not_collide_with_existing():
    existing = {
        config.DB_PATH,
        config.APP_DB_PATH,
        config.ASK_LOG,
        config.AUDIT_LOG,
        config.DATASETS_DIR,
        config.STATIC_DIR,
    }
    assert not existing & {
        config.MAP_PREVIEWS_DIR,
        config.MAP_CHANGES_LOG,
        config.REAL_DATASETS_DIR,
    }


def test_map_previews_and_changes_log_are_ignored():
    assert check_ignore("data/map_previews/x.json") == 0
    assert check_ignore(config.MAP_CHANGES_LOG.as_posix()) == 0


def test_visual_sandbox_is_ignored():
    assert check_ignore("data/visual/bilgin.db") == 0
    assert check_ignore("data/visual/real_datasets/kume/schema.json") == 0


def test_customer_maps_are_ignored_but_the_wwi_example_is_not():
    assert check_ignore("real_datasets/yeni_kume/schema.json") == 0
    assert check_ignore("real_datasets/wwi_real/schema.json") != 0


def test_app_db_path_reader_reads_the_env_at_call_time(monkeypatch, tmp_path):
    monkeypatch.delenv("NL2SQL_APP_DB", raising=False)
    assert config.app_db_path() == config.APP_DB_PATH
    target = tmp_path / "test.db"
    monkeypatch.setenv("NL2SQL_APP_DB", str(target))
    assert config.app_db_path() == target


def test_real_datasets_dir_reader_reads_the_env_at_call_time(monkeypatch, tmp_path):
    monkeypatch.delenv("NL2SQL_REAL_DATASETS_DIR", raising=False)
    assert config.real_datasets_dir() == config.REAL_DATASETS_DIR
    target = tmp_path / "gercek"
    monkeypatch.setenv("NL2SQL_REAL_DATASETS_DIR", str(target))
    assert config.real_datasets_dir() == target
