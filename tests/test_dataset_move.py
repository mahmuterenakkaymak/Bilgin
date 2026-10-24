"""T122: sentetik veri kümesi taşındı (PLAN R4-2) — yalnızca yollar değişti, baytlar aynı kaldı.

Beş veri dosyası ``datasets/synthetic_erp/`` altına geçti. sha256 değerleri taşımadan önce
``git show HEAD:<eski yol>`` çıktısından hesaplanıp burada sabitlendi: taşımaların commit'iyle
birlikte HEAD o yolları taşımıyor, dolayısıyla test eski hâli git'ten soramaz. Python yerinde
kaldı (``eval/reference*.py``, ``nl2sql/schema_map/*``); dataset.json onları ``modül:attr`` ile gösterir.
"""

import hashlib
import importlib
import json

from nl2sql import config
from nl2sql.agent import fake

DATASET = "synthetic_erp"
DATASET_DIR = f"datasets/{DATASET}"

# eski yol -> (yeni yol, taşınmadan önceki sha256'ı)
MOVED = {
    "schema/schema.json": (
        f"{DATASET_DIR}/schema.json",
        "bab34a253d0b1471bbeea9f1fcac39825a6dfaf1619706cf0b60e02933c7e62b",
    ),
    "schema/rules.json": (
        f"{DATASET_DIR}/rules.json",
        "2a3a7574834a8ec2aadf9aacb87f9812468cce37cc0dfc0dd27a3ebcaef8f87f",
    ),
    "profiles/netsis.json": (
        f"{DATASET_DIR}/profile.json",
        "0de07e0be6f5584bdf214c04e67884d575877523f83a6dbeb7f452c22b732e5e",
    ),
    "eval/golden.jsonl": (
        f"{DATASET_DIR}/golden.jsonl",
        "9b31cd5a1b466d20b3c3e92e4eee534f689e69e9baaf2ec56651efbb95463d28",
    ),
    "eval/traps.jsonl": (
        f"{DATASET_DIR}/traps.jsonl",
        "ac361e00d257430c29c450ceaaad0b64094ab855ef0efd0b9ca2c6d33b743fcb",
    ),
}

CONFIG_PATHS = {
    "schema": config.SCHEMA_PATH,
    "rules": config.RULES_PATH,
    "profile": config.PROFILE_PATH,
    "golden": config.GOLDEN_PATH,
    "traps": config.TRAPS_PATH,
}

CONTRACT_KEYS = {
    "name",
    "display_name",
    "dialect",
    "connection",
    "default_schema",
    "as_of",
    "seed",
    "files",
    "builder",
    "generator",
    "references",
    "fake_fallback_sql",
    "outputs",
}


def dataset_doc() -> dict:
    path = config.ROOT / DATASET_DIR / "dataset.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_old_paths_are_gone():
    for old in MOVED:
        assert not (config.ROOT / old).exists(), old


def test_moved_files_hold_their_old_bytes():
    for old, (new, digest) in MOVED.items():
        assert (config.ROOT / new).is_file(), new
        assert hashlib.sha256((config.ROOT / new).read_bytes()).hexdigest() == digest, old


def test_python_modules_stayed_where_they_were():
    for path in (
        "eval/reference.py",
        "eval/reference_run2.py",
        "nl2sql/schema_map/generator.py",
        "nl2sql/schema_map/build.py",
    ):
        assert (config.ROOT / path).is_file(), path


def test_config_paths_point_inside_the_dataset():
    assert len(set(CONFIG_PATHS.values())) == 5
    for name, path in CONFIG_PATHS.items():
        assert path.is_absolute(), name
        relative = path.relative_to(config.ROOT).as_posix()
        assert relative.startswith(f"{DATASET_DIR}/"), relative
        assert path.is_file(), relative


def test_dataset_json_has_every_contract_key():
    doc = dataset_doc()
    assert set(doc) == CONTRACT_KEYS
    assert doc["name"] == DATASET == config.DEFAULT_DATASET
    assert doc["display_name"] == "Sentetik ERP (Netsis benzeri)"
    assert doc["connection"] == "sqlite"
    assert doc["default_schema"] == "dbo"
    assert doc["as_of"] == config.AS_OF
    assert doc["seed"] == config.SEED
    assert doc["fake_fallback_sql"] == fake.FALLBACK_SQL


def test_dataset_json_files_are_the_moved_files():
    files = dataset_doc()["files"]
    assert set(files) == set(CONFIG_PATHS)
    for name, filename in files.items():
        assert CONFIG_PATHS[name] == config.ROOT / DATASET_DIR / filename, name


def test_dataset_json_outputs_are_todays_paths():
    outputs = dataset_doc()["outputs"]
    assert set(outputs) == {"db", "mssql_script", "index_dir", "eval_out"}
    for name, path in (
        ("db", config.DB_PATH),
        ("mssql_script", config.MSSQL_SCRIPT),
        ("index_dir", config.INDEX_DIR),
        ("eval_out", config.EVAL_OUT),
    ):
        assert outputs[name] == path.relative_to(config.ROOT).as_posix(), name


def test_dataset_json_code_references_resolve():
    doc = dataset_doc()
    for name in ("builder", "generator", "references"):
        module_name, _, attribute = doc[name].partition(":")
        assert getattr(importlib.import_module(module_name), attribute), name
