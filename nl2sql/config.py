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

# ---------------------------------------------------------------- Run 3: import + auto mode
EXCEL_PREVIEW_ROWS = 20  # rows of a sheet shown in the import preview
AUTO_FULL_MAX_TOKENS = 12000  # prompt budget above which auto mode falls back to rag
SAMPLE_HINT_N = 5  # sample values shown inline in the schema doc
SAMPLE_HINT_MAX_LEN = 100  # longer values are left out of the inline hint

# ---------------------------------------------------------------- Run 3: retrieval
NEIGHBOUR_EXPANSION = True  # join neighbours of a hit table join the context
NEIGHBOUR_MAX = 3  # neighbours added per hit table
SYNONYM_REWRITE = True  # expand the query with profile synonyms before BM25

# ---------------------------------------------------------------- Run 3: PII
PII_FILTER = frozenset(
    {"tckn", "vkn", "iban", "phone", "email", "address", "salary", "person_name"}
)

# ---------------------------------------------------------------- Run 4: datasets, models, context
DEFAULT_DATASET = "synthetic_erp"  # dataset used when the command names none
AUTO_FULL_SHARE = 0.5  # share of the prompt budget the full schema may take in auto mode
TRIM_TOOL_CHARS = 400  # tool answers longer than this are trimmed before the model sees them
MESSAGE_OVERHEAD_TOKENS = 4  # per-message overhead added to the prompt token estimate
PING_TIMEOUT_S = 5.0  # reachability probe timeout of a model endpoint
COMPARE_MODEL_MODES = ("full_rules", "rag")  # modes `compare-models` runs for every model

# ---------------------------------------------------------------- Run 5: web UI, ask log, reports
UI_MAX_ROWS = 200  # rows of the final answer the UI may show
EXPORT_MAX_ROWS = 100000  # rows an export re-runs the ask's SQL for
HISTORY_N = 50  # ask log lines /api/history returns (newest first)
EXAMPLES_N = 4  # example questions offered on the empty screen
SERVE_HOST = "127.0.0.1"  # `serve` binds loopback only: single user, no auth
SERVE_PORT = 8777
FANOUT_FACTOR = 3.0  # joined/driving row ratio above which the fan-out check warns
CHART_BAR_MAX_ROWS = 20  # rows a bar chart is still readable with
CHART_PIE_MAX_PARTS = 6
NARRATE_MAX_ROWS = 20  # masked rows the narrator is shown
NUMBER_TOLERANCE_UNITS = 0.5  # half a unit of the last shown decimal in the number guard
CLARIFY_MAX_OPTIONS = 4  # upper bound of the mutually exclusive options
TABLE_SUMMARIES = True  # R5-20: measured on both datasets, hybrid recall@5 gained (eval/SUMMARIES.md)
SUMMARY_KEY_COLUMNS = 8  # key columns one table summary lists

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
SCHEMA_PATH = ROOT / "datasets" / "synthetic_erp" / "schema.json"
GOLDEN_PATH = ROOT / "datasets" / "synthetic_erp" / "golden.jsonl"
TRAPS_PATH = ROOT / "datasets" / "synthetic_erp" / "traps.jsonl"
EVAL_OUT = ROOT / "eval_out"
AUDIT_LOG = ROOT / "logs" / "audit.jsonl"
# ASSUMPTION: Run 2 paths sit here, not in the Run 2 block above, because they need ROOT.
RULES_PATH = ROOT / "datasets" / "synthetic_erp" / "rules.json"
PROFILE_PATH = ROOT / "datasets" / "synthetic_erp" / "profile.json"
EXCEL_HEADERS_PATH = ROOT / "profiles" / "excel_headers.json"
INDEX_DIR = ROOT / "index"
# ASSUMPTION: Run 3 paths sit here for the same reason — they need ROOT.
SCHEMA_DIR = ROOT / "schema"
IMPORTED_PATH = SCHEMA_DIR / "imported.json"
SKELETON_PATH = SCHEMA_DIR / "skeleton.json"
DIFF_JSON_PATH = SCHEMA_DIR / "diff.json"
DIFF_MD_PATH = SCHEMA_DIR / "diff.md"
MERGED_PATH = SCHEMA_DIR / "merged.json"
LOGIN_SCRIPT_PATH = ROOT / "db" / "mssql" / "readonly_login.sql"
# ASSUMPTION: Run 4 paths sit here for the same reason — they need ROOT.
DATASETS_DIR = ROOT / "datasets"
MODELS_PATH = ROOT / "config" / "models.json"
# ASSUMPTION: Run 5 paths sit here for the same reason — they need ROOT.
APP_DB_PATH = ROOT / "data" / "bilgin.db"
ASK_LOG = ROOT / "logs" / "asks.jsonl"
STATIC_DIR = ROOT / "nl2sql" / "web" / "static"
WEB_DIR = ROOT / "web"

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


def mapping_path(name: str) -> Path:
    """Column mapping of one imported source: schema/mapping.<name>.json."""
    return SCHEMA_DIR / f"mapping.{name}.json"


def datasets_dir() -> Path:
    """Dataset directory: NL2SQL_DATASETS_DIR when set, else DATASETS_DIR."""
    return Path(_env("NL2SQL_DATASETS_DIR", str(DATASETS_DIR)))
