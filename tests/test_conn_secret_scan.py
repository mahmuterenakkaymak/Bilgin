# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T340: sözleşme - parola sunucudan çıkmaz (brief §4, PLAN R7-22..R7-25).

Burada ölçülen tek şey: sürücü parolayı bağlanamadığı her satırda geri yazar, biz de o satırı
nereye koyduğumuzu biliyoruz. Dünya gerçektir - gerçek ``create_app``, gerçek ``ConnectionStore``
(DPAPI ile), gerçek ``DbStatus``, gerçek yürütücü - canlı SQL Server yoktur: üç kapının bağacı
dışarıdan gelir ve hepsi aynı cümleyi verir, ``PWD=<parola>`` yineliyor. Sonra o parolanın
gerçekten dolaştığı her yer taranır: cevap gövdeleri, soru ve denetim günlüğü, tmp altındaki
``logs/``, yakalanan stdout/stderr ve uygulama veritabanının ``secret_blob`` dışındaki metin
sütunları. Beklenti sıfır vuruş.

Parola kutusu DPAPI istediğinden Windows dışında koşmaz; kabuktaki her bağlantı değişkeni
silinir, yoksa geliştiricide ambiyans duran ``NL2SQL_MSSQL_CONN`` kümenin yerini alır (R7-29).
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pyodbc
import pytest
from fastapi.testclient import TestClient

from nl2sql import config, datasets
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.engine import connections
from nl2sql.engine.connections import ConnectionStore
from nl2sql.engine.dbstatus import DOWN_MESSAGE, DbStatus
from nl2sql.web.app import create_app

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="parola kutusu (DPAPI) yalnız Windows'ta vardır"
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
ERP = "erp_live"
GIZLI = "Bilgin!2026erp"
PAROLA = "Giris2026!parola"
ADMIN, USER = "yonetici", "kullanici"

# Sürücünün bağlanamama cümlesi: parolayı olduğu gibi geri yazan hâlin kendisi (brief §4).
SURUCU = (
    "[28001] [Microsoft][ODBC Driver 18 for SQL Server]TCP Provider: Zaman aşımı aşıldı. "
    f"Login failed for user 'bilgin_ro'; PWD={GIZLI}; SERVER=10.0.0.5,1433"
)
GOVDE = {
    "server": "10.0.0.5",
    "database": "DNAEGITIM",
    "auth": "sql",
    "username": "bilgin_ro",
    "password": GIZLI,
    "options": {"encrypt": True, "trust_server_certificate": True, "port": None, "driver": ""},
}


class Baglayici:
    """Yoklamanın sahte bağacı: ``hata`` verilirse bağlantı hiç kurulamaz, verilmezse salt
    okunur bir girişi yanıtlar - her güç 0, her tablo okunur. Hangi bağlantı dizesiyle
    çağrıldığı ``calls``da durur: parolanın sunucuya gerçekten gittiği oradan okunur."""

    def __init__(self, hata: str | None = None) -> None:
        self.hata, self.calls = hata, []

    def __call__(self, conn_str: str):
        self.calls.append(conn_str)
        if self.hata:
            raise RuntimeError(self.hata)
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

    def __init__(self, saglam: bool = True) -> None:
        self.saglam = saglam

    def __call__(self, conn_str: str, timeout=None) -> None:
        if not self.saglam:
            raise RuntimeError(SURUCU)


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
    """Modülün dünyası bir kez: SQL Server ilan eden bir küme, gerçek depo, yönetici ve kullanıcı."""
    root = tmp_path_factory.mktemp("secret")
    copy_dataset(root / "datasets" / ERP, display_name="ERP Canlı (Sunucu)", connection="mssql")
    patch = pytest.MonkeyPatch()
    patch.setattr(config, "ROOT", root)
    patch.setenv("NL2SQL_DATASETS_DIR", str(root / "datasets"))
    patch.setenv("NL2SQL_REAL_DATASETS_DIR", str(root / "real_datasets"))
    patch.delenv(connections.CONN_ENV, raising=False)
    patch.delenv("NL2SQL_BACKEND", raising=False)
    for name in [n for n in os.environ if n.startswith(config.CONN_ENV_PREFIX)]:
        patch.delenv(name, raising=False)
    try:
        users = UserStore(root / "bilgin.db")
        users.add_user(ADMIN, PAROLA, "admin")
        users.add_user(USER, PAROLA, "user")
        assert cli.build_database(dataset=ERP) == 0
        store = ConnectionStore(root / "bilgin.db")
        ping = Ping()
        bekci = DbStatus(lambda ad: connections.resolve(ad, store, ERP), ping=ping)
        app = create_app(
            open_session(
                dataset=ERP,
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
        yield SimpleNamespace(root=root, app=app, store=store, ping=ping, bekci=bekci)
    finally:
        patch.undo()


def girisli(app, username: str) -> TestClient:
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": username, "password": PAROLA})
    assert response.status_code == 200, f"{username} giriş yapamadı: {response.status_code}"
    return client


def sorusu() -> str:
    """Kümenin altın sorusu: sahte model bunu duyduğunda kendi SQL'ini yollar, yani koşum yürür."""
    line = next(item for item in datasets.load_dataset(ERP).golden() if item["id"] == "Q01")
    return line["question"]


class Baglac:
    """Yürütücünün sahte bağacı: ``ilk`` bağlantıya kadar sorguyu yanıtlar, sonra sürücünün
    cümlesiyle düşer. Varsayılan iki: ajanın kendi sorgusu ve gönderdiği SQL'in yoklaması
    yürür, üçüncü bağlantı cevabın arayüz yürüyüşüdür - yani cümle cevabın gittiği her yere
    de gider: ekrana, payload'a ve konuşmanın satırına (diskte)."""

    def __init__(self, ilk: int = 2) -> None:
        self.ilk = ilk

    def __call__(self, conn_str, *args, **kwargs):
        if self.ilk > 0:
            self.ilk -= 1
            return Sunucu()
        raise pyodbc.Error(SURUCU)


class Sunucu:
    """Tek satırlık bir sonucu yanıtlayan sözde pyodbc bağlantısı."""

    timeout = 0

    def cursor(self) -> "Imlec":
        return Imlec()

    def close(self) -> None:
        pass


class Imlec:
    description = [("CIRO",)]

    def execute(self, sql) -> "Imlec":
        return self

    def fetchmany(self, n) -> list[tuple]:
        return [(1234.56,)][:n]


def metinler(root: Path) -> list[tuple[str, str]]:
    """tmp altındaki ``logs/`` dosyaları: soru günlüğü ve denetim günlüğü de burada."""
    found = []
    for path in sorted((root / "logs").rglob("*")):
        if path.is_file():
            found.append((str(path.relative_to(root)), path.read_text(encoding="utf-8")))
    return found


def veritabani_metinleri(path: Path) -> list[tuple[str, str]]:
    """Uygulama veritabanının metin değerleri; ``secret_blob`` taranmaz, sır zaten oradadır."""
    conn = sqlite3.connect(path)
    try:
        found = []
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for table in tables:
            columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')]
            for column in columns:
                if column == "secret_blob":
                    continue
                rows = conn.execute(f'SELECT "{column}" FROM "{table}"').fetchall()
                found += [
                    (f"{table}.{column}", value)
                    for (value,) in rows
                    if isinstance(value, str)
                ]
        return found
    finally:
        conn.close()


def test_the_password_never_leaves_the_server(world, monkeypatch, capsys):
    admin, user = girisli(world.app, ADMIN), girisli(world.app, USER)
    cevaplar = []

    def kaydet(ad, cevap):
        cevaplar.append((ad, cevap))
        return cevap

    # 1) Kayıt: sunucu bu anda cevap veriyor ve yoklama salt okunur girişi geçiyor.
    kaydet("PUT kayıt", admin.put(f"/api/connections/{ERP}", json=GOVDE))
    assert f"PWD={GIZLI};" in world.app.state.conn_connect.calls[0], "parola sunucuya gitmedi"

    # 2) Sunucu sonra reddediyor: yoklama, bekçi ve yürütücü aynı cümleyi veriyor.
    world.app.state.conn_connect = Baglayici(hata=SURUCU)
    world.ping.saglam = False
    world.bekci.check_now(ERP)  # arka plan turunun yaptığı yoklamanın kendisi

    kaydet("PUT red", admin.put(f"/api/connections/{ERP}", json=GOVDE))
    kaydet("POST test", admin.post(f"/api/connections/{ERP}/test", json=GOVDE))
    kaydet("GET liste", admin.get("/api/connections"))
    kaydet("GET satır", admin.get(f"/api/connections/{ERP}"))
    saglik = {
        rol: kaydet(f"GET sağlık {rol}", kim.get("/api/health"))
        for rol, kim in (("yönetici", admin), ("kullanici", user))
    }
    kaydet("POST soru (düşük veritabanı)", admin.post("/api/ask", json={"question": sorusu()}))

    assert [cevap.status_code for _, cevap in cevaplar] == [200, 409, 200, 200, 200, 200, 200, 200]
    assert saglik["yönetici"].json()["db"]["message"] == DOWN_MESSAGE
    assert saglik["yönetici"].json()["db"]["message_admin"], "yönetici sürücünün cümlesini okur"
    assert "message_admin" not in saglik["kullanici"].json()["db"]

    # 3) Bekçi sağ, ajanın sorgusu da yürüyor, ama cevabın kendi yürüyüşü düşüyor: sürücünün
    # cümlesi artık bir hata mesajı ve cevapla birlikte konuşmanın satırına da yazılıyor.
    world.ping.saglam = True
    world.bekci.check_now(ERP)
    monkeypatch.setattr(pyodbc, "connect", Baglac())
    dusuk = kaydet("POST soru (düşük sorgu)", admin.post("/api/ask", json={"question": sorusu()}))
    assert dusuk.json()["error"]["kind"] == "exec:sql"

    yerler = (
        [(ad, cevap.text) for ad, cevap in cevaplar]
        + metinler(world.root)
        + veritabani_metinleri(world.root / "bilgin.db")
        + [("stdout", capsys.readouterr().out), ("stderr", capsys.readouterr().err)]
    )
    assert [ad for ad, metin in yerler if GIZLI in metin] == []
    # Sır iş başındaydı: tarama boş bir dünya üzerinde koşmuyor, sürücünün cümlesi elden geçmiş hâlde orada.
    assert "PWD=***" in dusuk.text, "sürücünün cümlesi hiç görünmedi"
