# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T338: bağlantıların API'si (PLAN R7-22..R7-24, Contracts "connection (public)", "guard report").

Sırrın sunucudan çıkmadığı burada ölçülür: parola yalnız ``PUT``la içeri girer, cevapların
hiçbirinde ne parola ne ``PWD=`` vardır - parolayı gören tek yer, yoklamanın kendi bağlantı
dizesidir. Canlı SQL Server çağrılmaz: ``app.state.conn_connect`` testin sahte bağacını taşır
(düzeni ``tests/test_conn_guard.py``dan), ``app.state.dbstatus`` da durum yoklamasının yerine
geçer. Dünya tmp'dir ve parola kutusu DPAPI istediğinden Windows dışında koşmaz.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nl2sql import config, datasets
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.engine import dpapi
from nl2sql.engine._mssql import CONN_ENV
from nl2sql.engine.connections import BAD_PORT_MESSAGE, NO_DATABASE_MESSAGE, NO_SERVER_MESSAGE
from nl2sql.engine.guard import POWER_MESSAGE
from nl2sql.schema_map import doc
from nl2sql.web.app import create_app
from nl2sql.web.authz import NOT_ADMIN
from nl2sql.web.connections_api import ENV_SOURCE, GUARD_REFUSED, NOT_MSSQL

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="parola kutusu (DPAPI) yalnız Windows'ta vardır"
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
PAROLA = "Gizli2026!parola"
ADMIN, USER = "yonetici", "kullanici"
SQLITE_DS, ERP = "synthetic_erp", "erp_live"
KENDI = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=kendi;DATABASE=DNAEGITIM;"
GOVDE = {
    "server": "10.0.0.5",
    "database": "DNAEGITIM",
    "auth": "sql",
    "username": "bilgin_ro",
    "password": PAROLA,
    "options": {"encrypt": True, "trust_server_certificate": True, "port": None, "driver": ""},
}

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
    """Sahte bağdaç: her yoklamayı sorgunun metnine göre yanıtlayan bağlantı verir.

    ``gucler`` hangi gücün 1 olduğunu - yani girişin fazla yetkili - ``okunamayan`` hangi
    tablonun görünmez olduğunu söyler; ``hata`` verilirse bağlantı hiç kurulamaz ve sürücünün
    cümlesi raporun tek satırı olur. Hangi bağlantı dizesiyle çağrıldığı ``calls``da durur:
    parolanın yoklamaya gerçekten gittiği oradan okunur.
    """

    def __init__(self, gucler=(), okunamayan=(), hata: str | None = None) -> None:
        self.gucler, self.okunamayan, self.hata = set(gucler), set(okunamayan), hata
        self.calls: list[str] = []

    def __call__(self, conn_str: str) -> "Baglanti":
        self.calls.append(conn_str)
        if self.hata:
            raise RuntimeError(self.hata)
        return Baglanti(self.gucler, self.okunamayan)


class Baglanti:
    def __init__(self, gucler: set, okunamayan: set) -> None:
        self.gucler, self.okunamayan = gucler, okunamayan
        self.satir: tuple = ()

    def execute(self, sql: str) -> "Baglanti":
        self.satir = (self._cevap(sql),)
        return self

    def fetchone(self) -> tuple:
        return self.satir

    def close(self) -> None:
        pass

    def _cevap(self, sql: str):
        # Haritanın adı allowlistte büyük harfli: yoklama hangi yazımla sorarsa sorsun aynı.
        buyuk = sql.upper()
        for ad in self.gucler:
            if ISARETLER[ad] in buyuk:
                return 1
        if "'OBJECT', 'SELECT'" in buyuk:
            return 0 if any(ad.upper() in buyuk for ad in self.okunamayan) else 1
        return 0


class Durum:
    """Sahte durum yoklaması: kaç kez erken yoklamaya çağrıldığı ve noktanın ne gösterdiği."""

    def __init__(self, state: str = "ok") -> None:
        self.state_value, self.kicks = state, 0

    def state(self, dataset: str) -> dict:
        return {"state": self.state_value, "checked_at": None, "message": None}

    def kick(self) -> None:
        self.kicks += 1


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
    """Modülün dünyası bir kez: biri SQLite, biri SQL Server iki küme, bir yönetici ve bir kullanıcı."""
    root = tmp_path_factory.mktemp("conns")
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
        users.add_user(USER, PAROLA, "user")
        for name in (SQLITE_DS, ERP):
            assert cli.build_database(dataset=name) == 0
        yield SimpleNamespace(root=root, users=users)
    finally:
        patch.undo()


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Testin kendi değişkenleri de sönümlensin: env kaynağı testi diğerine taşınmasın."""
    for name in [n for n in os.environ if n.startswith(config.CONN_ENV_PREFIX)]:
        monkeypatch.delenv(name, raising=False)


def build_app(world, home: Path, dataset: str = SQLITE_DS):
    """Taze uygulama, taze depo dosyası: bir testin kaydı diğerinin satırı olmaz."""
    home.mkdir(parents=True, exist_ok=True)
    app = create_app(
        open_session(
            dataset=dataset,
            llm="fake",
            audit_path=home / "audit.jsonl",
            ask_log=home / "asks.jsonl",
        ),
        saved_path=home / "app.db",
        static_dir=world.root / "static",
        users=world.users,
    )
    app.state.conn_connect = Baglayici()  # varsayılan: salt okunur bir giriş
    return app


@pytest.fixture
def app(world, tmp_path):
    return build_app(world, tmp_path)


def logged_in(app, username: str = ADMIN) -> TestClient:
    client = TestClient(app)
    response = client.post(
        "/api/auth/login", json={"username": username, "password": PAROLA}
    )
    assert response.status_code == 200, f"{username} giriş yapamadı: {response.status_code}"
    return client


@pytest.fixture
def client(app) -> TestClient:
    return logged_in(app)


def satir(rows: list[dict], dataset: str) -> dict:
    return next(row for row in rows if row["dataset"] == dataset)


# ------------------------------------------------------------------ sırrın çıkmaması


def test_no_answer_carries_the_password_or_a_connection_string(client, app):
    saved = client.put(f"/api/connections/{ERP}", json=GOVDE)

    assert saved.status_code == 200
    answers = [
        saved,
        client.get("/api/connections"),
        client.get(f"/api/connections/{ERP}"),
        client.post(f"/api/connections/{ERP}/test", json=GOVDE),
    ]
    for answer in answers:
        assert answer.status_code == 200
        assert PAROLA not in answer.text
        assert "PWD=" not in answer.text
        assert "DRIVER=" not in answer.text
    # parolayı yalnız sahte bağdaç görür: dize yoklama için kuruluyor, cevapta işi yok
    assert f"PWD={PAROLA};" in app.state.conn_connect.calls[0]
    assert "UID=bilgin_ro" in app.state.conn_connect.calls[0]


def test_a_connect_failure_is_one_scrubbed_line(client, app):
    app.state.conn_connect = Baglayici(
        hata=f"[28000] Login failed for user 'bilgin_ro'; PWD={PAROLA}; tekrar deneyin."
    )

    reported = client.post(f"/api/connections/{ERP}/test", json=GOVDE)

    assert reported.status_code == 200
    assert [line["check"] for line in reported.json()["lines"]] == ["connect"]
    assert PAROLA not in reported.text
    assert "PWD=***" in reported.text


def test_a_login_that_can_write_is_refused_and_no_row_is_written(client, app):
    app.state.conn_connect = Baglayici(gucler={"sysadmin"})

    refused = client.put(f"/api/connections/{ERP}", json=GOVDE)

    assert refused.status_code == 409
    assert refused.json()["detail"] == GUARD_REFUSED
    report = refused.json()["guard"]
    assert report["ok"] is False
    assert report["login_script_url"] == f"/api/datasets/{ERP}/login-script.sql"
    assert next(line for line in report["lines"] if line["check"] == "sysadmin")[
        "message"
    ] == POWER_MESSAGE
    # satır yazılmadı: form yine boş bir bağlantı görür
    row = client.get(f"/api/connections/{ERP}").json()
    assert row["server"] == "" and row["has_secret"] is False and row["source"] == "none"


# ------------------------------------------------------------------ sözleşmenin satırı


def test_a_saved_connection_is_listed_with_its_source_and_state(client, app):
    assert client.put(f"/api/connections/{ERP}", json=GOVDE).status_code == 200

    rows = client.get("/api/connections").json()["connections"]

    assert [row["dataset"] for row in rows] == [ERP]  # SQLite kümesinin bağlantısı yoktur
    row = rows[0]
    assert row["server"] == "10.0.0.5" and row["database"] == "DNAEGITIM"
    assert row["auth"] == "sql" and row["username"] == "bilgin_ro"
    assert row["has_secret"] is True
    assert row["source"] == "stored" and row["read_only_form"] is False
    assert row["state"] == "unknown"  # yoklama henüz hiçbir şey sormadı
    assert row["options"] == GOVDE["options"]


def test_the_test_endpoint_reports_without_saving_anything(client):
    reported = client.post(f"/api/connections/{ERP}/test", json=GOVDE)

    assert reported.status_code == 200
    assert reported.json()["ok"] is True
    assert reported.json()["missing_tables"] == []
    assert client.get(f"/api/connections/{ERP}").json()["server"] == ""


def test_an_invisible_table_is_reported_but_does_not_refuse_the_save(client, app):
    # yoklama allowlistin adlarını sorar; rapor da o adları yazar (R7-24)
    tablo = sorted(doc.allowlist(datasets.load_dataset(ERP).schema()))[0]
    app.state.conn_connect = Baglayici(okunamayan={tablo})

    saved = client.put(f"/api/connections/{ERP}", json=GOVDE)

    assert saved.status_code == 200
    assert saved.json()["guard"]["missing_tables"] == [tablo]


def test_the_status_dot_comes_from_the_checker_and_a_save_kicks_it(client, app):
    durum = Durum(state="down")
    app.state.dbstatus = durum

    assert client.get("/api/connections").json()["connections"][0]["state"] == "down"
    assert client.put(f"/api/connections/{ERP}", json=GOVDE).status_code == 200

    assert durum.kicks == 1


# ------------------------------------------------------------------ ortam değişkeni


def test_ones_own_variable_makes_the_form_read_only_and_the_save_refused(client, monkeypatch):
    monkeypatch.setenv(config.CONN_ENV_PREFIX + ERP.upper(), KENDI)

    row = client.get(f"/api/connections/{ERP}").json()

    assert row["source"] == "env_dataset" and row["read_only_form"] is True

    refused = client.put(f"/api/connections/{ERP}", json=GOVDE)

    assert refused.status_code == 409
    assert refused.json()["detail"] == ENV_SOURCE
    assert client.get(f"/api/connections/{ERP}").json()["server"] == ""


# ------------------------------------------------------------------ oturumun yenilenmesi


def test_saving_the_active_datasets_connection_rebuilds_the_session(world, tmp_path):
    app = build_app(world, tmp_path / "etkin", dataset=ERP)
    client = logged_in(app)
    before = app.state.session

    assert client.put(f"/api/connections/{ERP}", json=GOVDE).status_code == 200

    assert app.state.session is not before
    assert app.state.session.dataset.name == ERP


def test_saving_another_datasets_connection_leaves_the_session_alone(client, app):
    before = app.state.session

    assert client.put(f"/api/connections/{ERP}", json=GOVDE).status_code == 200

    assert app.state.session is before


# ------------------------------------------------------------------ redler ve yetki


def test_a_blank_form_is_refused_with_the_stores_own_sentences(client):
    assert client.put(f"/api/connections/{ERP}", json={"database": "DNAEGITIM"}).json()[
        "detail"
    ] == NO_SERVER_MESSAGE
    assert client.put(f"/api/connections/{ERP}").json()["detail"] == NO_SERVER_MESSAGE
    assert client.put(f"/api/connections/{ERP}", json={"server": "10.0.0.5"}).json()[
        "detail"
    ] == NO_DATABASE_MESSAGE


def test_an_invalid_port_is_refused_before_the_server_is_asked(client, app):
    govde = {**GOVDE, "options": {**GOVDE["options"], "port": 99999}}

    refused = client.put(f"/api/connections/{ERP}", json=govde)

    assert refused.status_code == 422
    assert refused.json()["detail"] == BAD_PORT_MESSAGE
    assert app.state.conn_connect.calls == []


def test_a_sqlite_dataset_has_no_connection_to_edit(client):
    refused = client.put(f"/api/connections/{SQLITE_DS}", json=GOVDE)

    assert refused.status_code == 409
    assert refused.json()["detail"] == NOT_MSSQL
    assert client.get(f"/api/connections/{SQLITE_DS}").status_code == 409


def test_an_unknown_dataset_is_not_found(client):
    assert client.get("/api/connections/olmayan").status_code == 404
    assert client.put("/api/connections/olmayan", json=GOVDE).status_code == 404
    assert client.post("/api/connections/olmayan/test").status_code == 404


@pytest.mark.parametrize(
    "yontem, yol",
    [
        ("GET", "/api/connections"),
        ("GET", f"/api/connections/{ERP}"),
        ("PUT", f"/api/connections/{ERP}"),
        ("POST", f"/api/connections/{ERP}/test"),
    ],
)
def test_a_user_is_refused_every_connection_route(app, yontem, yol):
    client = logged_in(app, USER)

    refused = client.request(yontem, yol, json=GOVDE if yontem == "PUT" else None)

    assert refused.status_code == 403
    assert refused.json() == {"detail": NOT_ADMIN}


def test_the_form_is_closed_when_this_server_cannot_seal_a_secret(client, app, monkeypatch):
    monkeypatch.setattr(dpapi, "available", lambda: False)

    refused = client.put(f"/api/connections/{ERP}", json=GOVDE)

    assert refused.status_code == 409
    assert refused.json()["detail"].startswith("Bu sunucuda parola saklanamaz")
    assert app.state.conn_connect.calls == []  # denemeye bile değmez
