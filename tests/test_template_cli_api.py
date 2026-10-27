"""T417: şablonun indirme ve komut yolu (PLAN R8-12).

Şablon iki kapıdan doğar: arayüzün indirdiği ``GET /api/schema-map/template.xlsx`` ve kullanıcının
kendi makinesine yazdığı ``template`` komutu. İkisi de dili sorar - API ``?lang=``ı kişinin tercihinden
üstün tutar, çünkü indirilen dosya o dili taşır; komut ``--lang``ı sorar - ve ikisi de aynı çalışma
kitabını üretir: sayfa adları, başlıklar, açılır listeler ve ``_bilgin``in ``lang`` satırı birlikte
o dile döner. Testler dosyayı geri okuyor: bir şablonun hangi dilde olduğu adından değil içeriğinden
ve okuyucunun onu kusur çıkarmadan okumasından ölçülür.
"""

import io
import shutil
from pathlib import Path

import openpyxl
import pytest
from fastapi.testclient import TestClient

from nl2sql import config, datasets
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.i18n import t
from nl2sql.schema_map import introspect, template, template_import
from nl2sql.schema_map.template import INFO_SHEET
from nl2sql.web.app import create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
PAROLA = "Bilgin2026!erp"
ADMIN, ADMIN_EN = "yonetici", "yonetici_en"
TEMPLATE_URL = "/api/schema-map/template.xlsx"

# Şablonun dili içeriğinden okunur: `_bilgin`in ikinci satırı (R8-12) ve sayfaların kendi adları.
SHEETS = {lang: list(template.LABELS[lang]["sheets"]) for lang in ("tr", "en")}

SKELETON = {
    "tables": [
        {
            "name": "Satis.Fatura",
            "columns": [{"name": "FaturaID", "type": "INT", "nullable": False}],
        }
    ]
}


@pytest.fixture
def project(tmp_path, monkeypatch, capsys):
    """tmp dünyası: iki kök ve mini kümesi - repo ile ``data/`` anılmaz (T251'in dünyası)."""
    (tmp_path / "datasets").mkdir()
    (tmp_path / "real_datasets").mkdir()
    shutil.copytree(FIXTURE_ROOT / "mini", tmp_path / "datasets" / "mini")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(tmp_path / "datasets"))
    monkeypatch.setenv("NL2SQL_REAL_DATASETS_DIR", str(tmp_path / "real_datasets"))
    monkeypatch.setattr(config, "MAP_PREVIEWS_DIR", tmp_path / "map_previews")
    monkeypatch.setattr(config, "MAP_CHANGES_LOG", tmp_path / "logs" / "map_changes.jsonl")
    assert cli.build_database(dataset="mini") == 0
    capsys.readouterr()
    return tmp_path


@pytest.fixture
def logged_in(project):
    """İki yöneticili tek uygulama: birinin arayüz tercihi İngilizce, ötekinin hiç tercihi yok (R8-5)."""
    users = UserStore(project / "app.db")
    users.set_lang(users.add_user(ADMIN_EN, PAROLA, "admin")["id"], "en")
    users.add_user(ADMIN, PAROLA, "admin")
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


@pytest.fixture
def client_en(logged_in):
    return logged_in(ADMIN_EN)


@pytest.fixture
def client(logged_in):
    return logged_in(ADMIN)


def _book(content: bytes):
    return openpyxl.load_workbook(io.BytesIO(content))


def lang_of(content: bytes) -> str:
    """Dosyanın kendi dili: ``_bilgin``in B2 hücresi (R8-12)."""
    book = _book(content)
    try:
        return str(book[INFO_SHEET]["B2"].value)
    finally:
        book.close()


def sheet_names(content: bytes) -> list[str]:
    book = _book(content)
    try:
        return [name for name in book.sheetnames if name != INFO_SHEET]
    finally:
        book.close()


def read_back(project, content: bytes, lang: str) -> dict:
    """İndirilen dosya okunur: dilin kendisi değil, okuyucunun onu kusursuz okuması ölçülür."""
    path = project / "indirilen.xlsx"
    path.write_bytes(content)
    return template_import.read_template(path, lang=lang)


# ------------------------------------------------------------------ indirme


def test_an_english_user_downloads_the_english_template(client_en, project):
    response = client_en.get(TEMPLATE_URL)

    assert response.status_code == 200
    assert response.headers["content-disposition"] == (
        f'attachment; filename="{config.TEMPLATE_FILENAMES["en"]}"'
    )
    assert lang_of(response.content) == "en"
    assert sheet_names(response.content) == SHEETS["en"]
    assert read_back(project, response.content, "en")["errors"] == []


def test_the_lang_query_wins_over_the_users_preference(client_en, client):
    tr = client_en.get(f"{TEMPLATE_URL}?lang=tr")

    assert tr.status_code == 200
    assert tr.headers["content-disposition"] == (
        f'attachment; filename="{config.TEMPLATE_FILENAMES["tr"]}"'
    )
    assert lang_of(tr.content) == "tr"
    assert sheet_names(tr.content) == SHEETS["tr"]

    en = client.get(f"{TEMPLATE_URL}?lang=en")

    assert en.status_code == 200
    assert en.headers["content-disposition"] == (
        f'attachment; filename="{config.TEMPLATE_FILENAMES["en"]}"'
    )
    assert lang_of(en.content) == "en"


def test_a_lang_the_program_does_not_speak_is_refused(client_en):
    response = client_en.get(f"{TEMPLATE_URL}?lang=de")

    assert response.status_code == 422
    assert response.json() == {"detail": t("map.bad_lang", "en", value="de")}


def test_the_query_lang_reaches_the_live_skeleton_too(client_en, project, monkeypatch):
    monkeypatch.setenv("NL2SQL_BACKEND", "mssql")
    monkeypatch.setenv("NL2SQL_MSSQL_CONN", "ODBC DRIVER=...")
    monkeypatch.setattr(introspect, "mssql_skeleton", lambda: SKELETON)

    response = client_en.get(f"{TEMPLATE_URL}?from_db=1&lang=en")

    assert response.status_code == 200
    assert lang_of(response.content) == "en"
    read = read_back(project, response.content, "en")
    assert [table["name"] for table in read["schema"]["tables"]] == ["SATIS.FATURA"]
    assert read["errors"] == []


# ------------------------------------------------------------------ komut


@pytest.mark.parametrize("lang", ("tr", "en"))
def test_the_cli_writes_the_template_in_the_asked_language(project, capsys, lang):
    out = project / "sablonlar" / f"sablon-{lang}.xlsx"

    assert cli.main(["template", "--lang", lang, "--out", str(out)]) == 0

    assert out.is_file()
    assert lang_of(out.read_bytes()) == lang
    assert sheet_names(out.read_bytes()) == SHEETS[lang]
    assert template_import.read_template(out, lang=lang)["errors"] == []
    assert str(out) in capsys.readouterr().out


def test_the_dataset_fills_the_skeleton_and_reads_back_clean(project, capsys):
    out = project / "mini-en.xlsx"
    names = [table["name"] for table in datasets.load_dataset("mini").schema()["tables"]]

    assert cli.main(["template", "--lang", "en", "--dataset", "mini", "--out", str(out)]) == 0

    read = template_import.read_template(out, lang="en")
    assert read["errors"] == []
    # Şemanın adı şablona büyük harfle iner (R6-13'in convert'i), o yüzden karşılaştırma katlanarak.
    assert [table["name"] for table in read["schema"]["tables"]] == [name.upper() for name in names]
    assert read["counts"]["tables"] == len(names)
    assert read["counts"]["columns"] > 0
    assert lang_of(out.read_bytes()) == "en"
    assert "mini" in capsys.readouterr().out


def test_the_cli_refuses_a_dataset_that_does_not_exist(project, capsys):
    out = project / "uydurma.xlsx"

    assert cli.main(["template", "--lang", "en", "--dataset", "yok", "--out", str(out)]) == 2

    assert not out.exists()
