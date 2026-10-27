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

# ---------------------------------------------------------------- Run 6: auth, sessions, login limit
PASSWORD_MIN_LEN = 10  # shorter passwords are refused
SCRYPT_N = 2**14  # scrypt cost factors; the hash stores them, so a later change stays verifiable
SCRYPT_R = 8
SCRYPT_P = 1
SESSION_HOURS = 12  # a session expires this many hours after it was created
SESSION_COOKIE = "bilgin_oturum"
LOGIN_MAX_FAILURES = 5  # failures inside LOGIN_WINDOW_MIN minutes lock the account for LOCKOUT_MIN
LOGIN_WINDOW_MIN = 15
LOCKOUT_MIN = 15
DEV_ADMIN_ENV = "NL2SQL_DEV_ADMIN_PASSWORD"  # env var the bootstrap admin password is read from

# ---------------------------------------------------------------- Run 6: schema map onboarding
MAP_MAX_BYTES = 5 * 1024 * 1024  # an uploaded map bigger than this is refused before it is read
MAP_PREVIEW_TTL_MIN = 30  # a preview may be applied until this many minutes after it was written
TEMPLATE_FILENAME = "bilgin-veritabani-sablonu.xlsx"  # template the user fills in and uploads back
TEMPLATE_VERSION = "1"  # stamped into the template; a mismatch warns that the file is outdated
DATASET_NAME_RE = r"^[a-z][a-z0-9_]{2,30}$"  # dataset directory name: lowercase keeps Windows paths stable

# ---------------------------------------------------------------- Run 7: conversation
CONV_KEEP_ROWS = 5  # masked rows of a turn kept in summary_json for the next turn
CONV_TURNS = 3  # earlier turns the context block offers the model
CONV_TITLE_CHARS = 80  # a conversation title is the first question cut to this
FOLLOWUP_MARKERS = (
    "bu",
    "bunlar",
    "bunları",
    "bunların",
    "şu",
    "şunlar",
    "o",
    "onlar",
    "aynı",
    "sadece",
    "yalnız",
    "bunu",
    "peki",
    "ya",
    "bunlardan",
    "onun",
    "bunun",
)  # deterministic hints: the question probably continues the previous turn

# ---------------------------------------------------------------- Run 7: start screen
BUSINESS_ROLES = {
    "satis": "Satış",
    "satin_alma": "Satın alma",
    "muhasebe": "Muhasebe",
    "yonetim": "Yönetim",
    "genel": "Genel",
}  # order = the order roles are listed in on the start screen and in the users screen
DEFAULT_BUSINESS_ROLE = "genel"
PERSONAL_CARDS = 6  # cards one user may pin for themselves
START_CACHE_S = 300  # a card's result is rerun at most once per dataset+card this often
CARD_REFRESH_MIN_S = 30  # "Yenile" on one card is rate-limited to this
CARD_TABLE_ROWS = 10  # rows of a table card the start screen shows
SUGGEST_PER_ROLE = (2, 4)  # ready questions suggested per business role: at least, at most

# ---------------------------------------------------------------- Run 7: database connections
DB_CHECK_S = 60  # the background checker asks "is the database up?" this often
DB_CHECK_TIMEOUT_S = 3  # seconds the SELECT 1 is given
CONN_ENV_PREFIX = "NL2SQL_MSSQL_CONN_"  # NL2SQL_MSSQL_CONN_<DATASET> overrides a stored connection
CONN_TABLE_SAMPLE = 10  # tables of the map the read-only guard samples against the live database

# ---------------------------------------------------------------- Run 8: language
LANGUAGES = ("tr", "en")
DEFAULT_LANG = "tr"
FOLLOWUP_MARKERS_EN = (
    "this",
    "these",
    "those",
    "it",
    "them",
    "that",
    "same",
    "only",
    "just",
    "their",
    "its",
)  # English twins of FOLLOWUP_MARKERS
DETECT_EN_WORDS = (
    "the",
    "what",
    "when",
    "where",
    "which",
    "who",
    "how",
    "many",
    "much",
    "is",
    "are",
    "was",
    "were",
    "of",
    "for",
    "and",
    "with",
    "from",
    "show",
    "list",
    "tell",
    "give",
    "me",
    "their",
    "total",
    "by",
    "per",
    "top",
    "in",
    "on",
    "each",
    "all",
    "any",
    "last",
    "this",
    "number",
    "sum",
    "average",
    "between",
    "than",
    "most",
    "least",
    "highest",
    "lowest",
    "products",
    "customers",
    "orders",
    "sales",
    "revenue",
    "city",
)  # English stopwords of detect_lang (R8-6)
DETECT_TR_WORDS = (
    "nedir",
    "kaç",
    "hangi",
    "kim",
    "kimin",
    "ne",
    "neden",
    "nasıl",
    "toplam",
    "ortalama",
    "en",
    "için",
    "ile",
    "ve",
    "veya",
    "göster",
    "listele",
    "ver",
    "bana",
    "geçen",
    "bu",
    "şu",
    "önce",
    "sonra",
    "daha",
)  # Turkish stopwords of detect_lang (R8-6)
TEMPLATE_FILENAMES = {
    "tr": TEMPLATE_FILENAME,
    "en": "bilgin-database-template.xlsx",
}  # download name of the fill-in template, per language

# ---------------------------------------------------------------- Run 8: Windows service
SERVICE_NAME = "Bilgin"
SERVICE_PORT = 8777
SERVICE_HOME = r"C:\ProgramData\Bilgin"  # default NL2SQL_HOME of an installed service

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
# ASSUMPTION: Run 6 paths sit here for the same reason — they need ROOT.
MAP_PREVIEWS_DIR = ROOT / "data" / "map_previews"
MAP_CHANGES_LOG = ROOT / "logs" / "map_changes.jsonl"
REAL_DATASETS_DIR = ROOT / "real_datasets"

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


def lang() -> str:
    """Program language: NL2SQL_LANG when it names one of LANGUAGES, else DEFAULT_LANG."""
    value = _env("NL2SQL_LANG", DEFAULT_LANG)
    return value if value in LANGUAGES else DEFAULT_LANG


def mapping_path(name: str) -> Path:
    """Column mapping of one imported source: schema/mapping.<name>.json."""
    return SCHEMA_DIR / f"mapping.{name}.json"


def datasets_dir() -> Path:
    """Dataset directory: NL2SQL_DATASETS_DIR when set, else DATASETS_DIR."""
    return Path(_env("NL2SQL_DATASETS_DIR", str(DATASETS_DIR)))


def app_db_path() -> Path:
    """App database: NL2SQL_APP_DB when set, else APP_DB_PATH."""
    return Path(_env("NL2SQL_APP_DB", str(APP_DB_PATH)))


def real_datasets_dir() -> Path:
    """Real dataset root: NL2SQL_REAL_DATASETS_DIR when set, else REAL_DATASETS_DIR."""
    return Path(_env("NL2SQL_REAL_DATASETS_DIR", str(REAL_DATASETS_DIR)))
