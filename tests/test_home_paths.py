"""``NL2SQL_HOME`` (PLAN R8-20): kurulmayınca her yol Run 7 ile aynı, kurulunca yazıların kökü HOME.

Yollar ``config`` import edilirken çözüldüğü için testler alt süreç koşar: ortam gerçek, modül
taze. Alt süreç ``nl2sql``i depodan görsün diye ``cwd`` depo kökü, ortamda ``NL2SQL_*`` yok.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from nl2sql import config

REPO = Path(config.__file__).resolve().parent.parent
NAME = "home_kumesi"

# Kurulmadığında beklenen yollar config'in bugünkü sabitlerinden değil Run 7'nin dizgilerinden.
WRITTEN = {
    "APP_DB_PATH": "data/bilgin.db",
    "ASK_LOG": "logs/asks.jsonl",
    "AUDIT_LOG": "logs/audit.jsonl",
    "MAP_PREVIEWS_DIR": "data/map_previews",
    "MAP_CHANGES_LOG": "logs/map_changes.jsonl",
    "EVAL_OUT": "eval_out",
    "INDEX_DIR": "index",
    "SECRETS_DIR": "secrets",
    "LOGS_DIR": "logs",
}
# Kodla birlikte depoda duranlar: HOME kurulsa da taşınmazlar (PLAN R8-20).
REPO_ONLY = {
    "DB_PATH": "data/test.db",
    "SCHEMA_PATH": "datasets/synthetic_erp/schema.json",
    "DATASETS_DIR": "datasets",
    "REAL_DATASETS_DIR": "real_datasets",
}

PREVIEW = {
    "dataset": {"name": NAME, "display_name": NAME, "connection": "mssql", "as_of": "2026-10-01"},
    "schema": {
        "tables": [
            {
                "name": "dbo.Urun",
                "description": "Urun tablosu",
                "columns": [{"name": "KOD", "type": "int", "description": "Kod"}],
            }
        ]
    },
    "rules": [],
    "counts": {"tables": 1},
}

HEADER = (
    f"WRITTEN = {WRITTEN!r}\n"
    f"REPO_ONLY = {REPO_ONLY!r}\n"
    f"NAME = {NAME!r}\n"
    f"PREVIEW = {PREVIEW!r}\n"
)

PROBE = """
import json, os
from nl2sql import config, datasets

out = {
    "home": str(config.HOME),
    "paths": {n: str(getattr(config, n)) for n in WRITTEN},
    "repo_paths": {n: str(getattr(config, n)) for n in REPO_ONLY},
    "app_db": str(config.app_db_path()),
    "onboard_dir": str(config.onboard_dir()),
}
if os.environ.get("BILGIN_PROBE_APPLY"):
    from nl2sql.schema_map import onboard

    out["applied"] = str(onboard.apply_preview(PREVIEW, "eren"))
    out["listed"] = sorted((i["name"], i["root"]) for i in datasets.all_datasets())
    ds = datasets.load_dataset(NAME)
    out["ds"] = {
        "index_dir": str(ds.index_dir),
        "eval_out": str(ds.eval_out),
        "db_path": str(ds.db_path),
        "mssql_script": str(ds.mssql_script),
    }
print(json.dumps(out))
"""


def probe(home=None, apply=False, **env):
    """Alt süreçte taze bir ``config`` okur; ``home`` verilmezse ``NL2SQL_HOME`` kurulu değildir."""
    child_env = {k: v for k, v in os.environ.items() if not k.startswith("NL2SQL_")}
    if home is not None:
        child_env["NL2SQL_HOME"] = str(home)
    child_env.update({key: str(value) for key, value in env.items()})
    if apply:
        child_env["BILGIN_PROBE_APPLY"] = "1"
    run = subprocess.run(
        [sys.executable, "-c", HEADER + PROBE],
        cwd=str(REPO),
        env=child_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def as_paths(values, base):
    return {name: base / relative for name, relative in values.items()}


def test_unset_home_keeps_every_path_of_run7():
    out = probe()

    assert Path(out["home"]) == REPO
    assert {k: Path(v) for k, v in out["paths"].items()} == as_paths(WRITTEN, REPO)
    assert {k: Path(v) for k, v in out["repo_paths"].items()} == as_paths(REPO_ONLY, REPO)
    assert Path(out["onboard_dir"]) == REPO / "real_datasets"


def test_home_is_the_root_of_every_written_path(tmp_path):
    out = probe(home=tmp_path)

    assert Path(out["home"]) == tmp_path
    assert {k: Path(v) for k, v in out["paths"].items()} == as_paths(WRITTEN, tmp_path)
    assert {k: Path(v) for k, v in out["repo_paths"].items()} == as_paths(REPO_ONLY, REPO)
    assert Path(out["onboard_dir"]) == tmp_path / "datasets"


def test_app_db_env_still_wins_over_home(tmp_path):
    target = tmp_path / "ozel.db"

    assert Path(probe(home=tmp_path, NL2SQL_APP_DB=target)["app_db"]) == target
    assert Path(probe(NL2SQL_APP_DB=target)["app_db"]) == target


def test_real_datasets_env_still_wins_over_home(tmp_path):
    target = tmp_path / "kume_kokleri"

    out = probe(home=tmp_path, NL2SQL_REAL_DATASETS_DIR=target)
    assert Path(out["onboard_dir"]) == target


def test_an_onboarded_dataset_lands_under_home_and_is_listed(tmp_path):
    out = probe(home=tmp_path, apply=True)

    # HOME/datasets daha önce yoktu: apply onu kendisi kurmak zorundaydı.
    assert Path(out["applied"]) == tmp_path / "datasets" / NAME
    assert (NAME, "home_datasets") in [tuple(row) for row in out["listed"]]
    # İndeks ve ölçüm HOME'a, veritabanı ile T-SQL betiği depoya gider (PLAN R8-20).
    assert Path(out["ds"]["index_dir"]) == tmp_path / "index" / NAME
    assert Path(out["ds"]["eval_out"]) == tmp_path / "eval_out" / NAME
    assert Path(out["ds"]["db_path"]) == REPO / "data" / f"{NAME}.db"
    assert Path(out["ds"]["mssql_script"]) == REPO / "db" / "mssql" / f"build_{NAME}.sql"
