# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T251: şema haritasının altı yönetici yolu (PLAN R6-16, R6-17).

Ekranın haritadan kümeye giden yolu üç indirmeyle başlar (boş şablon, iskeletle dolu şablon, dolu
örnek), iki yazmayla biter (bekletilen önizleme, küme klasörü + arka plandaki indeks işi). Testler
ikisinin arasına bakıyor: önizleme ``MAP_PREVIEWS_DIR``den başka bir yere dokunmaz, uygulama ise
ad doluysa, rapor hatalıysa ya da önizlemenin süresi geçtinse hiçbir şey yazmaz. İndirmelerin
içeriği de okunarak ölçülür - bir şablonun boş olduğu, bir örneğin sayıları kendi üstünde taşır.
"""

import base64
import io
import json
import shutil
import time
import zipfile
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from bilgin import config, datasets
from bilgin.app.session import open_session
from bilgin.auth.store import UserStore
from bilgin.cli import main as cli
from bilgin.schema_map import introspect, template_import
from bilgin.schema_map.template import filled_example_workbook
from bilgin.web.app import create_app
from bilgin.web.authz import NOT_ADMIN
from bilgin.web.map_api import DB_NOTE, NO_PREVIEW

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
PAROLA = "Bilgin2026!erp"
ADMIN, USER = "yonetici", "kullanici"
SAMPLE = "ornek_fatura"
NO_DB = "Canlı veritabanı bağlantısı yok; karşılaştırma yapılmadı."

# İndirilen iskelet: Tablolar/Kolonlar'ın doldurulması gereken yapı, anlam değil.
SKELETON = {
    "tables": [
        {
            "name": "Satis.Fatura",
            "columns": [
                {"name": "FaturaID", "type": "INT", "fk": None, "nullable": False},
                {
                    "name": "CariKod",
                    "type": "NVARCHAR(20)",
                    "fk": "Satis.Cari.CariKod",
                    "nullable": True,
                },
            ],
        }
    ]
}

# Kapının her yolla sınandığı liste: (istemci metodu, yol, gövde).
ROUTES = [
    ("get", "/api/schema-map/info", None),
    ("get", "/api/schema-map/template.xlsx", None),
    ("get", "/api/schema-map/sample.xlsx", None),
    ("post", "/api/schema-map/preview", {}),
    ("post", "/api/schema-map/apply", {}),
    ("get", "/api/schema-map/status/abc", None),
]


@pytest.fixture
def project(tmp_path, monkeypatch, capsys):
    """tmp dünyası: iki kök, iki günlük ve ``outputs``un ROOT'u - repo ile ``data/`` anılmaz."""
    (tmp_path / "datasets").mkdir()
    (tmp_path / "real_datasets").mkdir()
    shutil.copytree(FIXTURE_ROOT / "mini", tmp_path / "datasets" / "mini")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(tmp_path / "datasets"))
    monkeypatch.setenv("BILGIN_REAL_DATASETS_DIR", str(tmp_path / "real_datasets"))
    monkeypatch.setattr(config, "MAP_PREVIEWS_DIR", tmp_path / "map_previews")
    monkeypatch.setattr(config, "MAP_CHANGES_LOG", tmp_path / "logs" / "map_changes.jsonl")
    assert cli.build_database(dataset="mini") == 0
    capsys.readouterr()
    return tmp_path


@pytest.fixture
def client(project, logged_in):
    return logged_in(ADMIN)


@pytest.fixture
def logged_in(project):
    """Giriş yapmış bir istemci: yönetici de kullanıcı da aynı uygulamada."""
    users = UserStore(project / "app.db")
    users.add_user(ADMIN, PAROLA, "admin")
    users.add_user(USER, PAROLA, "user")
    session = open_session(
        dataset="mini",
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
    )
    app = create_app(
        session, saved_path=project / "bilgin.db", static_dir=project / "static", users=users
    )

    def make(username: str) -> TestClient:
        client = TestClient(app)
        response = client.post(
            "/api/auth/login", json={"username": username, "password": PAROLA}
        )
        assert response.status_code == 200, f"{username} giriş yapamadı: {response.status_code}"
        return client

    return make


def upload(client, data: bytes, filename: str = "sablon.xlsx"):
    return client.post(
        "/api/schema-map/preview",
        json={"filename": filename, "content_b64": base64.b64encode(data).decode()},
    )


def read_back(project, content: bytes) -> dict:
    """İndirilen dosya okunur: bir şablonun boşluğu da dolduğu da içeriğinden ölçülür."""
    path = project / "indirilen.xlsx"
    path.write_bytes(content)
    return template_import.read_template(path)


def wait_for(client, preview_id: str, timeout: float = 120.0) -> dict:
    """Aşama bir daha değişmeyecek an: iş bitti ya da düştü."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = client.get(f"/api/schema-map/status/{preview_id}").json()
        if status["phase"] in ("done", "failed"):
            return status
        time.sleep(0.02)
    raise AssertionError(f"iş bitmedi: {preview_id}")


# ------------------------------------------------------------------ indirmeler


def test_the_blank_template_downloads_and_reads_back_blank(client, project):
    response = client.get("/api/schema-map/template.xlsx")

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{config.TEMPLATE_FILENAME}"'
    )
    assert "spreadsheetml" in response.headers["content-type"]
    assert "x-bilgin-note" not in response.headers

    read = read_back(project, response.content)
    assert read["template"] is True
    assert read["counts"]["tables"] == 0
    assert read["dataset"]["name"] == ""
    assert read["errors"] == []


def test_the_sample_downloads_and_previews_with_no_error(client, project):
    sample = client.get("/api/schema-map/sample.xlsx")

    assert sample.status_code == 200
    assert f'filename="{SAMPLE}.xlsx"' in sample.headers["content-disposition"]

    body = upload(client, sample.content, f"{SAMPLE}.xlsx").json()
    assert body["errors"] == []
    assert body["counts"] == {
        "tables": 1, "columns": 7, "pii": 1, "deny": 1, "references": 0, "rules": 1,
    }
    assert body["dataset"] == {
        "name": SAMPLE,
        "display_name": SAMPLE,
        "connection": "sqlite",
        "default_schema": None,
        "as_of": "2026-10-01",
    }
    assert body["db_check"] == {
        "checked": False, "missing_in_db": [], "only_in_db": [], "message": NO_DB,
    }


def test_a_template_that_is_not_a_workbook_is_refused_by_its_content(client):
    text = upload(client, "TABLO,KOLON\nFatura,ID\n".encode(), "sablon.xlsx")
    assert text.status_code == 422
    assert text.json() == {"detail": "Yalnız .xlsx dosyası yüklenebilir."}

    carrier = io.BytesIO()
    with zipfile.ZipFile(carrier, "w") as book:
        book.writestr("merhaba.txt", "zip ama xlsx değil")
    assert upload(client, carrier.getvalue()).status_code == 422


def test_an_oversize_upload_is_refused_before_it_is_read(client):
    data = filled_example_workbook(SAMPLE) + b"\0" * config.MAP_MAX_BYTES

    response = upload(client, data)

    assert response.status_code == 413
    assert "5 MB" in response.json()["detail"]


# ------------------------------------------------------------------ önizleme


def test_a_preview_writes_the_preview_and_nothing_else(client, project):
    body = upload(client, filled_example_workbook(SAMPLE), "fatura.xlsx").json()

    previews = Path(config.MAP_PREVIEWS_DIR)
    assert [path.name for path in previews.iterdir()] == [f"{body['preview_id']}.json"]
    assert list(Path(config.real_datasets_dir()).iterdir()) == []
    assert not Path(config.MAP_CHANGES_LOG).exists()
    assert [path.name for path in Path(config.datasets_dir()).iterdir()] == ["mini"]

    record = json.loads((previews / f"{body['preview_id']}.json").read_text(encoding="utf-8"))
    assert record["username"] == ADMIN
    assert record["filename"] == "fatura.xlsx"
    assert record["schema"]["tables"][0]["name"] == "SATIS.FATURA"
    assert record["rules"]


def test_a_preview_of_a_workbook_without_a_dataset_row_is_refused(client, project):
    fixture = (Path(__file__).parent / "fixtures" / "map_customer_map.xlsx").read_bytes()

    response = upload(client, fixture, "harita.xlsx")

    assert response.status_code == 422
    assert response.json() == {"detail": "Veri kümesi sayfası yok: Bilgin şablonunu kullanın."}
    assert not Path(config.MAP_PREVIEWS_DIR).exists()


def test_an_expired_or_unknown_preview_id_is_404(client):
    assert client.post("/api/schema-map/apply", json={"preview_id": "abc"}).status_code == 404
    missing = client.get("/api/schema-map/status/abc")

    assert missing.status_code == 404
    assert missing.json() == {"detail": NO_PREVIEW}


# ------------------------------------------------------------------ uygulama


def test_an_apply_creates_the_dataset_and_the_index_job_finishes(client, project):
    preview_id = upload(client, filled_example_workbook(SAMPLE)).json()["preview_id"]

    applied = client.post("/api/schema-map/apply", json={"preview_id": preview_id})

    assert applied.status_code == 200
    assert applied.json()["name"] == SAMPLE
    assert applied.json()["phase"] in ("writing", "indexing")
    assert wait_for(client, preview_id) == {
        "preview_id": preview_id, "name": SAMPLE, "phase": "done", "message": None,
    }

    ds = datasets.load_dataset(SAMPLE)
    assert ds.connection == "sqlite"
    assert (ds.index_dir / "meta.json").is_file()
    assert (Path(config.real_datasets_dir()) / SAMPLE / "readonly_login.sql").is_file()
    line = json.loads(Path(config.MAP_CHANGES_LOG).read_text(encoding="utf-8").splitlines()[-1])
    assert line["username"] == ADMIN and line["name"] == SAMPLE


def test_a_second_preview_of_the_sample_names_the_existing_dataset(client):
    preview_id = upload(client, filled_example_workbook(SAMPLE)).json()["preview_id"]
    assert client.post("/api/schema-map/apply", json={"preview_id": preview_id}).status_code == 200

    again = upload(client, filled_example_workbook(SAMPLE)).json()

    assert again["errors"] == [
        {
            "sheet": "Veri kümesi",
            "row": None,
            "column": "AD",
            "message": f"Bu ad zaten bir veri kümesi: {SAMPLE}.",
        }
    ]
    refused = client.post("/api/schema-map/apply", json={"preview_id": again["preview_id"]})
    assert refused.status_code == 409
    assert refused.json() == {"detail": "Önizlemede düzeltilmemiş hata var; şablonu düzeltip yeniden yükleyin."}


def test_an_apply_never_touches_a_folder_that_already_exists(client):
    preview_id = upload(client, filled_example_workbook(SAMPLE)).json()["preview_id"]
    assert client.post("/api/schema-map/apply", json={"preview_id": preview_id}).status_code == 200
    before = sorted(
        path.name for path in (Path(config.real_datasets_dir()) / SAMPLE).iterdir()
    )

    again = client.post("/api/schema-map/apply", json={"preview_id": preview_id})

    assert again.status_code == 409
    assert again.json() == {"detail": f"Bu ad zaten bir veri kümesi: {SAMPLE}."}
    assert sorted(
        path.name for path in (Path(config.real_datasets_dir()) / SAMPLE).iterdir()
    ) == before


# ------------------------------------------------------------------ veritabanından doldurma


def test_the_button_shows_only_for_a_live_sql_server_connection(client, monkeypatch):
    monkeypatch.delenv("BILGIN_MSSQL_CONN", raising=False)

    assert client.get("/api/schema-map/info").json() == {"db_connection": False}

    monkeypatch.setenv("BILGIN_BACKEND", "mssql")
    assert client.get("/api/schema-map/info").json() == {"db_connection": False}

    monkeypatch.setenv("BILGIN_MSSQL_CONN", "ODBC DRIVER=...")
    assert client.get("/api/schema-map/info").json() == {"db_connection": True}


def test_from_db_fills_the_template_with_the_live_structure(client, project, monkeypatch):
    monkeypatch.setenv("BILGIN_BACKEND", "mssql")
    monkeypatch.setenv("BILGIN_MSSQL_CONN", "ODBC DRIVER=...")
    monkeypatch.setattr(introspect, "mssql_skeleton", lambda: SKELETON)

    response = client.get("/api/schema-map/template.xlsx?from_db=1")

    assert response.status_code == 200
    assert "x-bilgin-note" not in response.headers
    read = read_back(project, response.content)
    assert [table["name"] for table in read["schema"]["tables"]] == ["SATIS.FATURA"]
    assert read["counts"] == {
        "tables": 1, "columns": 2, "pii": 0, "deny": 0, "references": 1, "rules": 0,
    }
    assert read["errors"] == []


def test_a_server_that_cannot_be_read_still_gives_the_blank_template(client, project, monkeypatch):
    monkeypatch.setenv("BILGIN_BACKEND", "mssql")
    monkeypatch.setenv("BILGIN_MSSQL_CONN", "ODBC DRIVER=...")

    def broken() -> dict:
        raise introspect.IntrospectError("VIEW DEFINITION yetkisi yok")

    monkeypatch.setattr(introspect, "mssql_skeleton", broken)

    response = client.get("/api/schema-map/template.xlsx?from_db=1")

    assert response.status_code == 200
    assert unquote(response.headers["x-bilgin-note"]) == DB_NOTE
    assert read_back(project, response.content)["counts"]["tables"] == 0


def test_without_a_connection_string_the_server_is_never_asked_again(client, project, monkeypatch):
    monkeypatch.setenv("BILGIN_BACKEND", "mssql")
    monkeypatch.delenv("BILGIN_MSSQL_CONN", raising=False)

    def never() -> dict:
        raise AssertionError("bağlantı yokken yoklama yapılmaz")

    monkeypatch.setattr(introspect, "mssql_skeleton", never)

    response = client.get("/api/schema-map/template.xlsx?from_db=1")

    assert response.status_code == 200
    assert "x-bilgin-note" not in response.headers
    assert read_back(project, response.content)["counts"]["tables"] == 0


# ------------------------------------------------------------------ kapı


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_every_map_route_belongs_to_an_admin(logged_in, method, path, body):
    client = logged_in(USER)

    response = client.request(method.upper(), path, json=body)

    assert response.status_code == 403, f"{method.upper()} {path} kullanıcıya {response.status_code}"
    assert response.json() == {"detail": NOT_ADMIN}
