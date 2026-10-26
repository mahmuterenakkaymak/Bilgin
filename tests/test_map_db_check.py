"""T282: yüklemenin kontrol raporu canlı veritabanıyla karşılaştırılır (PLAN R6-15, R6-16).

Önizleme bugüne kadar ``validate``i iskeletsiz çağırıyordu, yani şablonun veritabanında olmayan
tablosu hiç sorulmamış oluyordu: 0 hata, ``checked: false``. Buradaki dört ölçüm karşı kapıdan
(gerçek ``create_app``, gerçek ``UserStore``) geçer; tek sahte olan şey sunucunun kendisi -
``mssql_skeleton`` ve ``_db_connection`` monkeypatchlenir, çünkü yoklamanın kendisi
tests/test_introspect'in işi. İddia: şablonun olmayanı hata olup uygulamayı durdurur,
iskeletin fazlası uyarıdır, okunamayan sunucu yüklemeyi düşürmez, sqlite kümesi sunucuyu
hiç sormaz.
"""

import base64
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.schema_map import introspect
from nl2sql.schema_map.template import filled_example_workbook
from nl2sql.web import map_api
from nl2sql.web.app import create_app
from nl2sql.web.map_api import STILL_BROKEN

FIXTURE = Path(__file__).parent / "fixtures" / "datasets" / "mini"
PAROLA = "Bilgin2026!t282"
ADMIN = "yonetici"
NO_DB = "Canlı veritabanı bağlantısı yok; karşılaştırma yapılmadı."
TABLE = "SATIS.FATURA"  # okuyucu adları büyütür; iskelet kendi adını olduğu gibi taşır
CARI = "Satis.Cari"
COLUMNS = ("FaturaID", "FaturaTarihi", "CariKod", "FaturaTipi", "Tutar", "YetkiliAdi", "IcNot")


@pytest.fixture
def client(tmp_path, monkeypatch, capsys):
    """Giriş yapmış yönetici: iki kök tmp'de, mini üretilmiş, uygulama gerçek depo üzerinde."""
    (tmp_path / "datasets").mkdir()
    (tmp_path / "real_datasets").mkdir()
    shutil.copytree(FIXTURE, tmp_path / "datasets" / "mini")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(tmp_path / "datasets"))
    monkeypatch.setenv("NL2SQL_REAL_DATASETS_DIR", str(tmp_path / "real_datasets"))
    monkeypatch.setattr(config, "MAP_PREVIEWS_DIR", tmp_path / "map_previews")
    monkeypatch.setattr(config, "MAP_CHANGES_LOG", tmp_path / "logs" / "map_changes.jsonl")
    assert cli.build_database(dataset="mini") == 0
    capsys.readouterr()

    users = UserStore(tmp_path / "app.db")
    users.add_user(ADMIN, PAROLA, "admin")
    session = open_session(
        dataset="mini",
        llm="fake",
        audit_path=tmp_path / "audit.jsonl",
        ask_log=tmp_path / "asks.jsonl",
    )
    app = create_app(
        session, saved_path=tmp_path / "bilgin.db", static_dir=tmp_path / "static", users=users
    )
    client = TestClient(app)
    assert client.post(
        "/api/auth/login", json={"username": ADMIN, "password": PAROLA}
    ).status_code == 200
    return client


def upload(client, data: bytes, filename: str = "sablon.xlsx"):
    return client.post(
        "/api/schema-map/preview",
        json={"filename": filename, "content_b64": base64.b64encode(data).decode()},
    )


def live(monkeypatch, skeleton=None, raises: str | None = None) -> list:
    """Yoklanabilir bir SQL Server ve onu okuyan sahte bir iskelet: çağrılarının sayısını da sayar."""
    calls: list = []

    def fake() -> dict:
        calls.append(1)
        if raises:
            raise introspect.IntrospectError(raises)
        return skeleton

    monkeypatch.setattr(map_api, "_db_connection", lambda: True)
    monkeypatch.setattr(introspect, "mssql_skeleton", fake)
    return calls


def skeleton(*tables: str) -> dict:
    """Adları verilen tablolar; Fatura'nın kolonları örneğin kolonlarıyla aynı adlar."""
    return {
        "tables": [
            {
                "name": name,
                "columns": [
                    {"name": column, "type": "VARCHAR", "fk": None, "nullable": True}
                    for column in (COLUMNS if name.upper() == TABLE else ("ID",))
                ],
            }
            for name in tables
        ]
    }


def test_a_table_the_database_does_not_have_is_an_error_and_blocks_apply(client, monkeypatch):
    live(monkeypatch, skeleton(CARI))

    body = upload(client, filled_example_workbook("db_eksik", connection="mssql")).json()

    assert body["db_check"]["checked"] is True
    assert body["db_check"]["missing_in_db"] == [TABLE]
    assert f"veritabanında yok: {TABLE}." in " ".join(i["message"] for i in body["errors"])
    refused = client.post("/api/schema-map/apply", json={"preview_id": body["preview_id"]})
    assert (refused.status_code, refused.json()) == (409, {"detail": STILL_BROKEN})
    assert not (Path(config.real_datasets_dir()) / "db_eksik").exists()


def test_a_table_only_the_database_has_is_a_warning(client, monkeypatch):
    live(monkeypatch, skeleton(TABLE, CARI))

    body = upload(client, filled_example_workbook("db_fazla", connection="mssql")).json()

    assert body["errors"] == []
    assert body["db_check"] == {
        "checked": True, "missing_in_db": [], "only_in_db": [CARI], "message": None,
    }
    assert f"yalnız veritabanında: {CARI}." in " ".join(i["message"] for i in body["warnings"])


def test_a_server_that_cannot_be_read_still_reports_the_upload(client, monkeypatch):
    broken = "SQL Server yoklanamadı; NL2SQL_MSSQL_CONN ortam değişkenini ve sunucuyu denetleyin."
    calls = live(monkeypatch, raises=broken)

    response = upload(client, filled_example_workbook("db_kopuk", connection="mssql"))

    assert response.status_code == 200
    body = response.json()
    assert body["errors"] == [], "okunamayan sunucu yüklemenin hatası değil"
    assert body["db_check"] == {
        "checked": False, "missing_in_db": [], "only_in_db": [], "message": broken,
    }
    assert len(calls) == 1, "başarısız yoklama bir daha yinelenmez"


def test_a_sqlite_workbook_never_asks_the_server(client, monkeypatch):
    def never() -> dict:
        raise AssertionError("sqlite kümesi için sunucu yoklanmaz")

    monkeypatch.setattr(map_api, "_db_connection", lambda: True)
    monkeypatch.setattr(introspect, "mssql_skeleton", never)

    body = upload(client, filled_example_workbook("db_sqlite")).json()

    assert body["errors"] == []
    assert body["db_check"] == {
        "checked": False, "missing_in_db": [], "only_in_db": [], "message": NO_DB,
    }
