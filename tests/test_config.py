# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

import pytest

from nl2sql import config

ENV_VARS = [
    "NL2SQL_LLM_BASE_URL",
    "NL2SQL_LLM_MODEL",
    "NL2SQL_LLM_API_KEY",
    "NL2SQL_BACKEND",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_timeouts_are_positive_seconds():
    for value in (config.QUERY_TIMEOUT_S, config.AGENT_TIMEOUT_S, config.LLM_CALL_TIMEOUT_S):
        assert isinstance(value, float) and value > 0
    assert config.AGENT_TIMEOUT_S > config.LLM_CALL_TIMEOUT_S > config.QUERY_TIMEOUT_S


def test_row_budgets_ordered():
    assert config.MODEL_MAX_ROWS < config.COMPARE_MAX_ROWS
    assert config.TOP_N >= config.MODEL_MAX_ROWS


def test_source_dirs_exist():
    for directory in ("data", "db/mssql", "schema", "eval"):
        assert (config.ROOT / directory).is_dir(), directory


def test_llm_settings_defaults():
    settings = config.llm_settings()
    assert settings.base_url == "http://127.0.0.1:8080/v1"
    assert settings.model
    assert settings.api_key == "local"


def test_llm_settings_env_override(monkeypatch):
    monkeypatch.setenv("NL2SQL_LLM_BASE_URL", "http://127.0.0.1:8888/v1")
    monkeypatch.setenv("NL2SQL_LLM_MODEL", "qwen3.8-27b")
    monkeypatch.setenv("NL2SQL_LLM_API_KEY", "secret-from-env")
    settings = config.llm_settings()
    assert (settings.base_url, settings.model, settings.api_key) == (
        "http://127.0.0.1:8888/v1",
        "qwen3.8-27b",
        "secret-from-env",
    )


def test_llm_settings_read_at_call_time(monkeypatch):
    assert config.llm_settings().model == config.DEFAULT_LLM_MODEL
    monkeypatch.setenv("NL2SQL_LLM_MODEL", "changed")
    assert config.llm_settings().model == "changed"
    monkeypatch.delenv("NL2SQL_LLM_MODEL")
    assert config.llm_settings().model == config.DEFAULT_LLM_MODEL


def test_blank_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("NL2SQL_LLM_BASE_URL", "   ")
    assert config.llm_settings().base_url == config.DEFAULT_LLM_BASE_URL


def test_backend_default():
    assert config.backend() == "sqlite"


@pytest.mark.parametrize("value", ["mssql", "MSSQL", " mssql "])
def test_backend_env_override(monkeypatch, value):
    monkeypatch.setenv("NL2SQL_BACKEND", value)
    assert config.backend() == "mssql"


def test_backend_unknown_rejected(monkeypatch):
    monkeypatch.setenv("NL2SQL_BACKEND", "postgres")
    with pytest.raises(ValueError, match="NL2SQL_BACKEND"):
        config.backend()
