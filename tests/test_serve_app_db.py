# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T265: ``serve`` kayıtları kullanıcının yaşadığı dosyaya yazar (PLAN R6-1, R6-9).

Kullanıcı deposu ``BILGIN_APP_DB``den kuruluyor ama ``create_app``e ``saved_path`` verilmiyordu, o
yüzde kapı imzanın bağlandığı ``config.APP_DB_PATH``e düşüp ``data/bilgin.db``yi kendi açıyordu -
smoke (T232) ve ``scripts/visual_serve.py`` (T235) tam da gerçek dosyaya dokunmamak için o değişkeni
kuruyorlardı. Burada dünya tmp'de: mini küme, sahte model, ``run_server`` yerine geçen bir kapı.

Depodaki ``data/bilgin.db`` bu testte bir ölçümdür: koşudan önce var mı ve hangi damgada, koşudan
sonra da o. Değişirse ``SavedStore`` kullanıcı dosyasının dışına çıkmış demektir.
"""

import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bilgin import config
from bilgin.auth.store import UserStore
from bilgin.cli import main as cli

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
PAROLA = "Bilgin2026!erp"
REPO_APP_DB = config.APP_DB_PATH  # import anının yolu: config.ROOT değişse de depoda kalır
QUESTION = "geçen ay net ciro ne kadar"


def stamp() -> tuple[bool, int]:
    """Depodaki uygulama veritabanının yokluk/damga izi; koşu boyunca değişmemesi beklenir."""
    if not REPO_APP_DB.exists():
        return (False, 0)
    return (True, REPO_APP_DB.stat().st_mtime_ns)


@pytest.fixture
def app_db(tmp_path, monkeypatch):
    """tmp'de kurulu mini dünyanın uygulama veritabanı; yöneticisi olan tek dosya."""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(FIXTURE_ROOT))
    monkeypatch.setenv("BILGIN_APP_DB", str(tmp_path / "app.db"))
    monkeypatch.delenv(config.DEV_ADMIN_ENV, raising=False)
    monkeypatch.setattr(config, "AUDIT_LOG", tmp_path / "audit.jsonl")
    monkeypatch.setattr(config, "ASK_LOG", tmp_path / "asks.jsonl")
    cli.build_database(dataset="mini")
    UserStore(tmp_path / "app.db").add_user("admin", PAROLA, "admin")
    return tmp_path / "app.db"


def served(app_db, monkeypatch) -> TestClient:
    """Gerçek ``serve`` bir kez: sunucu açılmaz, kurulan kapının istemcisi döner."""
    seen: dict = {}
    monkeypatch.setattr(cli, "run_server", lambda app, host, port: seen.update(app=app))
    assert cli.serve(llm_kind="fake", dataset="mini") == 0
    client = TestClient(seen["app"])
    login = client.post("/api/auth/login", json={"username": "admin", "password": PAROLA})
    assert login.status_code == 200, login.text
    return client


def test_the_gate_reads_the_user_file_for_its_own_state(app_db, monkeypatch):
    served_app = served(app_db, monkeypatch).app

    assert served_app.state.saved_path == app_db
    assert served_app.state.users.path == app_db


def test_a_saved_question_lands_in_the_user_file(app_db, monkeypatch):
    client = served(app_db, monkeypatch)

    assert client.post("/api/saved", json={"question": QUESTION}).status_code == 200

    conn = sqlite3.connect(app_db)
    try:
        rows = conn.execute("SELECT question FROM saved").fetchall()
    finally:
        conn.close()
    assert [row[0] for row in rows] == [QUESTION]


def test_the_repo_app_db_is_neither_created_nor_touched(app_db, monkeypatch):
    before = stamp()  # ``create_app`` dosyayı daha ilk adımda açıyor, o yüzden koşudan önce alınır

    client = served(app_db, monkeypatch)
    assert client.post("/api/saved", json={"question": QUESTION}).status_code == 200

    assert stamp() == before, f"{REPO_APP_DB} dokunulmadı; kapı kullanıcı dosyasının dışına çıktı"
