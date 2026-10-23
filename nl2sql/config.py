"""All tunables in one place. Env vars are read at call time, never at import."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------- Run 2: modes
MODES = ("full", "full_rules", "rag")
DEFAULT_EVAL_MODE = "full"
MAX_TOOL_CALLS_BY_MODE = {"full": 8, "full_rules": 8, "rag": 12}
TOOL_RESULT_MAX_CHARS = 4000  # a tool answer longer than this is cut before the model sees it

# ---------------------------------------------------------------- Run 2: retrieval
SEARCH_K = 5  # tables returned by search_schema
RULES_K = 3  # calculation rules returned per query
RRF_K = 60  # constant of the reciprocal rank fusion
BM25_K1 = 1.5
BM25_B = 0.75
FAKE_EMBED_DIM = 256  # vector width of the deterministic fake embedder
EMBED_BATCH = 32  # documents per embedding request
EMBED_TIMEOUT_S = 60.0
SAMPLE_VALUES_N = 20  # distinct sample values per column in the index text
LOW_CONFIDENCE = 0.7  # join-path score below which the answer warns the model
CHARS_PER_TOKEN = 4  # rough char->token estimate for the prompt budget

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
# ASSUMPTION: Run 2 paths sit here, not in the Run 2 block above, because they need ROOT.
RULES_PATH = ROOT / "schema" / "rules.json"
PROFILE_PATH = ROOT / "profiles" / "netsis.json"
INDEX_DIR = ROOT / "index"

# ---------------------------------------------------------------- env defaults
DEFAULT_LLM_BASE_URL = "http://127.0.0.1:8080/v1"
# ASSUMPTION: local servers (Strata, llama.cpp) accept any model id; override with NL2SQL_LLM_MODEL.
DEFAULT_LLM_MODEL = "strata"
DEFAULT_LLM_API_KEY = "local"
DEFAULT_BACKEND = "sqlite"
BACKENDS = ("sqlite", "mssql")
DEFAULT_EMBED_BASE_URL = "http://127.0.0.1:8891/v1"
DEFAULT_EMBED_MODEL = "embeddinggemma"
DEFAULT_EMBED_API_KEY = "local"


@dataclass(frozen=True)
class LLMSettings:
    base_url: str
    model: str
    api_key: str


@dataclass(frozen=True)
class EmbedSettings:
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


def embed_settings() -> EmbedSettings:
    """Embedding endpoint settings; NL2SQL_EMBED_* override the defaults."""
    return EmbedSettings(
        base_url=_env("NL2SQL_EMBED_BASE_URL", DEFAULT_EMBED_BASE_URL),
        model=_env("NL2SQL_EMBED_MODEL", DEFAULT_EMBED_MODEL),
        api_key=_env("NL2SQL_EMBED_API_KEY", DEFAULT_EMBED_API_KEY),
    )


def backend() -> str:
    """Query backend: 'sqlite' (default) or 'mssql', from NL2SQL_BACKEND."""
    name = _env("NL2SQL_BACKEND", DEFAULT_BACKEND).lower()
    if name not in BACKENDS:
        raise ValueError(f"NL2SQL_BACKEND='{name}' geçersiz; {list(BACKENDS)} olmalı.")
    return name
