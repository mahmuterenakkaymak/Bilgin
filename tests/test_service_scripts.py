# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``scripts/uninstall-service.ps1`` ve ``scripts/update-service.ps1`` (PLAN R8-23).

İki betik de operatörün elinde; testleri de betiğin kendisini PowerShell ile koşar ve basılan
adım satırlarını okur. Üç şey sabittir. Sıralama: kaldırma durdurmadan, veri sorusu kaldırmadan;
güncellemede derleme durdurmadan sonra, başlatma derlemeden sonra gelmeli. ``-WhatIf`` sözü:
veri klasörünün adı geçmeli ama içinden tek bir dosya eksilmemeli. Güncellemenin var olma
nedeni: arayüz derlemesi yalnızca ``web/`` altında derlenmiş ``index.html``den yeni bir dosya
varsa koşulur, yoksa salt Python güncellemesi derleme harcamaz - ``web/node_modules`` de her
kurulumda saati değiştiği için kaynak sayılmaz.

Hiçbir betik kaynağı güncellemez (R8-23: kodu operatör taşır), bu yüzden ``git`` sözcüğü iki
dosyada da hiç geçmez. Betikler ASCII olmak zorundadır (Windows PowerShell 5.1 işaretsiz
dosyayı konsolun kod sayfasında okur).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
UNINSTALL = REPO / "scripts" / "uninstall-service.ps1"
UPDATE = REPO / "scripts" / "update-service.ps1"
SERVICE = "Bilgin"

# Kaldırmanın sırası: servis tanınmadan durdurulamaz, durdurulmadan kaldırılamaz, klasör
# sorulmadan silinemez. Güncellemenin sırası: durdurulmadan derlenmez, derlemeden başlatılmaz.
UNINSTALL_STEPS = ["service", "stop", "uninstall", "data"]
UPDATE_STEPS = ["service", "stop", "ui", "start", "health"]

pytestmark = pytest.mark.skipif(
    sys.platform != "win32" or shutil.which("powershell.exe") is None,
    reason="the service scripts run on Windows PowerShell",
)


def run(script: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script), *args],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )


def steps_in_order(out: str, steps: list[str]) -> None:
    positions = [out.find(f"[{step}]") for step in steps]
    missing = [step for step, at in zip(steps, positions) if at < 0]
    assert not missing, f"steps missing from the output: {missing}\n{out}"
    assert positions == sorted(positions), f"steps out of order: {list(zip(steps, positions))}\n{out}"


def step_lines(out: str) -> list[str]:
    return [line for line in out.splitlines() if line.startswith("[")]


def service_installed() -> bool:
    """Betiklerin reddini test etmek için tek güvenli koşul: makinede gerçekten kurulu olmaması.

    Modül düzeyindeki ``skipif`` her platformda değerlendirilir, o yüzden Windows dışı burada
    sessizce ``False`` döndürür - dosyanın kendisi zaten ``pytestmark`` ile atlanır.
    """
    if sys.platform != "win32":
        return False
    probe = subprocess.run(["sc.exe", "query", SERVICE], capture_output=True, text=True, timeout=60)
    return probe.returncode == 0


def touch(path: Path, when: float) -> None:
    os.utime(path, (when, when))


def fixture_repo(tmp_path: Path) -> Path:
    """Koddan arındırılmış bir depo kopyası: yalnızca arayüzün iki tarafı ve node_modules.

    Betik ``-Repo`` ile başka bir köke bakabilsin diye; derlenmiş ``index.html`` ile ``web/``
    altındaki saatler testin elinde kalsın diye.
    """
    repo = tmp_path / "repo"
    (repo / "web" / "src").mkdir(parents=True)
    (repo / "web" / "node_modules" / "vite" / "bin").mkdir(parents=True)
    (repo / "nl2sql" / "web" / "static").mkdir(parents=True)
    (repo / "web" / "src" / "App.jsx").write_text("export function App() {}\n", encoding="utf-8")
    (repo / "web" / "node_modules" / "vite" / "bin" / "vite.js").write_text("//\n", encoding="utf-8")
    (repo / "nl2sql" / "web" / "static" / "index.html").write_text("<!doctype html>\n", encoding="utf-8")
    return repo


def update_out(repo: Path, tmp_path: Path) -> str:
    proc = run(
        UPDATE,
        "-WhatIf",
        "-Repo",
        str(repo),
        "-Home",
        str(tmp_path / "home"),
        "-Port",
        "8777",
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


def test_uninstall_whatif_walks_every_step_in_order(tmp_path: Path) -> None:
    proc = run(UNINSTALL, "-WhatIf", "-Home", str(tmp_path))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    steps_in_order(proc.stdout, UNINSTALL_STEPS)
    assert "WHATIF" in proc.stdout
    # Veri klasörü varsayılan olarak kalır ve adı yine de duyulur.
    assert str(tmp_path) in proc.stdout
    assert list(tmp_path.rglob("*")) == []


def test_uninstall_remove_data_whatif_names_the_folder_and_deletes_nothing(tmp_path: Path) -> None:
    home = tmp_path / "Bilgin"
    (home / "data").mkdir(parents=True)
    (home / "data" / "bilgin.db").write_text("kullanıcılar", encoding="utf-8")
    proc = run(UNINSTALL, "-WhatIf", "-RemoveData", "-Home", str(home))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    steps_in_order(proc.stdout, UNINSTALL_STEPS)
    line = next(line for line in step_lines(proc.stdout) if line.startswith("[data]"))
    assert "WHATIF" in line and "delete" in line.lower()
    assert str(home) in line
    assert (home / "data" / "bilgin.db").exists()
    assert list(home.rglob("*")) != []


@pytest.mark.skipif(service_installed(), reason=f"a real {SERVICE} service exists on this machine")
def test_uninstall_refuses_when_the_service_does_not_exist(tmp_path: Path) -> None:
    proc = run(UNINSTALL, "-Home", str(tmp_path))
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert step_lines(proc.stdout) == [f"[service] no service named {SERVICE} on this machine - nothing to remove"]
    assert list(tmp_path.rglob("*")) == []


@pytest.mark.skipif(service_installed(), reason=f"a real {SERVICE} service exists on this machine")
def test_update_refuses_when_the_service_does_not_exist(tmp_path: Path) -> None:
    proc = run(UPDATE, "-Home", str(tmp_path), "-Port", "8777")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    lines = step_lines(proc.stdout)
    assert len(lines) == 1 and lines[0].startswith("[service] no service named ")
    assert list(tmp_path.rglob("*")) == []


def test_update_whatif_walks_every_step_in_order(tmp_path: Path) -> None:
    proc = run(UPDATE, "-WhatIf", "-Home", str(tmp_path), "-Port", "8777")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    steps_in_order(proc.stdout, UPDATE_STEPS)
    assert "WHATIF" in proc.stdout
    assert list(tmp_path.rglob("*")) == []


def test_update_rebuilds_the_ui_only_when_a_web_file_is_newer(tmp_path: Path) -> None:
    repo = fixture_repo(tmp_path)
    built = time.time()
    app = repo / "web" / "src" / "App.jsx"
    installed = repo / "web" / "node_modules" / "vite" / "bin" / "vite.js"
    index = repo / "nl2sql" / "web" / "static" / "index.html"
    touch(index, built)
    touch(app, built - 3600)
    # node_modules her npm kurulumunda yenilenir: saati öne çıksa da kaynak değildir.
    touch(installed, built + 3600)

    out = update_out(repo, tmp_path)
    assert "ui rebuild" not in out, out

    touch(app, built + 60)
    out = update_out(repo, tmp_path)
    assert "ui rebuild" in out, out
    assert "App.jsx" in out
    assert "vite.js" in out


def test_both_scripts_are_ascii() -> None:
    for script in (UNINSTALL, UPDATE):
        raw = script.read_bytes()
        assert b"\xff" not in raw[:2] and b"\xfe" not in raw[:2], f"{script.name}: a BOM breaks 5.1"
        raw.decode("ascii")


def test_neither_script_touches_the_source_control() -> None:
    for script in (UNINSTALL, UPDATE):
        assert not re.search(r"\bgit\b", script.read_text(encoding="ascii")), script.name
