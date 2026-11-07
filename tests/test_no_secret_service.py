# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Brief §4: hiçbir sır yerinden oynamaz - beş ortam sırrının değeri hiçbir çıktıda geçmez.

R8-21 ile R8-23'ün ortak sözü tek cümledir: bağlantı dizesi uygulama veritabanında, model anahtarı
``BILGIN_HOME``ın sır klasöründe durur; servisin XML'i, ``paths``, ``service-check`` ve kurulum
betiğinin satırları o değerlerin yalnız *adını* taşır. Test beş değişkene koşu başına rastgele
değerler koyar - sabit bir örnek bir sızıntıyı ancak değeri tanıyarak gösterir - ve o değerleri
çıktıların kendisinde arar: ``render_xml``, ``paths`` (metin ve ``--json``), ``service-check --json``,
kümesine özel ``BILGIN_MSSQL_CONN_WWI``den de genel ``BILGIN_MSSQL_CONN``den de gelen bağlantı
dizesini sürücünün geri söylediği yol dahil, ve kurulum betiğinin ``-WhatIf`` koşusu.

Betiğin iki koşusu vardır: ``BILGIN_DEV_ADMIN_PASSWORD`` dururken ``dev-admin-env`` adımında durmalı
ve sırrın değerini söylememeli; o değişken yokken bütün adımlar geçmeli, tmp klasörüyle
``deploy/windows`` olduğu gibi kalmalı. Son satır R8-23'ün bir diğer sözü: WinSW exe'si depoya girmez.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from bilgin import config
from bilgin.cli import main as cli
from bilgin.service import winsw

REPO = Path(config.__file__).resolve().parent.parent
MINI = REPO / "tests" / "fixtures" / "datasets" / "mini"
SCRIPT = REPO / "scripts" / "install-service.ps1"
DEPLOY = REPO / "deploy"
DEV_ADMIN = "BILGIN_DEV_ADMIN_PASSWORD"

# Brief §4'ün beş sırrı: değerleri ne XML'e ne bir terminal satırına düşebilir.
SECRET_NAMES = (
    "BILGIN_MSSQL_CONN",
    "BILGIN_MSSQL_CONN_WWI",
    "BILGIN_LLM_API_KEY",
    "UNSLOTH_API_KEY",
    DEV_ADMIN,
)
_PWD = re.compile(r"PWD=([^;]+)")

WINDOWS_ONLY = pytest.mark.skipif(
    sys.platform != "win32" or shutil.which("powershell.exe") is None,
    reason="install-service.ps1 runs on Windows PowerShell",
)


def conn_string(secret: str) -> str:
    """Sırrı PWD satırında taşıyan bağlantı dizesi: sürücü onu hatada kendine geri söyler."""
    return (
        "DRIVER={ODBC Driver 18 for SQL Server};SERVER=sunucu;DATABASE=erp;"
        f"UID=ro;PWD={secret};"
    )


def closed_port() -> int:
    """Kimsenin dinlemediği bir port: bağlananın anında reddedileceği adresin sayısı."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def assert_clean(text: str, values: dict[str, str]) -> None:
    """Hiçbir sır değeri metinde geçmemeli; bağlantı dizesinin PWD sırrı ayrıca aranır."""
    needles = dict(values)
    for name, value in values.items():
        secret = _PWD.search(value)
        if secret:
            needles[f"{name} PWD"] = secret.group(1)
    leaked = [name for name, needle in needles.items() if needle in text]
    assert not leaked, f"sır çıktıya sızmış: {leaked}\n{text}"


@pytest.fixture
def secrets_env(monkeypatch) -> dict[str, str]:
    """Beş sır değişkeni koşu başına rastgele değerleriyle kurulur; sözlük arama listesidir."""
    values = {
        "BILGIN_MSSQL_CONN": conn_string(secrets.token_hex(8)),
        "BILGIN_MSSQL_CONN_WWI": conn_string(secrets.token_hex(8)),
        "BILGIN_LLM_API_KEY": secrets.token_hex(8),
        "UNSLOTH_API_KEY": secrets.token_hex(8),
        DEV_ADMIN: secrets.token_hex(8),
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return values


def test_render_xml_carries_no_secret(secrets_env):
    xml = winsw.render_xml(
        r"C:\repo\.venv\Scripts\python.exe",
        REPO,
        r"C:\ProgramData\Bilgin",
        8777,
        "wwi",
        "tr",
        "mssql",
        datasets_dir=r"C:\ProgramData\Bilgin\index",
    )

    assert_clean(xml, secrets_env)


def run_paths(*args, **env) -> str:
    """``python -m bilgin paths`` taze bir alt süreçte: config yolları import anında çözülür."""
    child = {key: value for key, value in os.environ.items() if not key.startswith("BILGIN_")}
    child.update({key: str(value) for key, value in env.items()})
    done = subprocess.run(
        [sys.executable, "-m", "bilgin", "paths", *[str(a) for a in args]],
        cwd=str(REPO),
        env=child,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert done.returncode == 0, done.stderr
    return done.stdout + done.stderr


@pytest.mark.parametrize("flag", [[], ["--json"]])
def test_paths_prints_no_secret(secrets_env, flag):
    assert_clean(run_paths(*flag, **secrets_env), secrets_env)


def _rewrite(path: Path, name: str) -> None:
    """Kopyalanan tanımın adı, bağlantısı ve çıktıları; küme klasörü kendi adını taşır."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["name"] = name
    raw["connection"] = "mssql"
    raw["outputs"] = {
        "db": f"data/{name}.db",
        "mssql_script": f"db/mssql/build_{name}.sql",
        "index_dir": f"index/{name}",
        "eval_out": f"eval_out/{name}",
    }
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture
def world(tmp_path, monkeypatch, secrets_env):
    """İki mssql kümesi: ``wwi`` kendi değişkenini okur, ``erp`` genel ``BILGIN_MSSQL_CONN``i."""
    for name in ("wwi", "erp"):
        shutil.copytree(MINI, tmp_path / "datasets" / name)
        _rewrite(tmp_path / "datasets" / name / "dataset.json", name)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(tmp_path / "datasets"))
    monkeypatch.setenv("BILGIN_APP_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("BILGIN_BACKEND", "mssql")
    # Modelin ucu kapalı: yoklamanın cümlesi gerçekten üretilsin, ama sır oraya da sıçramasın.
    monkeypatch.setenv("BILGIN_LLM_BASE_URL", f"http://127.0.0.1:{closed_port()}/v1")
    return tmp_path


def failing_connect(conn_str: str):
    """Sürücünün yaptığı gibi bağlantı dizesini kendine döndüren başarısız bağdaç."""
    raise ConnectionError(f"[08001] Login failed. {conn_str}")


@pytest.mark.parametrize("dataset", ["wwi", "erp"])
@pytest.mark.parametrize("json_out", [True, False])
def test_service_check_prints_no_secret(world, capsys, secrets_env, dataset, json_out):
    code = cli.service_check(dataset, json_out=json_out, connect=failing_connect)
    printed = capsys.readouterr().out

    assert code == 0
    assert_clean(printed, secrets_env)


def child_env(values: dict[str, str]) -> dict[str, str]:
    """Ortamın kendisi + verilen sırlar; listelerdeki bir sır betiğe devralınmaz."""
    env = {key: value for key, value in os.environ.items() if key not in SECRET_NAMES}
    env.update(values)
    return env


def run_whatif(home: Path, port: int, values: dict[str, str]) -> subprocess.CompletedProcess:
    """Betik gerçek PowerShell ile ve ``-WhatIf``le: hiçbir şeyi değiştirmeden yürür."""
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-WhatIf",
            "-Home",
            str(home),
            "-Port",
            str(port),
        ],
        cwd=str(REPO),
        env=child_env(values),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


@WINDOWS_ONLY
def test_the_whatif_refusal_names_the_variable_not_its_value(tmp_path, secrets_env):
    done = run_whatif(tmp_path, closed_port(), secrets_env)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "[dev-admin-env]" in done.stdout
    assert_clean(done.stdout + done.stderr, secrets_env)
    assert list(tmp_path.rglob("*")) == []


@WINDOWS_ONLY
def test_the_whatif_walk_and_the_files_it_leaves_hold_no_secret(tmp_path, secrets_env):
    values = {name: value for name, value in secrets_env.items() if name != DEV_ADMIN}
    before = sorted(path.as_posix() for path in DEPLOY.rglob("*"))

    done = run_whatif(tmp_path, closed_port(), values)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "[url]" in done.stdout
    assert_clean(done.stdout + done.stderr, values)
    assert sorted(path.as_posix() for path in DEPLOY.rglob("*")) == before
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert_clean(path.read_bytes().decode("utf-8", "replace"), values)


def test_deploy_tracks_no_executable():
    """WinSW exe'si indirdiği yerde durur; ``deploy/windows``ın .gitignore'u onu depoya sokmaz."""
    done = subprocess.run(
        ["git", "ls-files", "deploy"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        check=True,
    )

    names = done.stdout.split()
    assert names
    assert [name for name in names if name.lower().endswith(".exe")] == []
