import pytest

from nl2sql import config

ENV_VARS = [
    "NL2SQL_EMBED_BASE_URL",
    "NL2SQL_EMBED_MODEL",
    "NL2SQL_EMBED_API_KEY",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def test_run1_tunables_unchanged():
    assert config.AS_OF == "2026-09-30"
    assert config.SEED == 42
    assert config.TOP_N == 1000
    assert config.MODEL_MAX_ROWS == 50
    assert config.COMPARE_MAX_ROWS == 100000
    assert config.QUERY_TIMEOUT_S == 10.0
    assert config.MAX_TOOL_CALLS == 8
    assert config.MAX_FAILED_RUNS == 3
    assert config.AGENT_TIMEOUT_S == 180.0
    assert config.LLM_CALL_TIMEOUT_S == 120.0
    assert config.ENABLE_THINKING is True


def test_modes_and_per_mode_tool_budget():
    assert config.MODES == ("full", "full_rules", "rag")
    assert config.DEFAULT_EVAL_MODE == "full"
    assert config.DEFAULT_EVAL_MODE in config.MODES
    assert config.MAX_TOOL_CALLS_BY_MODE == {"full": 8, "full_rules": 8, "rag": 12}
    assert set(config.MAX_TOOL_CALLS_BY_MODE) == set(config.MODES)
    assert config.MAX_TOOL_CALLS_BY_MODE[config.DEFAULT_EVAL_MODE] == config.MAX_TOOL_CALLS


def test_retrieval_tunables_match_plan():
    assert config.SEARCH_K == 5
    assert config.RULES_K == 3
    assert config.RRF_K == 60
    assert config.BM25_K1 == 1.5
    assert config.BM25_B == 0.75
    assert config.FAKE_EMBED_DIM == 256
    assert config.EMBED_BATCH == 32
    assert config.EMBED_TIMEOUT_S == 60.0
    assert config.SAMPLE_VALUES_N == 20
    assert config.LOW_CONFIDENCE == 0.7
    assert config.CHARS_PER_TOKEN == 4
    assert config.TOOL_RESULT_MAX_CHARS == 4000


def test_retrieval_values_are_sane():
    assert config.RULES_K < config.SEARCH_K
    assert config.RRF_K > 0
    assert config.BM25_K1 > 0
    assert 0 < config.BM25_B <= 1
    assert 0 < config.LOW_CONFIDENCE < 1
    assert config.EMBED_BATCH > 0
    assert config.FAKE_EMBED_DIM > 0
    assert config.SAMPLE_VALUES_N > 0
    assert config.CHARS_PER_TOKEN > 0
    assert config.TOOL_RESULT_MAX_CHARS > 0
    assert isinstance(config.EMBED_TIMEOUT_S, float) and config.EMBED_TIMEOUT_S > 0


def test_run2_paths_absolute_and_named():
    expected = {
        "RULES_PATH": "datasets/synthetic_erp/rules.json",
        "PROFILE_PATH": "datasets/synthetic_erp/profile.json",
        "INDEX_DIR": "index",
    }
    for name, relative in expected.items():
        path = getattr(config, name)
        assert path.is_absolute(), name
        assert path.relative_to(config.ROOT).as_posix() == relative, name


def test_run2_paths_do_not_collide_with_run1():
    run1 = {config.DB_PATH, config.SCHEMA_PATH, config.EVAL_OUT, config.AUDIT_LOG}
    assert not run1 & {config.RULES_PATH, config.PROFILE_PATH, config.INDEX_DIR}


def test_index_dir_is_build_output_and_ignored():
    lines = (config.ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert "/index/" in lines
    assert "index/" not in lines


def test_embed_settings_defaults():
    settings = config.embed_settings()
    assert settings.base_url == "http://127.0.0.1:8891/v1"
    assert settings.model == "embeddinggemma"
    assert settings.api_key == "local"


def test_embed_settings_env_override(monkeypatch):
    monkeypatch.setenv("NL2SQL_EMBED_BASE_URL", "http://127.0.0.1:8888/v1")
    monkeypatch.setenv("NL2SQL_EMBED_MODEL", "qwen3-embedding-4b")
    monkeypatch.setenv("NL2SQL_EMBED_API_KEY", "secret-from-env")
    settings = config.embed_settings()
    assert (settings.base_url, settings.model, settings.api_key) == (
        "http://127.0.0.1:8888/v1",
        "qwen3-embedding-4b",
        "secret-from-env",
    )


def test_embed_settings_read_at_call_time(monkeypatch):
    assert config.embed_settings().model == config.DEFAULT_EMBED_MODEL
    monkeypatch.setenv("NL2SQL_EMBED_MODEL", "changed")
    assert config.embed_settings().model == "changed"
    monkeypatch.delenv("NL2SQL_EMBED_MODEL")
    assert config.embed_settings().model == config.DEFAULT_EMBED_MODEL


@pytest.mark.parametrize(
    "name,field,default",
    [
        ("NL2SQL_EMBED_BASE_URL", "base_url", config.DEFAULT_EMBED_BASE_URL),
        ("NL2SQL_EMBED_MODEL", "model", config.DEFAULT_EMBED_MODEL),
        ("NL2SQL_EMBED_API_KEY", "api_key", config.DEFAULT_EMBED_API_KEY),
    ],
)
def test_blank_embed_env_falls_back_to_default(monkeypatch, name, field, default):
    monkeypatch.setenv(name, "   ")
    assert getattr(config.embed_settings(), field) == default


def test_embed_settings_independent_of_llm_settings(monkeypatch):
    monkeypatch.setenv("NL2SQL_LLM_BASE_URL", "http://127.0.0.1:8080/v1")
    monkeypatch.setenv("NL2SQL_LLM_MODEL", "strata")
    monkeypatch.setenv("NL2SQL_LLM_API_KEY", "llm-key")
    embed = config.embed_settings()
    llm = config.llm_settings()
    assert embed.base_url == config.DEFAULT_EMBED_BASE_URL
    assert embed.model == config.DEFAULT_EMBED_MODEL
    assert embed.api_key == config.DEFAULT_EMBED_API_KEY
    assert (llm.base_url, llm.model, llm.api_key) == (
        "http://127.0.0.1:8080/v1",
        "strata",
        "llm-key",
    )
