"""T411: CLI'nin öteki komutları da çözülen dilde (PLAN R8-5, R8-11).

``ask`` ve ``user *`` T410'da kataloğa geçmişti; burada aynı kural kalan komutlara uygulanıyor:
build-db, build-index, import-map, introspect, diff-map, merge-map, make-login-script ve serve'ın
açılış/reddin satırları ``cli.<komut>.*`` anahtarlarından ``--lang``da gelir. Ölçüt iki parçalı:
İngilizce koşumda çerçevenin hiçbir satırı Türkçe harf taşımaz, Türkçe koşum ise bugünkü halidir.

Veri değerleri çevrilmez - kümenin tablo adı, müşterinin Excel başlığı, modelin cümlesi olduğu gibi
kalır. ``diff-map``ın dolu farkında bastığı bölüm başlıkları ``schema_map/merge`` raporunun kendi
satırlarıdır (diff.md ile aynı metin), o yüzden İngilizce koşum boş fark üzerinden ölçülür.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import openpyxl
import pytest

from nl2sql import config
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.cli.table import format_table
from nl2sql.engine.login_script import DEFAULT_LOGIN
from nl2sql.engine.result import Result
from nl2sql.i18n.detect import TURKISH_LETTERS
from nl2sql.i18n.scan import user_literals
from nl2sql.schema_map import build
from nl2sql.web import app as web_app
from nl2sql.web.datasets_api import ACTIVE_SETTING

PAROLA = "Bilgin2026!erp"
# import-map'ın ASCII haritası: başlıklar sözlükte de İngilizce, yani eşleme kuruluyor ama hiçbir
# satır Türkçe harf taşımıyor - "Türkçe harf yok" ölçütü veri değerine çarpmıyor.
HEADERS = ["TABLE", "FIELD", "TYPE", "DESCRIPTION", "FK", "VALUES", "NULL", "MODULE"]
ROWS = [["TBLA", "CODE", "int", "Card code", "", "", "N", "Stock"]]
# diff-map/merge-map'ın iki tarafı: aynı dosya verildiğinde fark çıkmaz, yani ekran yalnız çerçevedir.
SCHEMA = {"tables": [{"name": "TBLA", "columns": [{"name": "CODE", "type": "int"}]}]}


def turkish(out: str) -> list[str]:
    """Çıktının hâlâ Türkçe harf taşıyan satırları - çerçeve için ölçüt budur."""
    return [line for line in out.splitlines() if any(ch in TURKISH_LETTERS for ch in line)]


@pytest.fixture
def project(tmp_path, monkeypatch):
    """Yollar tmp'ye çevrilir: komutlar varsayılanlarını çağrı anında config'den okur."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(config, "MSSQL_SCRIPT", tmp_path / "test.sql")
    monkeypatch.setattr(config, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(config, "AUDIT_LOG", tmp_path / "audit.jsonl")
    monkeypatch.setenv("NL2SQL_APP_DB", str(tmp_path / "app.db"))
    return tmp_path


def workbook(tmp_path) -> Path:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "COLUMNS"
    sheet.append(HEADERS)
    for item in ROWS:
        sheet.append(item)
    path = tmp_path / "map.xlsx"
    book.save(path)
    return path


def stub_session(monkeypatch) -> None:
    """``serve``ın açılış satırı ölçülür, sunucu ayağa kalkmaz: oturum, kapı ve bekçi hazır."""
    session = SimpleNamespace(dataset=None, profile=None, llm_kind="fake", executor=None)
    monkeypatch.setattr("nl2sql.app.session.open_session", lambda **kwargs: session)
    monkeypatch.setattr(
        web_app,
        "create_app",
        lambda session, **kwargs: SimpleNamespace(state=SimpleNamespace(session=session)),
    )
    monkeypatch.setattr(cli, "_db_status", lambda *args, **kwargs: SimpleNamespace(start=lambda: None))
    monkeypatch.setattr(cli, "run_server", lambda app, host, port: None)


def write_datasets(root: Path, name: str, indexed=()) -> None:
    """``root`` altında tek kümelik bir kök: ``dataset.json``u ve ``indexed``deki indeks imzası."""
    folder = root / "datasets" / name
    folder.mkdir(parents=True)
    (folder / "dataset.json").write_text(
        json.dumps(
            {
                "name": name,
                "as_of": "2026-01-31",
                "builder": "builder.py:build_db",
                "generator": "builder.py:generate",
                "references": "reference.py:REFERENCES",
                "outputs": {"index_dir": f"index/{name}"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    if name in indexed:
        index = root / "index" / name
        index.mkdir(parents=True)
        (index / "meta.json").write_text("{}", encoding="utf-8")


# ------------------------------------------------------------------ build-db


def test_build_db_in_english(project, capsys):
    assert cli.main(["build-db", "--seed", "7", "--lang", "en"]) == 0
    out = capsys.readouterr().out

    assert "Seed: 7" in out and f"Database: {project / 'test.db'}" in out
    assert "T-SQL script:" in out and "Checksum (sha256):" in out
    assert "Tables:" in out and "Schema text (full mode):" in out
    assert turkish(out) == []


def test_build_db_turkish_is_todays(project, capsys):
    assert cli.main(["build-db", "--seed", "7"]) == 0
    out = capsys.readouterr().out

    assert f"Tohum: 7\nVeritabanı: {project / 'test.db'}\n" in out
    assert f"T-SQL betiği: {project / 'test.sql'}\n" in out
    assert "Tablolar: " in out and "şema-yalnız " in out
    assert "Şema metni (full mod): " in out and "Sağlama (sha256):" in out


# ------------------------------------------------------------------ build-index


def test_build_index_in_english(project, capsys):
    assert cli.main(["build-index", "--embed", "fake", "--lang", "en"]) == 0
    out = capsys.readouterr().out

    assert "Schema: " in out and "Rules: " in out and "Documents:" in out
    assert "Signature:" in out and "Time:" in out and f"Index: {project / 'index'}" in out
    assert turkish(out) == []


def test_a_broken_embed_source_is_refused_in_english(project, capsys):
    assert cli.main(["build-index", "--embed", "bozuk", "--lang", "en"]) == 2
    out = capsys.readouterr().out

    assert "Could not read the embedder source: bozuk" in out
    assert "--embed-model" in out and turkish(out) == []


# ------------------------------------------------------------------ import-map


def test_import_map_in_english(project, capsys):
    path = workbook(project)
    assert cli.main(
        [
            "import-map",
            str(path),
            "--llm",
            "fake",
            "--accept",
            "--out",
            str(project / "schema.json"),
            "--lang",
            "en",
        ]
    ) == 0
    out = capsys.readouterr().out

    assert f"File: {path}" in out and "COLUMNS — header row 1" in out
    assert "table_name" in out and "Mapping: " in out
    assert f"Schema written: {project / 'schema.json'} (1 tables, 1 columns, 0 skipped rows)" in out
    assert turkish(out) == []


def test_a_missing_workbook_is_refused_in_english(project, capsys):
    assert cli.main(["import-map", str(project / "yok.xlsx"), "--llm", "fake", "--lang", "en"]) == 2
    out = capsys.readouterr().out

    assert "Excel file not found: " in out and turkish(out) == []


# ------------------------------------------------------------------ introspect


def test_introspect_in_english(project, capsys):
    build.build_db(config.SEED, project / "test.db", project / "test.sql")
    assert cli.main(["introspect", "--out", str(project / "skel.json"), "--lang", "en"]) == 0
    out = capsys.readouterr().out

    assert f"-> {project / 'skel.json'}" in out and "Skeleton: " in out
    assert " tables, " in out and " columns -> " in out and turkish(out) == []


# ------------------------------------------------------------------ diff-map / merge-map


def test_diff_map_in_english(project, capsys):
    schema = project / "schema.json"
    schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
    assert (
        cli.diff_map(
            schema,
            db_schema=schema,
            json_out=project / "diff.json",
            md_out=project / "diff.md",
            lang="en",
        )
        == 0
    )
    out = capsys.readouterr().out

    assert f"Excel: {schema}" in out and f"Database: {schema}" in out
    assert "No differences." in out and "JSON:" in out and "Markdown:" in out
    assert turkish(out) == []


def test_merge_map_in_english(project, capsys):
    schema = project / "schema.json"
    schema.write_text(json.dumps(SCHEMA), encoding="utf-8")
    assert (
        cli.merge_map(schema, db_schema=schema, out=project / "merged.json", lang="en") == 0
    )
    out = capsys.readouterr().out

    assert f"Merged schema written: {project / 'merged.json'} (1 tables, 1 columns)" in out
    assert turkish(out) == []


# ------------------------------------------------------------------ make-login-script


def test_make_login_script_in_english(project, capsys):
    assert cli.make_login_script(out=project / "login.sql", lang="en") == 0
    out = capsys.readouterr().out

    assert f"Login: {DEFAULT_LOGIN}" in out and "Allowlist: " in out
    assert "PII columns denied: " in out and f"Script: {project / 'login.sql'}" in out
    assert turkish(out) == []


def test_make_login_script_turkish_is_todays(project, capsys):
    assert cli.make_login_script(out=project / "login.sql") == 0
    out = capsys.readouterr().out

    assert f"Giriş: {DEFAULT_LOGIN}\n" in out
    assert "Allowlist: " in out and " tablo\n" in out
    assert "PII kolonu reddedildi: " in out
    assert f"Betik: {project / 'login.sql'}" in out


# ------------------------------------------------------------------ serve


def test_the_serve_line_in_english(project, monkeypatch, capsys):
    stub_session(monkeypatch)
    UserStore(project / "app.db").add_user("admin", PAROLA, "admin")

    assert cli.serve(llm_kind="fake", dataset="mini", lang="en") == 0
    out = capsys.readouterr().out

    assert f"Bilgin: http://{config.SERVE_HOST}:8777  (dataset synthetic_erp, model fake, llm fake)" in out
    assert turkish(out) == []


def test_the_serve_refusals_in_english(project, monkeypatch, capsys):
    assert cli.serve(db_probe_file=project / "probe.json", llm_kind="openai", lang="en") == 2
    assert "--db-probe-file works only with --llm fake" in capsys.readouterr().out

    stub_session(monkeypatch)
    UserStore(project / "app.db").add_user("admin", PAROLA, "admin")
    assert cli.serve(host="10.0.0.5", llm_kind="fake", dataset="mini", lang="en") == 2
    out = capsys.readouterr().out
    assert "Bilgin runs on 127.0.0.1 only" in out and turkish(out) == []

    monkeypatch.setenv("NL2SQL_APP_DB", str(project / "bos.db"))
    monkeypatch.delenv(config.DEV_ADMIN_ENV, raising=False)
    assert cli.serve(llm_kind="fake", dataset="mini", lang="en") == 2
    out = capsys.readouterr().out
    assert "No users yet: create an admin first" in out and turkish(out) == []


def test_the_stored_dataset_note_in_english(project, monkeypatch, capsys):
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(project / "datasets"))
    monkeypatch.setenv("NL2SQL_REAL_DATASETS_DIR", str(project / "real"))
    write_datasets(project, cli.DEMO_DATASET, indexed=[cli.DEMO_DATASET])
    UserStore(project / "app.db").set_setting(ACTIVE_SETTING, "kaybolmus")

    assert cli._served_dataset("en") == cli.DEMO_DATASET
    out = capsys.readouterr().out

    assert "Note: the stored dataset kaybolmus no longer loads; serving the default" in out
    assert turkish(out) == []


def test_the_stored_dataset_note_stays_turkish_by_default(project, monkeypatch, capsys):
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(project / "datasets"))
    monkeypatch.setenv("NL2SQL_REAL_DATASETS_DIR", str(project / "real"))
    write_datasets(project, cli.DEMO_DATASET, indexed=[cli.DEMO_DATASET])
    UserStore(project / "app.db").set_setting(ACTIVE_SETTING, "kaybolmus")

    assert cli._served_dataset() == cli.DEMO_DATASET
    assert cli.STORED_LOST.format(name="kaybolmus", default=cli.DEMO_DATASET) in (
        capsys.readouterr().out
    )


# ------------------------------------------------------------------ tablo başlıkları


def test_the_table_notices_follow_the_lang():
    empty = Result(columns=["KOD"], rows=[], row_count=0)
    assert format_table(empty) == "Sonuç boş (0 satır)"
    assert format_table(empty, "en") == "Empty result (0 rows)"

    cut = Result(columns=["KOD"], rows=[("A001",)], row_count=312, truncated=True)
    assert format_table(cut).endswith("İlk 1 satır gösteriliyor (toplam 312)")
    assert format_table(cut, "en").endswith("Showing the first 1 rows (of 312 total)")


def test_table_has_no_turkish_literal_left():
    assert user_literals("nl2sql/cli/table.py") == []
