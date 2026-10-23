"""All tunables in one place. Env vars are read at call time, never at import."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------- reference date
# "geçen ay" / "bu yıl" are always relative to this date, never to the real clock.
AS_OF = "2026-09-30"

# ---------------------------------------------------------------- determinism
SEED = 42

# ---------------------------------------------------------------- query budgets
TOP_N = 1000  # TOP injected by the policy when the SQL has none
MODEL_MAX_ROWS = 50  # rows the model may see per run_sql
COMPARE_MAX_ROWS = 100000  # rows fetched when comparing golden vs predicted
QUERY_TIMEOUT_S = 10.0

# ---------------------------------------------------------------- agent limits
MAX_TOOL_CALLS = 8
MAX_FAILED_RUNS = 3  # failed run_sql calls before the loop stops
AGENT_TIMEOUT_S = 180.0
LLM_CALL_TIMEOUT_S = 120.0
ENABLE_THINKING = True

# ---------------------------------------------------------------- paths
ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "test.db"
MSSQL_SCRIPT = ROOT / "db" / "mssql" / "build_test_db.sql"
SCHEMA_PATH = ROOT / "schema" / "schema.json"
GOLDEN_PATH = ROOT / "eval" / "golden.jsonl"
TRAPS_PATH = ROOT / "eval" / "traps.jsonl"
EVAL_OUT = ROOT / "eval_out"
AUDIT_LOG = ROOT / "logs" / "audit.jsonl"

# ---------------------------------------------------------------- env defaults
DEFAULT_LLM_BASE_URL = "http://127.0.0.1:8080/v1"
# ASSUMPTION: local servers (Strata, llama.cpp) accept any model id; override with NL2SQL_LLM_MODEL.
DEFAULT_LLM_MODEL = "strata"
DEFAULT_LLM_API_KEY = "local"
DEFAULT_BACKEND = "sqlite"
BACKENDS = ("sqlite", "mssql")


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    model: str
    api_key: str


def _env(name: str, default: str) -> str:
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else default


def llm_settings() -> LLMSettings:
    """OpenAI-compatible endpoint settings; NL2SQL_LLM_* override the defaults."""
    return LLMSettings(
        base_url=_env("NL2SQL_LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        model=_env("NL2SQL_LLM_MODEL", DEFAULT_LLM_MODEL),
        api_key=_env("NL2SQL_LLM_API_KEY", DEFAULT_LLM_API_KEY),
    )


def backend() -> str:
    """Query backend: 'sqlite' (default) or 'mssql', from NL2SQL_BACKEND."""
    name = _env("NL2SQL_BACKEND", DEFAULT_BACKEND).lower()
    if name not in BACKENDS:
        raise ValueError(f"NL2SQL_BACKEND='{name}' geçersiz; {list(BACKENDS)} olmalı.")
    return name
