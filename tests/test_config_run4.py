# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Run 4 config: dataset/model ayarları, dataset klasörü okuyucusu ve .gitignore kalıbı.

``datasets_dir()`` ``llm_settings`` gibi davranır: ``BILGIN_DATASETS_DIR`` çağrı anında
okunur, yoksa sabit ``DATASETS_DIR`` döner. ``db/mssql/build_*.sql`` üretilen betikleri
eler; ``build_test_db.sql`` satırı durduğu için o da elenmeye devam eder, ``.gitkeep`` elemez.
"""

import subprocess

import pytest

from bilgin import config

ENV_VARS = ["BILGIN_DATASETS_DIR"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def check_ignore(path: str) -> int:
    """Yol depo köküne göre elenme kuralına mı takılıyor; 0 = eleniyor, 1 = elenmiyor."""
    return subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", path],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
    ).returncode


def test_earlier_tunables_unchanged():
    assert config.AS_OF == "2026-09-30"
    assert config.SEED == 42
    assert config.TOP_N == 1000
    assert config.MODES == ("full", "full_rules", "rag")
    assert config.SEARCH_K == 5
    assert config.AUTO_FULL_MAX_TOKENS == 12000
    assert config.SYNONYM_REWRITE is True


def test_run4_tunables_match_plan():
    assert config.DEFAULT_DATASET == "synthetic_erp"
    assert config.AUTO_FULL_SHARE == 0.5
    assert config.TRIM_TOOL_CHARS == 400
    assert config.MESSAGE_OVERHEAD_TOKENS == 4
    assert config.PING_TIMEOUT_S == 5.0
    assert config.COMPARE_MODEL_MODES == ("full_rules", "rag")


def test_run4_values_are_sane():
    assert 0 < config.AUTO_FULL_SHARE <= 1
    assert config.TRIM_TOOL_CHARS > 0
    assert config.MESSAGE_OVERHEAD_TOKENS > 0
    assert isinstance(config.PING_TIMEOUT_S, float) and config.PING_TIMEOUT_S > 0
    assert config.PING_TIMEOUT_S < config.LLM_CALL_TIMEOUT_S
    assert set(config.COMPARE_MODEL_MODES) <= set(config.MODES)
    assert len(set(config.COMPARE_MODEL_MODES)) == len(config.COMPARE_MODEL_MODES)


def test_run4_paths_absolute_and_named():
    expected = {"DATASETS_DIR": "datasets", "MODELS_PATH": "config/models.json"}
    for name, relative in expected.items():
        path = getattr(config, name)
        assert path.is_absolute(), name
        assert path.relative_to(config.ROOT).as_posix() == relative, name


def test_run4_paths_do_not_collide_with_existing():
    existing = {
        config.DB_PATH,
        config.SCHEMA_DIR,
        config.INDEX_DIR,
        config.EVAL_OUT,
        config.LOGIN_SCRIPT_PATH,
    }
    assert not existing & {config.DATASETS_DIR, config.MODELS_PATH}


def test_datasets_dir_default():
    assert config.datasets_dir() == config.DATASETS_DIR
    assert config.datasets_dir().is_absolute()


def test_datasets_dir_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(tmp_path))
    assert config.datasets_dir() == tmp_path


def test_datasets_dir_read_at_call_time(monkeypatch, tmp_path):
    assert config.datasets_dir() == config.DATASETS_DIR
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(tmp_path))
    assert config.datasets_dir() == tmp_path
    monkeypatch.delenv("BILGIN_DATASETS_DIR")
    assert config.datasets_dir() == config.DATASETS_DIR


def test_blank_datasets_dir_env_falls_back(monkeypatch):
    monkeypatch.setenv("BILGIN_DATASETS_DIR", "   ")
    assert config.datasets_dir() == config.DATASETS_DIR


def test_generated_mssql_scripts_are_ignored():
    assert check_ignore("db/mssql/build_wwi.sql") == 0
    assert check_ignore("db/mssql/build_test_db.sql") == 0


def test_handwritten_mssql_files_are_not_ignored():
    assert check_ignore("db/mssql/.gitkeep") != 0
