# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T407: bağlantı ve veritabanı cümleleri isteğin dilinde (PLAN R8-5).

Bağlantı ekranının dört yüzü de aynı cümleyi aynı dilden okur: yoklamanın satırları (``#conn-result``),
reddin detayı, durum noktasının alt yazısı ile afişi (``#db-dot``/``#db-banner``, ikisi de
``/api/health``ın ``db`` bloğunu okur) ve düşmüş bir veritabanının soru cevabı. Bekçi arka planda
koştuğu için onun genel cümlesini çip kurar; yöneticinin sürücü cümlesi çevrilmez. Canlı SQL Server
çağrılmaz: ``app.state.conn_connect`` testin sahte bağacını taşır (düzeni tests/test_conn_guard.pydan).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nl2sql import config, datasets
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.engine import connections, dbstatus, dpapi, guard
from nl2sql.engine._mssql import CONN_ENV
from nl2sql.engine.dbstatus import DOWN_MESSAGE, DbStatus
from nl2sql.engine.guard import POWER_MESSAGE
from nl2sql.i18n import t
from nl2sql.i18n.detect import TURKISH_LETTERS
from nl2sql.i18n.scan import user_literals
from nl2sql.schema_map import doc
from nl2sql.web import connections_api
from nl2sql.web.app import create_app
from nl2sql.web.connections_api import ENV_SOURCE, GUARD_REFUSED, NOT_MSSQL

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
PAROLA = "Gizli2026!parola"
ADMIN = "yonetici"
SQLITE_DS, ERP = "synthetic_erp", "erp_live"
KENDI = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=kendi;DATABASE=DNAEGITIM;"
# Gövde parola taşımaz: sır kutusu reddin kendisi değildir, o yüzden ancak isteyen test ekler.
GOVDE = {
    "server": "10.0.0.5",
    "database": "DNAEGITIM",
    "auth": "sql",
    "username": "bilgin_ro",
    "options": {"encrypt": True, "trust_server_certificate": True, "port": None, "driver": ""},
}
BAGLANTI = (
    "DRIVER={ODBC Driver 18 for SQL Server};SERVER=10.0.0.5;DATABASE=WWI;"
    f"UID=bilgin_ro;PWD={PAROLA};"
)
# Sürücünün bağlanamama cümlesi: yönetici çizgisinde durur, kullanıcının cümlesi onun yerine geçer.
SURUCU_HATASI = (
    "[08001] [Microsoft][ODBC Driver 18 for SQL Server]TCP Provider: "
    f"Login failed for user 'bilgin_ro'; PWD={PAROLA};"
)
EN = {"Accept-Language": "en"}

# R8-5: beş modülün kullanıcıya bakan her cümlesi kataloğa taşındı.
MODULLER = (guard, connections, dpapi, dbstatus, connections_api)

# Güç denetimlerinin sorgudaki işaretleri (R7-24'ın yedi sorusu).
ISARETLER = {
    "sysadmin": "IS_SRVROLEMEMBER",
    "db_owner": "IS_MEMBER",
    "insert": "'INSERT'",
    "update": "'UPDATE'",
    "delete": "'DELETE'",
    "alter": "'ALTER'",
    "execute": "'EXECUTE'",
}


class Baglayici:
    """Sahte bağdaç: her yoklamayı sorgunun metnine göre yanıtlayan bağlantı verir."""

    def __init__(self, gucler=(), hata: str | None = None) -> None:
        self.gucler, self.hata = set(gucler), hata
        self.calls: list[str] = []

    def __call__(self, conn_str: str) -> "Baglanti":
        self.calls.append(conn_str)
        if self.hata:
            raise RuntimeError(self.hata)
        return Baglanti(self.gucler)


class Baglanti:
    def __init__(self, gucler: set) -> None:
        self.gucler = gucler
        self.satir: tuple = ()

    def execute(self, sql: str) -> "Baglanti":
        self.satir = (self._cevap(sql),)
        return self

    def fetchone(self) -> tuple:
        return self.satir

    def close(self) -> None:
        pass

    def _cevap(self, sql: str):
        buyuk = sql.upper()
        for ad in self.gucler:
            if ISARETLER[ad] in buyuk:
                return 1
        return 1 if "'OBJECT', 'SELECT'" in buyuk else 0


def copy_dataset(folder: Path, **over) -> None:
    """Mini kümesinin tmp kopyası: ad, çıktı yolları ve söylenen birkaç alan değişir."""
    name = folder.name
    shutil.copytree(FIXTURE_ROOT / "mini", folder)
    meta = json.loads((folder / "dataset.json").read_text(encoding="utf-8"))
    meta.update({"name": name, **over})
    meta["outputs"] = {
        key: value.replace("mini", name) for key, value in (meta.get("outputs") or {}).items()
    }
    (folder / "dataset.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modülün dünyası bir kez: SQLite'ın yanında bir SQL Server kümesi ve bir yönetici."""
    root = tmp_path_factory.mktemp("connslang")
    copy_dataset(root / "datasets" / SQLITE_DS)
    copy_dataset(root / "datasets" / ERP, display_name="ERP Canlı (Sunucu)", connection="mssql")
    patch = pytest.MonkeyPatch()
    patch.setattr(config, "ROOT", root)
    patch.setenv("NL2SQL_DATASETS_DIR", str(root / "datasets"))
    patch.setenv("NL2SQL_REAL_DATASETS_DIR", str(root / "real_datasets"))
    # Kabuktaki her bağlantı değişkeni silinir: geliştiricide NL2SQL_MSSQL_CONN ambiyans durur (R7-29).
    patch.delenv(CONN_ENV, raising=False)
    patch.delenv("NL2SQL_BACKEND", raising=False)
    for name in [n for n in os.environ if n.startswith(config.CONN_ENV_PREFIX)]:
        patch.delenv(name, raising=False)
    try:
        users = UserStore(root / "users.db")
        users.add_user(ADMIN, PAROLA, "admin")
        assert cli.build_database(dataset=SQLITE_DS) == 0
        yield SimpleNamespace(root=root, users=users)
    finally:
        patch.undo()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Program dili ve env kaynakları testler arasında taşınmasın: başlıksız istek Türkçe okur."""
    monkeypatch.delenv("NL2SQL_LANG", raising=False)
    for name in [n for n in os.environ if n.startswith(config.CONN_ENV_PREFIX)]:
        monkeypatch.delenv(name, raising=False)


def _dusen_ping(conn_str: str, timeout=None) -> None:
    raise RuntimeError(SURUCU_HATASI)


def dusmus_bekci() -> DbStatus:
    """Yoklaması her seferinde sürücü cümlesiyle düşen gerçek bekçi: çip kırmızıdır."""
    bekci = DbStatus(lambda _veri_kumesi: {"source": "stored", "conn_str": BAGLANTI},
                     ping=_dusen_ping)
    bekci.check_now(SQLITE_DS)  # çip etkin kümeyi okur; yoklama onun satırında durur
    return bekci


@pytest.fixture
def app(world, tmp_path):
    """Taze uygulama, taze depo dosyası ve salt okunur sayılan sahte bağdaç."""
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    app = create_app(
        open_session(
            dataset=SQLITE_DS,
            llm="fake",
            audit_path=home / "audit.jsonl",
            ask_log=home / "asks.jsonl",
        ),
        saved_path=home / "app.db",
        static_dir=world.root / "static",
        users=world.users,
    )
    app.state.conn_connect = Baglayici()
    return app


@pytest.fixture
def client(app) -> TestClient:
    client = TestClient(app)
    assert client.post(
        "/api/auth/login", json={"username": ADMIN, "password": PAROLA}
    ).status_code == 200
    return client


def satir(rapor: dict, denetim: str) -> dict:
    return next(line for line in rapor["lines"] if line["check"] == denetim)


def turkce_mi(metin: str) -> bool:
    return any(karakter in TURKISH_LETTERS for karakter in metin)


# ------------------------------------------------------------------------ #conn-result satırları


def test_the_guard_report_answers_in_the_language_of_the_request(client, app):
    app.state.conn_connect = Baglayici(gucler={"sysadmin"})
    tablo = sorted(doc.allowlist(datasets.load_dataset(ERP).schema()))[0]

    ingilizce = client.post(f"/api/connections/{ERP}/test", json=GOVDE, headers=EN).json()
    turkce = client.post(f"/api/connections/{ERP}/test", json=GOVDE).json()

    assert satir(ingilizce, "sysadmin") == {
        "check": "sysadmin",
        "ok": False,
        "message": t("guard.power", "en"),
    }
    assert satir(ingilizce, "insert")["message"] == t("guard.permission", "en", permission="INSERT")
    assert satir(ingilizce, "table")["message"] == t("guard.table_ok", "en", name=tablo)
    assert satir(turkce, "sysadmin")["message"] == POWER_MESSAGE
    assert satir(turkce, "insert")["message"] == t("guard.permission", "tr", permission="INSERT")
    assert satir(turkce, "table")["message"] == t("guard.table_ok", "tr", name=tablo)
    # satırların tamamı aynı dili konuşur: yarısı çevrilmiş bir rapor yoktur
    assert all(not turkce_mi(line["message"]) for line in ingilizce["lines"])
    assert all(turkce_mi(line["message"]) for line in turkce["lines"])


def test_a_connect_failure_line_keeps_the_drivers_sentence_in_the_request_language(client, app):
    app.state.conn_connect = Baglayici(hata=SURUCU_HATASI)

    rapor = client.post(f"/api/connections/{ERP}/test", json=GOVDE, headers=EN).json()

    mesaj = rapor["lines"][0]["message"]
    assert mesaj.startswith(t("guard.connect", "en"))
    assert "Login failed" in mesaj, "sürücünün cümlesi çevrilmez, olduğu gibi okunur"
    assert "PWD=***" in mesaj and PAROLA not in mesaj


# --------------------------------------------------------------------------------- redler


def test_a_login_that_can_write_is_refused_in_the_request_language(client, app):
    app.state.conn_connect = Baglayici(gucler={"sysadmin"})

    ingilizce = client.put(f"/api/connections/{ERP}", json=GOVDE, headers=EN)
    turkce = client.put(f"/api/connections/{ERP}", json=GOVDE)

    assert (ingilizce.status_code, turkce.status_code) == (409, 409)
    assert ingilizce.json()["detail"] == t("conn.guard_refused", "en")
    assert turkce.json()["detail"] == GUARD_REFUSED
    assert satir(ingilizce.json()["guard"], "sysadmin")["message"] == t("guard.power", "en")


def test_the_stores_own_refusal_is_in_the_request_language(client):
    govde = {key: value for key, value in GOVDE.items() if key != "server"}

    ingilizce = client.put(f"/api/connections/{ERP}", json=govde, headers=EN)
    turkce = client.put(f"/api/connections/{ERP}", json=govde)

    assert (ingilizce.status_code, turkce.status_code) == (422, 422)
    assert ingilizce.json()["detail"] == t("conn.no_server", "en")
    assert turkce.json()["detail"] == t("conn.no_server", "tr")


def test_the_env_refusal_is_in_the_request_language(client, monkeypatch):
    monkeypatch.setenv(config.CONN_ENV_PREFIX + ERP.upper(), KENDI)

    ingilizce = client.put(f"/api/connections/{ERP}", json=GOVDE, headers=EN)
    turkce = client.put(f"/api/connections/{ERP}", json=GOVDE)

    assert (ingilizce.status_code, turkce.status_code) == (409, 409)
    assert ingilizce.json()["detail"] == t("conn.env_source", "en")
    assert turkce.json()["detail"] == ENV_SOURCE


def test_the_secret_box_refusal_is_in_the_request_language(client, monkeypatch):
    monkeypatch.setattr(dpapi, "available", lambda: False)

    ingilizce = client.put(f"/api/connections/{ERP}", json={**GOVDE, "password": PAROLA}, headers=EN)
    turkce = client.put(f"/api/connections/{ERP}", json={**GOVDE, "password": PAROLA})

    assert (ingilizce.status_code, turkce.status_code) == (409, 409)
    assert ingilizce.json()["detail"] == t("conn.dpapi_off", "en")
    assert turkce.json()["detail"] == t("conn.dpapi_off", "tr")


def test_a_sqlite_dataset_has_no_connection_in_the_request_language(client):
    ingilizce = client.put(f"/api/connections/{SQLITE_DS}", json=GOVDE, headers=EN)
    turkce = client.put(f"/api/connections/{SQLITE_DS}", json=GOVDE)

    assert (ingilizce.status_code, turkce.status_code) == (409, 409)
    assert ingilizce.json()["detail"] == t("conn.not_mssql", "en")
    assert turkce.json()["detail"] == NOT_MSSQL


# ------------------------------------------------------------------ db-dot, db-banner, soru


def test_the_db_chip_reads_the_down_sentence_in_the_request_language(app, client):
    app.state.dbstatus = dusmus_bekci()

    ingilizce = client.get("/api/health", headers=EN).json()["db"]
    turkce = client.get("/api/health").json()["db"]

    assert ingilizce["state"] == turkce["state"] == "down"
    assert ingilizce["message"] == t("db.down", "en")
    assert turkce["message"] == DOWN_MESSAGE
    # yöneticinin çizgisi sürücünün cümlesidir: çevrilmez, yalnız sırrı çıkar
    assert ingilizce["message_admin"] == turkce["message_admin"]
    assert "08001" in ingilizce["message_admin"] and PAROLA not in ingilizce["message_admin"]


def test_a_question_while_the_database_is_down_is_answered_in_the_request_language(app, client):
    app.state.dbstatus = dusmus_bekci()

    ingilizce = client.post("/api/ask", json={"question": "Top 5 products"}, headers=EN).json()
    turkce = client.post("/api/ask", json={"question": "En çok satan 5 ürün"}).json()

    assert ingilizce["error"] == {"kind": "db_down", "message": t("ask.fail.db_down", "en")}
    assert ingilizce["answer_text"] == t("ask.fail.db_down", "en")
    assert turkce["answer_text"] == t("ask.fail.db_down", "tr")


# ---------------------------------------------------------------------------- kataloğun kendisi


@pytest.mark.parametrize("modul", MODULLER, ids=lambda modul: modul.__name__.rsplit(".", 1)[-1])
def test_no_connection_module_writes_turkish_anymore(modul):
    assert user_literals(Path(modul.__file__)) == []
