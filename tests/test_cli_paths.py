"""``python -m nl2sql paths`` (PLAN R8-20, Contracts ``paths``): her yol adıyla ve çözülmuş haliyle.

Üç şey sabitlenir: ``--json``ın anahtarları sözleşmenin satırıdır (kurulum betiği ve README onları
okur), ``NL2SQL_HOME`` kurulunca yazıların hepsi oraya taşınır, ve ortamda duran sırlar - bağlantı
dizesi, API anahtarı, geliştirme yöneticisinin parolası - hiçbir çıktıda görünmez. Yollar ``config``
import edilirken çözüldüğü için testler alt süreç koşar (``test_home_paths``ın yolu): ortam gerçek,
modül taze.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from nl2sql import config

REPO = Path(config.__file__).resolve().parent.parent
TURKISH = set("çğıöşüÇĞİÖŞÜ")

# Contracts "paths": anahtarlar ve sıraları sözleşmenin satırıdır.
CONTRACT = [
    "home",
    "app_db",
    "logs",
    "ask_log",
    "audit_log",
    "map_changes",
    "map_previews",
    "eval_out",
    "index",
    "secrets",
    "datasets",
    "onboard_dir",
]
# HOME kurulunca taşınan yazılar (PLAN R8-20): depoda kalmaz, ``datasets`` kodla gelir.
UNDER_HOME = [
    "app_db",
    "logs",
    "ask_log",
    "audit_log",
    "map_changes",
    "map_previews",
    "eval_out",
    "index",
    "secrets",
]
SECRETS = ("NL2SQL_MSSQL_CONN", "NL2SQL_LLM_API_KEY", "NL2SQL_DEV_ADMIN_PASSWORD")


def run(*args, **env) -> subprocess.CompletedProcess:
    """``python -m nl2sql paths``ı alt süreçte koşar; ``NL2SQL_*`` ortamı temiz, verilenler kurulu."""
    child = {k: v for k, v in os.environ.items() if not k.startswith("NL2SQL_")}
    child.update({key: str(value) for key, value in env.items()})
    done = subprocess.run(
        [sys.executable, "-m", "nl2sql", "paths", *[str(a) for a in args]],
        cwd=str(REPO),
        env=child,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert done.returncode == 0, done.stderr
    return done


def test_json_keys_are_exactly_the_contract():
    data = json.loads(run("--json").stdout)

    assert list(data) == CONTRACT
    for key in CONTRACT:
        if key == "datasets":
            assert data[key]
            for path in data[key]:
                assert (Path(path) / "dataset.json").is_file()
        else:
            assert Path(data[key]).is_absolute(), key


def test_text_output_prints_one_line_per_path():
    data = json.loads(run("--json").stdout)
    lines = run().stdout.splitlines()

    for key in CONTRACT:
        if key == "datasets":
            continue
        assert any(line.endswith(f": {data[key]}") for line in lines), key
    for path in data["datasets"]:
        assert f"  {path}" in lines


def test_home_env_moves_every_written_path(tmp_path):
    data = json.loads(run("--json", NL2SQL_HOME=tmp_path).stdout)

    assert Path(data["home"]) == tmp_path
    for key in UNDER_HOME:
        assert Path(data[key]).is_relative_to(tmp_path), key
    assert Path(data["onboard_dir"]) == tmp_path / "datasets"


@pytest.mark.parametrize("flag", [[], ["--json"]])
def test_no_secret_value_appears_in_either_output(flag):
    secrets = {name: f"gizli-{uuid.uuid4().hex}" for name in SECRETS}

    done = run(*flag, **secrets)
    for value in secrets.values():
        assert value not in done.stdout
        assert value not in done.stderr


def test_labels_follow_lang():
    assert run().stdout != run("--lang", "en").stdout
    assert not set(run("--lang", "en").stdout) & TURKISH
