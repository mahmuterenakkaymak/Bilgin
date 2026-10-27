"""T406: veri kümesi ve harita API'lerinin cümleleri isteğin dilinde (PLAN R8-5).

Dünya test_web_map_api ve test_web_datasets_api ile aynı gerçeklikte - kopya, import değil:
tmp köklere kopyalanmış mini, yarım kalmış bir apply'ın izi olan ``semasiz``, SQL Server ilan
edilmiş bir kopya, sahte model ve tmp günlükler. Dil tek bir başlıkla seçilir, ``Accept-Language``:
aynı dünyanın reddi iki dilde de okunur. tr tarafı 2026-10-27'de ekranda okunan cümleye sabittir -
katalog bir gün bozulursa buradan anlaşılır; İngilizce taraf kataloğun kendi satırıdır.
"""

import base64
import json
import shutil
import time
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.i18n import t
from nl2sql.i18n.scan import user_literals
from nl2sql.schema_map import introspect
from nl2sql.schema_map import onboard as onboard_module
from nl2sql.schema_map import rules_edit as rules_edit_module
from nl2sql.schema_map.template import filled_example_workbook
from nl2sql.web import datasets_api as datasets_api_module
from nl2sql.web import map_api as map_api_module
from nl2sql.web.app import create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
PAROLA = "Bilgin2026!erp"
ADMIN = "yonetici"
SAMPLE = "ornek_fatura"
MSSQL = "mini_sql"
# Yarım kalan bir apply'ın izi: tanımı okunuyor ama şeması yok.
SCHEMALESS = "semasiz"
DOC = {
    "name": SCHEMALESS,
    "as_of": "2026-09-30",
    "builder": "builder.py:build_db",
    "generator": "builder.py:generate",
    "references": "builder.py:REFERENCES",
}
# ``datasets.unknown``ın saydığı adlar: iki kökteki klasörler, ad sırasıyla.
KNOWN = f"mini, {MSSQL}, {SCHEMALESS}"

# 2026-10-27'de ekranda okunan cümleler: Türkçe yolun kataloğa taşınırken değişmediğinin ölçütü.
TODAY = {
    "datasets.empty_name": "Veri kümesi adı boş.",
    "datasets.unknown": "Bilinmeyen veri kümesi: {name} (bilinenler: {known})",
    "datasets.broken": "Veri kümesi okunamıyor: {name}. Klasördeki bir dosya eksik ya da bozuk.",
    "datasets.index_unreadable": "Kümenin şeması okunamadığı için indeksi denetlenemedi.",
    "datasets.login_notice": (
        "Bu küme SQL Server'a bağlı: salt okunur girişi kurun ve sunucuyu {env} ile başlatın."
    ),
    "map.not_xlsx": "Yalnız .xlsx dosyası yüklenebilir.",
    "map.too_large": "Dosya çok büyük; en fazla {mb} MB yüklenebilir.",
    "map.no_preview": "Önizleme bulunamadı ya da süresi doldu.",
    "map.still_broken": "Önizlemede düzeltilmemiş hata var; şablonu düzeltip yeniden yükleyin.",
    "map.name_taken": "Bu ad zaten bir veri kümesi: {name}.",
    "map.db_note": "Salt okunur giriş tablo bilgisini okuyamadı (VIEW DEFINITION); boş şablon verildi.",
    "onboard.index_failed": "İndeks kurulamadı: {name} (build-index {code} ile döndü).",
}

REJECTIONS = (
    "empty_name",
    "unknown_dataset",
    "broken_dataset",
    "index_unreadable",
    "not_xlsx",
    "too_large",
    "no_preview_apply",
    "no_preview_status",
    "still_broken",
    "name_taken",
)


def copy_dataset(root: Path, name: str, **over) -> Path:
    """Mini kümesinin tmp kopyası: ad, çıktı yolları ve söylenen birkaç alan değişir."""
    folder = root / name
    shutil.copytree(FIXTURE_ROOT / "mini", folder)
    meta = json.loads((folder / "dataset.json").read_text(encoding="utf-8"))
    meta.update({"name": name, **over})
    meta["outputs"] = {
        key: value.replace("mini", name) for key, value in (meta.get("outputs") or {}).items()
    }
    (folder / "dataset.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return folder


@pytest.fixture(autouse=True)
def failing_index(monkeypatch):
    """İndeks işi bu testlerin konusu değil: ``build-index`` hemen 1 döner, iş hemen düşer."""
    monkeypatch.setattr(cli, "build_index", lambda embed, dataset=None: 1)


@pytest.fixture
def project(tmp_path, monkeypatch, capsys):
    """İki kök: ölçülmüş mini, SQL Server ilan edilmiş kopyası, ``real_datasets``te yarım bir klasör."""
    root, real = tmp_path / "datasets", tmp_path / "real_datasets"
    copy_dataset(root, "mini")
    copy_dataset(root, MSSQL, display_name="Mini (Sunucu)", connection="mssql")
    (real / SCHEMALESS).mkdir(parents=True)
    (real / SCHEMALESS / "dataset.json").write_text(
        json.dumps(DOC, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(root))
    monkeypatch.setenv("NL2SQL_REAL_DATASETS_DIR", str(real))
    monkeypatch.setattr(config, "MAP_PREVIEWS_DIR", tmp_path / "map_previews")
    monkeypatch.setattr(config, "MAP_CHANGES_LOG", tmp_path / "logs" / "map_changes.jsonl")
    assert cli.build_database(dataset="mini") == 0
    assert cli.build_database(dataset=MSSQL) == 0
    capsys.readouterr()
    return tmp_path


@pytest.fixture
def app(project, capsys):
    users = UserStore(project / "app.db")
    users.add_user(ADMIN, PAROLA, "admin")
    session = open_session(
        dataset="mini",
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
    )
    capsys.readouterr()
    return create_app(
        session, saved_path=project / "bilgin.db", static_dir=project / "static", users=users
    )


def client(app, lang: str) -> TestClient:
    """Başlığı sabitlenmiş yönetici istemcisi: kümelerin ve haritanın yolları yönetici ister (R6-5)."""
    made = TestClient(app)
    made.headers["accept-language"] = lang
    granted = made.post("/api/auth/login", json={"username": ADMIN, "password": PAROLA})
    assert granted.status_code == 200, f"{ADMIN} giriş yapamadı: {granted.status_code}"
    return made


def expected(key: str, lang: str, **params) -> str:
    """Türkçe bugün okunan cümle, İngilizce kataloğun kendi satırı (R8-5)."""
    return TODAY[key].format(**params) if lang == "tr" else t(key, lang, **params)


def upload(made: TestClient, data: bytes, filename: str = "sablon.xlsx"):
    return made.post(
        "/api/schema-map/preview",
        json={"filename": filename, "content_b64": base64.b64encode(data).decode()},
    )


def apply_sample(made: TestClient) -> str:
    """Örnek şablonun önizlenip uygulanmış hali: o andan itibaren adı bir veri kümesidir."""
    preview_id = upload(made, filled_example_workbook(SAMPLE)).json()["preview_id"]
    assert made.post("/api/schema-map/apply", json={"preview_id": preview_id}).status_code == 200
    return preview_id


def wait_for_job(made: TestClient, preview_id: str, timeout: float = 60.0) -> dict:
    """Aşama bir daha değişmeyecek an: iş bitti ya da düştü."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = made.get(f"/api/schema-map/status/{preview_id}").json()
        if status["phase"] in ("done", "failed"):
            return status
        time.sleep(0.02)
    raise AssertionError(f"iş bitmedi: {preview_id}")


def detail_of(response, status: int) -> str:
    """Reddin cümlesi: durum da ölçülmüş olsun diye önce ona bakılır, sonra detay okunur."""
    assert response.status_code == status, f"{response.status_code}: {response.text}"
    return response.json()["detail"]


def reject(name: str, lang: str, made: TestClient) -> tuple[str, str]:
    """Adı geçen reddi koşar: (beklenen cümle, cevabın okunan cümlesi)."""
    if name == "empty_name":
        response = made.post("/api/datasets/active", json={"name": "  "})
        return expected("datasets.empty_name", lang), detail_of(response, 400)
    if name == "unknown_dataset":
        response = made.post("/api/datasets/active", json={"name": "olmayan"})
        return (
            expected("datasets.unknown", lang, name="olmayan", known=KNOWN),
            detail_of(response, 404),
        )
    if name == "broken_dataset":
        response = made.get(f"/api/datasets/{SCHEMALESS}/login-script.sql")
        return expected("datasets.broken", lang, name=SCHEMALESS), detail_of(response, 409)
    if name == "index_unreadable":
        body = made.get("/api/datasets")
        assert body.status_code == 200, body.text
        row = next(item for item in body.json()["datasets"] if item["name"] == SCHEMALESS)
        return expected("datasets.index_unreadable", lang), row["index"]["reason"]
    if name == "not_xlsx":
        response = upload(made, "TABLO,KOLON\nFatura,ID\n".encode(), "sablon.xlsx")
        return expected("map.not_xlsx", lang), detail_of(response, 422)
    if name == "too_large":
        data = filled_example_workbook(SAMPLE) + b"\0" * config.MAP_MAX_BYTES
        response = upload(made, data)
        wanted = expected("map.too_large", lang, mb=config.MAP_MAX_BYTES // (1024 * 1024))
        return wanted, detail_of(response, 413)
    if name == "no_preview_apply":
        response = made.post("/api/schema-map/apply", json={"preview_id": "abc"})
        return expected("map.no_preview", lang), detail_of(response, 404)
    if name == "no_preview_status":
        response = made.get("/api/schema-map/status/abc")
        return expected("map.no_preview", lang), detail_of(response, 404)
    if name == "still_broken":
        apply_sample(made)
        # Ad dolunca taze bir önizleme hatayla doğar: uygulama onu değil raporu okur.
        again = upload(made, filled_example_workbook(SAMPLE)).json()
        response = made.post("/api/schema-map/apply", json={"preview_id": again["preview_id"]})
        return expected("map.still_broken", lang), detail_of(response, 409)
    # Aynı rapor ikinci kez koşulursa sırayı rapor değil disk söyler: adı klasörün kendisi dolu sayar.
    preview_id = apply_sample(made)
    response = made.post("/api/schema-map/apply", json={"preview_id": preview_id})
    return expected("map.name_taken", lang, name=SAMPLE), detail_of(response, 409)


@pytest.mark.parametrize("lang", ["tr", "en"])
@pytest.mark.parametrize("name", REJECTIONS)
def test_a_rejection_reads_the_request_language(name, lang, app):
    wanted, detail = reject(name, lang, client(app, lang))

    assert detail == wanted


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_the_notice_of_an_sql_server_switch_names_the_next_step(lang, app):
    response = client(app, lang).post("/api/datasets/active", json={"name": MSSQL})

    assert response.status_code == 200
    assert response.json()["notice"]["env"] == "NL2SQL_MSSQL_CONN"
    assert response.json()["notice"]["message"] == expected(
        "datasets.login_notice", lang, env="NL2SQL_MSSQL_CONN"
    )


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_the_note_of_a_template_the_server_could_not_fill(lang, app, monkeypatch):
    monkeypatch.setenv("NL2SQL_BACKEND", "mssql")
    monkeypatch.setenv("NL2SQL_MSSQL_CONN", "ODBC DRIVER=...")

    def broken() -> dict:
        raise introspect.IntrospectError("VIEW DEFINITION yetkisi yok")

    monkeypatch.setattr(introspect, "mssql_skeleton", broken)

    response = client(app, lang).get("/api/schema-map/template.xlsx?from_db=1")

    assert response.status_code == 200
    assert unquote(response.headers["x-bilgin-note"]) == expected("map.db_note", lang)


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_the_index_job_of_an_apply_keeps_the_language_it_was_born_in(lang, app):
    """İş parçacığının kendi isteği yoktur: cümle, apply'in diliyle doğar, bir daha dönmez (R8-5)."""
    made = client(app, lang)
    preview_id = apply_sample(made)

    status = wait_for_job(made, preview_id)

    assert status["phase"] == "failed"
    assert status["message"] == expected("onboard.index_failed", lang, name=SAMPLE, code=1)


def test_no_turkish_literal_is_left_in_the_four_modules():
    for module in (datasets_api_module, map_api_module, onboard_module, rules_edit_module):
        assert user_literals(Path(module.__file__)) == []
