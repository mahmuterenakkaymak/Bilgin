# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``scripts/install-service.ps1`` (PLAN R8-23): betiğin kendisi Windows PowerShell ile koşulur.

Kurulum betiği bir servisin makinesini değiştiren tek dosyadır, o yüzden testi de betiğin
gerçeğidir: ``-WhatIf`` ile çağrılır, hiçbir şeyin değişmediği yerinde görülür. Test üç şeyi
sabitler. Birincisi sıralama - R8-23'ün adımları çıktıda aynı sırada geçmeli, yoksa operatör
hangi yoklamanın neyin önünde koştuğunu bilemez. İkincisi ``-WhatIf``in sözü: tmp klasörü boş
kalmalı, hiçbir WinSW exe'si belirmemeli, ama XML yine de basılmalı ve kurulacak servisi
anlatmalı. Üçüncüsü reddin sınırı - ``BILGIN_DEV_ADMIN_PASSWORD`` makine ya da kabuk düzeyinde
dururken beti ``dev-admin-env`` adımında durmalı, ardından tek bir adım daha gelmemeli.

Betik ASCII olmak zorundadır (Windows PowerShell 5.1 işaretsiz dosyayı konsolun kod sayfasında
okur) ve tek bir indirme adresi taşıyabilir: sabitlenmiş WinSW sürümü.
"""

from __future__ import annotations

import os
import re
import shutil
import socket
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "install-service.ps1"
WINSW_VERSION = "2.12.0"
WINSW_URL = f"https://github.com/winsw/winsw/releases/download/v{WINSW_VERSION}/WinSW-x64.exe"
DEV_ADMIN = "BILGIN_DEV_ADMIN_PASSWORD"

# R8-23'in adım sırası: yoklamalar kuruluma, kurulum sağlık yoklamasına önkoşuldur.
STEPS = [
    "admin",
    "dev-admin-env",
    "shell",
    "venv",
    "port",
    "model",
    "connection",
    "winsw",
    "home",
    "appdb",
    "index",
    "secrets",
    "admin-user",
    "xml",
    "install",
    "start",
    "health",
    "url",
]

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or shutil.which("powershell.exe") is None,
    reason="install-service.ps1 runs on Windows PowerShell",
)


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run(home: Path, port: int, extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    """Betik gerçek PowerShell ile, kurulumun kendi komut satırından: -WhatIf, -Home, -Port."""
    env = {key: value for key, value in os.environ.items() if key != DEV_ADMIN}
    env.update(extra or {})
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
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def test_whatif_walks_every_step_in_order(tmp_path: Path) -> None:
    out = run(tmp_path, free_port()).stdout
    positions = [out.find(f"[{step}]") for step in STEPS]
    missing = [step for step, at in zip(STEPS, positions) if at < 0]
    assert not missing, f"steps missing from the output: {missing}\n{out}"
    assert positions == sorted(positions), f"steps out of order: {list(zip(STEPS, positions))}\n{out}"
    assert "WHATIF" in out


def test_whatif_prints_the_xml_the_service_will_run(tmp_path: Path) -> None:
    port = free_port()
    out = run(tmp_path, port).stdout
    xml = re.search(r"(?s)<service>.*?</service>", out)
    assert xml, f"no XML in the output:\n{out}"
    root = ET.fromstring(xml.group(0))
    assert root.findtext("id") == "Bilgin"
    assert (
        root.findtext("arguments")
        == f"-m bilgin serve --host 127.0.0.1 --port {port} --dataset synthetic_erp"
    )
    assert root.findtext("workingdirectory").replace("/", "\\") == str(REPO)


def test_whatif_changes_and_downloads_nothing(tmp_path: Path) -> None:
    proc = run(tmp_path, free_port())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert list(tmp_path.rglob("*")) == []


def test_the_development_admin_password_stops_the_install_before_any_change(tmp_path: Path) -> None:
    proc = run(tmp_path, free_port(), {DEV_ADMIN: "kurulum-parolasi"})
    assert proc.returncode == 1, proc.stdout + proc.stderr
    out = proc.stdout
    assert "[dev-admin-env]" in out
    tail = out[out.index("[dev-admin-env]") + 1 :]
    assert not [step for step in STEPS if step != "dev-admin-env" and f"[{step}]" in tail], (
        f"steps ran after the refusal:\n{out}"
    )
    assert list(tmp_path.rglob("*")) == []


def test_the_script_is_ascii_and_downloads_only_the_pinned_winsw_release() -> None:
    raw = SCRIPT.read_bytes()
    assert b"\xff" not in raw[:2] and b"\xfe" not in raw[:2], "a byte-order mark breaks 5.1"
    text = raw.decode("ascii")
    urls = {url for url in re.findall(r"""https?://[^'"\s]+""", text) if "127.0.0.1" not in url}
    assert urls == {WINSW_URL.replace(WINSW_VERSION, "$WinSwVersion")}
    assert f'$WinSwVersion = \'{WINSW_VERSION}\'' in text
