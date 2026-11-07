# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T463: durum noktası sunucunun BAŞLADIĞI kümeyi değil o anki etkin kümeyi izler (PLAN R7-23, Contracts "health db").

Genel ``BILGIN_MSSQL_CONN`` yalnız etkin kümenin olduğundan bekçi etkin kümenin adını sunucunun
başlangıcından alıyordu: geçişten sonra yeni kümenin noktası hiç yanmıyor ("none"), eski küme
genel değişkenle yoklanmaya devam ediyordu. Dünya ``tests/test_serve_app_db.py`` ile aynı gerçeklikte
- tmp'de iki SQL Server kümesi, sahte model, ``run_server`` yerine geçen bir kapı - bir de
``SELECT 1``in yerine geçen bir yoklama; canlı SQL Server yoktur.
"""

import json
import os
import shutil
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from bilgin import config
from bilgin.auth.store import UserStore
from bilgin.cli import main as cli
from bilgin.engine import dbstatus
from bilgin.engine.connections import ConnectionStore

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
PAROLA = "Bilgin2026!erp"
GENEL = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=genel;DATABASE=WWI;UID=bilgin_ro;"


def copy_dataset(root: Path, name: str) -> Path:
    """Mini kümesinin SQL Server ilan edilmiş tmp kopyası: çıktı yolları da adı taşır."""
    folder = root / name
    shutil.copytree(FIXTURE_ROOT / "mini", folder)
    meta = json.loads((folder / "dataset.json").read_text(encoding="utf-8"))
    meta.update({"name": name, "connection": "mssql"})
    meta["outputs"] = {
        key: value.replace("mini", name) for key, value in (meta.get("outputs") or {}).items()
    }
    (folder / "dataset.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return folder


class Ping:
    """``SELECT 1``in yerine geçer; hangi bağlantı dizesinin yoklandığını da kaydeder."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, conn_str: str, timeout: float | None = None) -> None:
        self.calls.append(conn_str)


@pytest.fixture
def baglantilar(monkeypatch):
    """İki SQL Server kümesi, genel ortam değişkeni ve mssql yedeği; kabuktaki her bağlantı silinir."""
    for name in [n for n in os.environ if n.startswith(config.CONN_ENV_PREFIX)] + [
        "BILGIN_MSSQL_CONN",
        "BILGIN_BACKEND",
    ]:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("BILGIN_BACKEND", "mssql")
    monkeypatch.setenv("BILGIN_MSSQL_CONN", GENEL)
    return monkeypatch


@pytest.fixture
def world(tmp_path, baglantilar, capsys):
    """Gerçek ``serve`` bir kez: alfa üzerinde açılır, sunucu açılmaz, kurulan kapının istemcisi döner."""
    root = tmp_path / "datasets"
    copy_dataset(root, "alfa")
    copy_dataset(root, "beta")
    baglantilar.setenv("BILGIN_DATASETS_DIR", str(root))
    baglantilar.setattr(config, "ROOT", tmp_path)
    baglantilar.setenv("BILGIN_APP_DB", str(tmp_path / "app.db"))
    baglantilar.delenv(config.DEV_ADMIN_ENV, raising=False)
    baglantilar.setattr(config, "AUDIT_LOG", tmp_path / "audit.jsonl")
    baglantilar.setattr(config, "ASK_LOG", tmp_path / "asks.jsonl")
    UserStore(tmp_path / "app.db").add_user("admin", PAROLA, "admin")

    seen: dict = {}
    baglantilar.setattr(cli, "run_server", lambda app, host, port: seen.update(app=app))
    ping = Ping()
    baglantilar.setattr(dbstatus, "ping", ping)
    # Bekçinin etkin kümeyi kime sorduğu: düzeltmenin ölçtüğü şey tam olarak bu üçüncü argüman.
    sorulan: list[tuple] = []
    gercek = cli.resolve_connection

    def kaydet(dataset, store, active):
        found = gercek(dataset, store, active)
        sorulan.append((str(dataset), active))
        return found

    baglantilar.setattr(cli, "resolve_connection", kaydet)

    capsys.readouterr()
    assert cli.serve(llm_kind="fake", dataset="alfa") == 0
    client = TestClient(seen["app"])
    login = client.post("/api/auth/login", json={"username": "admin", "password": PAROLA})
    assert login.status_code == 200, login.text
    try:
        yield client, sorulan, ping
    finally:
        client.app.state.dbstatus.stop()


def saglik(client: TestClient, beklenen: str, sure: float = 3.0) -> dict:
    """Çipin cevabı: yoklama arka planda koşar, ilk okuma yalnız sorar, istek hiç beklemez."""
    son = time.perf_counter() + sure
    while True:
        block = client.get("/api/health").json()["db"]
        if block["state"] == beklenen or time.perf_counter() > son:
            return block
        time.sleep(0.02)


def test_the_dot_follows_the_dataset_the_server_switched_to(world):
    """Beta'ya geçişin ardından nokta beta için yanar; alfa artık kendini etkin sayarak çözümlenmez."""
    client, sorulan, ping = world

    assert saglik(client, "ok")["state"] == "ok", "açılışın kümesi genel değişkeninden yoklanır"
    assert set(ping.calls) == {GENEL}
    sorulan.clear()

    assert client.post("/api/datasets/active", json={"name": "beta"}).status_code == 200

    block = saglik(client, "ok")
    assert block["state"] == "ok", f"beta'nın noktası {block['state']} - genel değişken ona ait"
    assert ("beta", "beta") in sorulan
    assert ("alfa", "alfa") not in sorulan, "geçişin ardından alfa etkin sayılmaz"
    assert ("alfa", "beta") in sorulan, "alfa artık etkin kümenin gölgesinde sorulur"
    # İkinci yoklama betanın: alfa geçişten sonra hiçbir bağlantı çözemediği için yoklanamaz.
    assert len(ping.calls) >= 2 and set(ping.calls) == {GENEL}


def test_the_probe_file_checker_asks_the_active_dataset_too(tmp_path, baglantilar):
    """``--db-probe-file``ın çözümleyicisi de etkin kümeyi her yoklamada yeniden okur (R7-26)."""
    probe = tmp_path / "probe.json"
    probe.write_text("{}", encoding="utf-8")
    store = ConnectionStore(tmp_path / "app.db")

    bekci = cli._db_status(
        store,
        SimpleNamespace(name="alfa"),
        probe,
        get_active=lambda: "beta",
    )

    assert bekci.check_now("beta")["state"] == "ok"
    assert bekci.check_now("alfa")["state"] == "none"
