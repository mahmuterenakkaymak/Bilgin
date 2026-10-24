"""Run 5 config: arayüz/rapor sabitleri ve yeni yollar.

``APP_DB_PATH`` ``data/*.db`` kalıbına takılır (üretilen dosya, depoya girmez), ``ASK_LOG``
``logs/`` altındadır ve satır taşımaz; ``STATIC_DIR`` Vite'ın derleme çıktısıdır.
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


def test_earlier_tunables_unchanged():
    assert config.AS_OF == "2026-09-30"
    assert config.SEED == 42
    assert config.TOP_N == 1000
    assert config.MODEL_MAX_ROWS == 50
    assert config.COMPARE_MAX_ROWS == 100000
    assert config.MODES == ("full", "full_rules", "rag")
    assert config.DEFAULT_DATASET == "synthetic_erp"
    assert config.COMPARE_MODEL_MODES == ("full_rules", "rag")


def test_run5_tunables_match_plan():
    assert config.UI_MAX_ROWS == 200
    assert config.EXPORT_MAX_ROWS == 100000
    assert config.HISTORY_N == 50
    assert config.EXAMPLES_N == 4
    assert config.SERVE_HOST == "127.0.0.1"
    assert config.SERVE_PORT == 8777
    assert config.FANOUT_FACTOR == 3.0
    assert config.CHART_BAR_MAX_ROWS == 20
    assert config.CHART_PIE_MAX_PARTS == 6
    assert config.NARRATE_MAX_ROWS == 20
    assert config.NUMBER_TOLERANCE_UNITS == 0.5
    assert config.CLARIFY_MAX_OPTIONS == 4
    # Was `is False` (the pre-measurement default). T192 set it by the R5-20 rule from measured recall
    # (eval/SUMMARIES.md); tests/test_summaries_decision.py pins the value. Updated 2026-10-24 with Eren's approval.
    assert isinstance(config.TABLE_SUMMARIES, bool)
    assert config.SUMMARY_KEY_COLUMNS == 8


@pytest.mark.parametrize(
    "name",
    [
        "UI_MAX_ROWS",
        "EXPORT_MAX_ROWS",
        "HISTORY_N",
        "EXAMPLES_N",
        "SERVE_PORT",
        "CHART_BAR_MAX_ROWS",
        "CHART_PIE_MAX_PARTS",
        "NARRATE_MAX_ROWS",
        "CLARIFY_MAX_OPTIONS",
        "SUMMARY_KEY_COLUMNS",
    ],
)
def test_run5_counts_are_ints(name):
    value = getattr(config, name)
    assert isinstance(value, int) and not isinstance(value, bool), name


@pytest.mark.parametrize("name", ["FANOUT_FACTOR", "NUMBER_TOLERANCE_UNITS"])
def test_run5_ratios_are_floats(name):
    value = getattr(config, name)
    assert isinstance(value, float), name


def test_run5_scalar_types():
    assert isinstance(config.SERVE_HOST, str)
    assert isinstance(config.TABLE_SUMMARIES, bool)


def test_run5_values_are_sane():
    assert config.MODEL_MAX_ROWS <= config.UI_MAX_ROWS < config.EXPORT_MAX_ROWS
    assert config.EXAMPLES_N >= 1
    assert config.HISTORY_N > config.EXAMPLES_N
    assert config.SERVE_PORT > 1024
    assert config.SERVE_HOST == "127.0.0.1"
    assert config.FANOUT_FACTOR > 1.0
    assert 0 < config.NUMBER_TOLERANCE_UNITS < 1
    assert 2 <= config.CLARIFY_MAX_OPTIONS
    assert 1 <= config.CHART_PIE_MAX_PARTS < config.CHART_BAR_MAX_ROWS
    assert config.NARRATE_MAX_ROWS <= config.UI_MAX_ROWS
    assert config.SUMMARY_KEY_COLUMNS > 0


def test_run5_paths_absolute_and_named():
    expected = {
        "APP_DB_PATH": "data/bilgin.db",
        "ASK_LOG": "logs/asks.jsonl",
        "STATIC_DIR": "nl2sql/web/static",
        "WEB_DIR": "web",
    }
    for name, relative in expected.items():
        path = getattr(config, name)
        assert path.is_absolute(), name
        assert path.relative_to(config.ROOT).as_posix() == relative, name


def test_run5_paths_do_not_collide_with_existing():
    existing = {
        config.DB_PATH,
        config.EVAL_OUT,
        config.AUDIT_LOG,
        config.INDEX_DIR,
        config.DATASETS_DIR,
        config.MODELS_PATH,
        config.SCHEMA_DIR,
    }
    assert not existing & {
        config.APP_DB_PATH,
        config.ASK_LOG,
        config.STATIC_DIR,
        config.WEB_DIR,
    }


def test_app_db_path_is_ignored_like_every_data_db():
    assert config.APP_DB_PATH != config.DB_PATH
    assert config.APP_DB_PATH.suffix == ".db"
    assert check_ignore(config.APP_DB_PATH.as_posix()) == 0
    assert check_ignore("data/anything.db") == 0


def test_ask_log_lives_under_logs_and_is_ignored():
    assert config.ASK_LOG.parent == config.ROOT / "logs"
    assert config.ASK_LOG.name == "asks.jsonl"
    assert config.ASK_LOG != config.AUDIT_LOG
    assert check_ignore(config.ASK_LOG.as_posix()) == 0


def test_static_dir_is_the_build_output_and_ignored():
    assert config.STATIC_DIR == config.ROOT / "nl2sql" / "web" / "static"
    assert config.STATIC_DIR != config.WEB_DIR
    assert check_ignore("nl2sql/web/static/index.html") == 0


def test_web_dir_is_the_frontend_source():
    assert (config.WEB_DIR / "package.json").is_file()
