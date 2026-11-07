# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T345: M25 entegrasyonu — bağlantı, bekçi ve soru tek gerçek dünyada (PLAN R7-22..R7-25).

Kurmaca tek parça yok: kullanıcılar gerçek ``UserStore``, bağlantılar gerçek ``ConnectionStore``
(DPAPI), kaynağı gerçek ``resolve``, oturum gerçek ``open_session``, kapı gerçek ``create_app``,
nokta gerçek ``DbStatus``. Dışarıdan gelen yalnız iki yer var: guard'ın bağacı (canlı SQL Server
yerine salt okunur bir girişi yanıtlar) ve bekçinin ``SELECT 1``i. Zincir sırasıyla ölçülür:
yönetici tmp SQL Server kümesine salt okunur bir bağlantı kaydeder ve geçişte yürütücü o dizeyi
taşır; bekçi ok → down → ok derken ``/api/health`` kullanıcı için genel cümleyle birlikte uyar;
veritabanı düşmüşken soru sunucuya hiç gitmez; ``NL2SQL_MSSQL_CONN_<NAME>`` kayıtlı satırın üstüne
geçer ve form okunur olur; parola hiçbir cevabın içinde görünmez.

Nokta bekçinin kendi yoklamasıyla (``check_now``) yürür: iş parçacığının zamanı testin koşulu değil.
Parola kutusu DPAPI istediğinden Windows dışında koşmaz; kabuktaki her bağlantı değişkeni silinir,
yoksa geliştiricide ambiyans duran ``NL2SQL_MSSQL_CONN`` kümenin yerini alır (R7-29).
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
from pytest import MonkeyPatch

from nl2sql import config, datasets
from nl2sql.app.ask import DB_DOWN_MESSAGE
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.engine import _mssql, connections
from nl2sql.engine._mssql import CONN_ENV
from nl2sql.engine.connections import ConnectionStore
from nl2sql.engine.dbstatus import DOWN_MESSAGE, DbStatus
from nl2sql.engine.result import Result
from nl2sql.web.app import CONNECTIONS_URL, create_app
from nl2sql.web.connections_api import ENV_SOURCE

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="parola kutusu (DPAPI) yalnız Windows'ta vardır"
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
SQLITE_DS, ERP = "synthetic_erp", "erp_live"
ADMIN, USER = "yonetici", "kullanici"
PAROLA = "Giris2026!parola"  # hesapların giriş parolası
GIZLI = "Bilgin!2026erp"  # SQL Server'ın parolası: hiçbir cevapta aranan sır budur
KENDI = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=kendi;DATABASE=DNAEGITIM;"
GOVDE = {
    "server": "10.0.0.5",
    "database": "DNAEGITIM",
    "auth": "sql",
    "username": "bilgin_ro",
    "password": GIZLI,
    "options": {"encrypt": True, "trust_server_certificate": True, "port": None, "driver": ""},
}

# Sürücünün bağlanamama cümlesi: parolayı geri yazan hâlin kendisi (brief §4).
SURUCU = (
    "[08001] [Microsoft][ODBC Driver 18 for SQL Server]TCP Provider: Zaman aşımı aşıldı. "
    f"Login failed for user 'bilgin_ro'; PWD={GIZLI}; SERVER=10.0.0.5,1433"
)


class Baglayici:
    """Yoklamanın sahte bağacı: salt okunur bir girişi yanıtlar - her güç 0, her tablo okunur."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __call__(self, conn_str: str) -> "Baglanti":
        self.calls.append(conn_str)
        return Baglanti()


class Baglanti:
    satir: tuple = (0,)

    def execute(self, sql: str) -> "Baglanti":
        self.satir = (1 if "'OBJECT', 'SELECT'" in sql.upper() else 0,)
        return self

    def fetchone(self) -> tuple:
        return self.satir

    def close(self) -> None:
        pass


class Ping:
    """Bekçinin ``SELECT 1``i: ``saglam`` mi, sürücünün cümlesiyle mi düşeceği."""

    def __init__(self) -> None:
        self.saglam = True

    def __call__(self, conn_str: str, timeout=None) -> None:
        if not self.saglam:
            raise RuntimeError(SURUCU)


def copy_dataset(folder: Path, **over) -> None:
    """Mini kümesinin tmp kopyası: ad, çıktı yolları ve söylenen birkaç alan değişir."""
    shutil.copytree(FIXTURE_ROOT / "mini", folder)
    meta = json.loads((folder / "dataset.json").read_text(encoding="utf-8"))
    meta.update({"name": folder.name, **over})
    meta["outputs"] = {
        key: value.replace("mini", folder.name) for key, value in (meta.get("outputs") or {}).items()
    }
    (folder / "dataset.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def defter(store: ConnectionStore):
    """``serve``in bekçiye taktığı defter (R7-22): her gerçek yoklama satırın satırına yazılır."""

    def record(dataset: str, ok: bool, error: str | None) -> None:
        if ok:
            store.mark_ok(dataset)
        else:
            store.mark_error(dataset, error)

    return record


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modülün dünyası bir kez: SQLite kümesi, onun SQL Server ilan edilmiş kopyası, bir kapı.

    Zincir testleri aynı dünyayı sırayla koşar (M24'ün panoları gibi): kayıt, geçiş, sağlık ve
    ortam değişkeni aynı oturumun üstünde büyür, bu yüzden her test bir öncekinin hâlini görür.
    """
    root = tmp_path_factory.mktemp("m25")
    copy_dataset(root / "datasets" / SQLITE_DS)
    copy_dataset(root / "datasets" / ERP, display_name="ERP Canlı (Sunucu)", connection="mssql")
    mp = MonkeyPatch()
    mp.setattr(config, "ROOT", root)
    mp.setenv("NL2SQL_DATASETS_DIR", str(root / "datasets"))
    mp.setenv("NL2SQL_REAL_DATASETS_DIR", str(root / "real_datasets"))
    mp.delenv(CONN_ENV, raising=False)
    mp.delenv("NL2SQL_BACKEND", raising=False)
    for name in [n for n in os.environ if n.startswith(config.CONN_ENV_PREFIX)]:
        mp.delenv(name, raising=False)

    runs: list[dict] = []

    def fake_run(sql, budget, conn_str=None):
        """Sunucunun yeri: hangi SQL hangi bağlantı dizesiyle koştu, satır burada durur."""
        runs.append({"sql": sql, "conn_str": conn_str})
        return Result(columns=["CIRO"], rows=[(1234.5,)], row_count=1)

    mp.setattr(_mssql, "run", fake_run)
    try:
        users = UserStore(root / "bilgin.db")
        users.add_user(ADMIN, PAROLA, "admin")
        users.add_user(USER, PAROLA, "user")
        for name in (SQLITE_DS, ERP):
            assert cli.build_database(dataset=name) == 0
        store = ConnectionStore(root / "bilgin.db")
        ping = Ping()
        bekci = DbStatus(
            lambda ad: connections.resolve(ad, store, SQLITE_DS), ping=ping, record=defter(store)
        )
        app = create_app(
            open_session(
                dataset=SQLITE_DS,
                llm="fake",
                connections=store,
                audit_path=root / "logs" / "audit.jsonl",
                ask_log=root / "logs" / "asks.jsonl",
            ),
            saved_path=root / "bilgin.db",
            static_dir=root / "static",
            users=users,
            connections=store,
            dbstatus=bekci,
        )
        app.state.conn_connect = Baglayici()
        yield SimpleNamespace(
            root=root, app=app, store=store, ping=ping, bekci=bekci,
            baglayici=app.state.conn_connect, runs=runs,
        )
    finally:
        mp.undo()


# ------------------------------------------------------------------ yardımcı kapılar


def girisli(app, username: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": username, "password": PAROLA})
    assert response.status_code == 200, f"{username} giriş yapamadı: {response.status_code}"
    return client


def sor(client: TestClient):
    """Kümenin altın sorusu: sahte model duyduğu anda kendi SQL'ini yollar, yani koşum yürür."""
    line = next(item for item in datasets.load_dataset(ERP).golden() if item["id"] == "Q01")
    return client.post("/api/ask", json={"question": line["question"]})


def saglica(bekci: DbStatus, ping: Ping, saglam: bool) -> str:
    """Noktayı elle yürüt: bekçinin kendi yoklaması, iş parçacığının zamanı beklenmeden."""
    ping.saglam = saglam
    return bekci.check_now(ERP)["state"]


# ------------------------------------------------------------------ kayıt ve geçiş


def test_the_saved_read_only_connection_moves_the_executor(world):
    admin = girisli(world.app, ADMIN)

    saved = admin.put(f"/api/connections/{ERP}", json=GOVDE)
    switched = admin.post("/api/datasets/active", json={"name": ERP})
    answer = sor(admin)

    assert saved.status_code == 200, saved.text
    assert saved.json()["guard"]["ok"] is True, "salt okunur giriş yoklamayı geçmedi"
    assert saved.json()["connection"]["source"] == "stored"
    assert switched.status_code == 200 and switched.json()["active"] == ERP
    assert answer.status_code == 200 and answer.json()["status"] == "answered", answer.text

    assert world.runs, "sorgu sunucuya hiç gitmedi"
    for call in world.runs:
        assert "SERVER=10.0.0.5;" in call["conn_str"]
        assert f"PWD={GIZLI};" in call["conn_str"]
        # ReadOnly yemini bağlanırken eklenir (_mssql._read_only): yürütücü dizeyi onsuz taşır.
        assert "applicationintent" not in call["conn_str"].lower()
    # parolayı yürütücü kadar yoklamanın bağacı da görür; cevabın hiçbiri görmez (aşağıda)
    assert f"PWD={GIZLI};" in world.baglayici.calls[0]


# ------------------------------------------------------------------ sağlığın üç hali


def test_the_health_dot_follows_the_checker_ok_down_and_back(world):
    admin, user = girisli(world.app, ADMIN), girisli(world.app, USER)

    assert saglica(world.bekci, world.ping, True) == "ok"
    blok = user.get("/api/health").json()["db"]
    assert blok["state"] == "ok" and blok["message"] is None
    assert "message_admin" not in blok and "connections_url" not in blok, "kullanıcı admin değil"

    assert saglica(world.bekci, world.ping, False) == "down"
    blok = user.get("/api/health").json()["db"]
    assert blok["state"] == "down" and blok["message"] == DOWN_MESSAGE
    assert "message_admin" not in blok, "sürücünün cümlesi yalnız yöneticinin 'neden'idir"

    yonetici = admin.get("/api/health").json()["db"]
    assert yonetici["state"] == "down" and yonetici["message"] == DOWN_MESSAGE
    assert yonetici["connections_url"] == CONNECTIONS_URL
    assert GIZLI not in yonetici["message_admin"] and "PWD=***" in yonetici["message_admin"]
    satir = world.store.public(ERP)
    assert satir["last_error"] and GIZLI not in satir["last_error"]
    assert satir["last_ok_at"], "sağlam yoklamanın damgası arızayla silinmez"

    assert saglica(world.bekci, world.ping, True) == "ok"
    assert user.get("/api/health").json()["db"]["message"] is None
    satir = world.store.public(ERP)
    assert satir["last_error"] is None and satir["last_ok_at"]


# ------------------------------------------------------------------ düşmüş sunucuda soru


def test_a_question_while_the_database_is_down_never_reaches_the_server(world):
    user = girisli(world.app, USER)
    assert saglica(world.bekci, world.ping, False) == "down"
    kosan = len(world.runs)

    cevap = sor(user).json()

    assert cevap["status"] == "failed"
    assert cevap["error"] == {"kind": "db_down", "message": DB_DOWN_MESSAGE}
    assert cevap["answer_text"] == DB_DOWN_MESSAGE
    assert cevap["sql"] == "" and cevap["rows"] == [] and cevap["steps"] == []
    assert len(world.runs) == kosan, "cevap üretmeyen soru sunucuya sorgu gönderdi"

    assert saglica(world.bekci, world.ping, True) == "ok"
    assert sor(user).json()["status"] == "answered"
    assert len(world.runs) > kosan, "yukarıdaki yokluk ölçümü boş değil"


# ------------------------------------------------------------------ ortam değişkeni kazanır


def test_the_datasets_own_variable_overrides_the_stored_row(world, monkeypatch):
    monkeypatch.setenv(config.CONN_ENV_PREFIX + ERP.upper(), KENDI)
    admin = girisli(world.app, ADMIN)

    satir = admin.get(f"/api/connections/{ERP}").json()
    assert satir["source"] == "env_dataset" and satir["read_only_form"] is True

    refused = admin.put(f"/api/connections/{ERP}", json=GOVDE)
    assert refused.status_code == 409 and refused.json()["detail"] == ENV_SOURCE

    assert admin.post("/api/datasets/active", json={"name": ERP}).status_code == 200
    kosan = len(world.runs)
    assert sor(admin).json()["status"] == "answered"

    assert len(world.runs) > kosan
    for call in world.runs[kosan:]:
        assert call["conn_str"] == KENDI, "yürütücü kayıtlı satırın dizesinde kaldı"
        assert GIZLI not in call["conn_str"]


# ------------------------------------------------------------------ sırrın çıkmaması


def test_the_secret_appears_in_no_response(world):
    admin, user = girisli(world.app, ADMIN), girisli(world.app, USER)
    # arıza bir kez yaşansın: sürücünün parolayı geri yazdığı cümle cevaplardan birine sızabilir
    saglica(world.bekci, world.ping, False)
    saglica(world.bekci, world.ping, True)

    cevaplar = [
        admin.put(f"/api/connections/{ERP}", json=GOVDE),
        admin.get("/api/connections"),
        admin.get(f"/api/connections/{ERP}"),
        admin.post(f"/api/connections/{ERP}/test", json=GOVDE),
        admin.post(f"/api/connections/{ERP}/test", json={**GOVDE, "password": ""}),
        admin.get("/api/health"),
        user.get("/api/health"),
        sor(user),
        admin.get("/api/connections"),
    ]
    for cevap in cevaplar:
        assert cevap.status_code == 200, cevap.text
        assert GIZLI not in cevap.text, cevap.text[:200]
        assert "PWD=" not in cevap.text and "DRIVER=" not in cevap.text

    depo = json.dumps(world.store.public(ERP), ensure_ascii=False)
    assert GIZLI not in depo and "PWD=" not in depo, "satırın kendisi de sırrı taşımaz"
    assert world.store.secret(ERP) == GIZLI, "sır yerinde: yürütücü onu bir kez daha kurar"
