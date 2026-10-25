"""T231: ``serve`` her zaman oturum ister (PLAN R6-7).

Dünya ``tests/test_web_api.py`` ile aynı - kopya, import değil: gerçek mini küme, sahte model, tmp
yollar. Sunucu ayağa kalkmaz, ``run_server`` yerine geçilir; ``create_app``a giren kullanıcı deposu
ve kurulan kapı oradan okunur. Geliştirme yöneticisinin parolası depoda durmaz, testte ``secrets``
ile üretilir ve hiçbir ekran çıktısında aranır.
"""

import re
import secrets
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.web import app as web_app
from nl2sql.web.app import create_app
from nl2sql.web.authz import NO_SESSION, ROUTE_ROLES

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
PAROLA = "Bilgin2026!erp"
DEV_WARNING = (
    "Geliştirme yöneticisi oluşturuldu: admin - NL2SQL_DEV_ADMIN_PASSWORD ortam değişkeninden; "
    "canlı kurulumda bu değişkeni tanımlamayın."
)
# Matrisin public olmayan satırları: oturumsuz hepsi 401 demek zorunda.
NON_PUBLIC = [(method, path) for (method, path), level in ROUTE_ROLES.items() if level != "public"]


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    monkeypatch.setenv("NL2SQL_APP_DB", str(tmp_path / "app.db"))
    monkeypatch.delenv(config.DEV_ADMIN_ENV, raising=False)
    monkeypatch.setattr(config, "AUDIT_LOG", tmp_path / "audit.jsonl")
    monkeypatch.setattr(config, "ASK_LOG", tmp_path / "asks.jsonl")
    cli.build_database(dataset="mini")
    return tmp_path


def serve(project, capsys, monkeypatch) -> SimpleNamespace:
    """Gerçek ``serve`` bir kez: kapı tmp yollarla kurulur, sunucu açılmaz, ekran döner.

    Aynı testte iki kez çağrılabilir, o yüzden yerinde konan kapı değil asıl ``create_app``
    çağrılır - bir önceki turunki monkeypatch ile hâlâ yerinde durur.
    """
    built: dict = {}

    def stand_in(session, **kwargs):
        built.update(kwargs)
        return create_app(
            session, saved_path=project / "bilgin.db", static_dir=project / "static", **kwargs
        )

    seen: dict = {}
    monkeypatch.setattr(web_app, "create_app", stand_in)
    monkeypatch.setattr(cli, "run_server", lambda app, host, port: seen.update(app=app))
    code = cli.serve(llm_kind="fake", dataset="mini")
    return SimpleNamespace(
        code=code, out=capsys.readouterr().out, app=seen.get("app"), users=built.get("users")
    )


def stored_hash(project) -> str:
    """Karma yalnız dosyada durur; bootstrapün onu yenileyip yenilemediği buradan okunur."""
    conn = sqlite3.connect(project / "app.db")
    try:
        return conn.execute("SELECT password_hash FROM users WHERE username = 'admin'").fetchone()[0]
    finally:
        conn.close()


@pytest.fixture
def served(project, capsys, monkeypatch) -> TestClient:
    """``serve``ın kurduğu kapı: bir yönetici var, ama açılan oturum yok."""
    UserStore(project / "app.db").add_user("admin", PAROLA, "admin")
    return TestClient(serve(project, capsys, monkeypatch).app)


# ------------------------------------------------------------------ kapı deponun üstünde


def test_serve_hands_a_user_store_to_the_app(project, capsys, monkeypatch):
    UserStore(project / "app.db").add_user("admin", PAROLA, "admin")

    run = serve(project, capsys, monkeypatch)

    assert run.code == 0
    assert isinstance(run.users, UserStore), "kapı depoya bağlanmadı, yani hiçbir yol oturum sormaz"
    assert run.users.path == config.app_db_path()
    assert run.app is not None, "run_server çağrılmadı"


@pytest.mark.parametrize("method,path", NON_PUBLIC)
def test_every_non_public_route_needs_a_session(served, method, path):
    response = served.request(method, re.sub(r"\{[^}]+\}", "1", path))

    assert response.status_code == 401
    assert response.json() == {"detail": NO_SESSION}


# ------------------------------------------------------------------ kullanıcı yokken


def test_an_empty_user_table_refuses_to_listen(project, capsys, monkeypatch):
    run = serve(project, capsys, monkeypatch)

    assert run.code == 2
    assert cli.NO_USERS in run.out
    assert run.app is None and run.users is None, "reddedilen koşum ne kapı kurar ne dinler"


# ------------------------------------------------------------------ geliştirme bootstrapü


def test_the_bootstrap_creates_the_admin_and_warns(project, capsys, monkeypatch):
    password = secrets.token_urlsafe(12)
    monkeypatch.setenv(config.DEV_ADMIN_ENV, password)

    run = serve(project, capsys, monkeypatch)

    assert run.code == 0
    assert DEV_WARNING in run.out
    store = UserStore(project / "app.db")
    assert store.get_user("admin")["role"] == "admin"
    store.authenticate("admin", password)
    assert password not in run.out and "scrypt$" not in run.out


def test_the_bootstrap_ignores_the_minimum_password_length(project, capsys, monkeypatch):
    """Kısa değer bu yolda geçerli: denetim ``user add``in denetimi (R6-7)."""
    monkeypatch.setenv(config.DEV_ADMIN_ENV, secrets.token_urlsafe(1))

    assert serve(project, capsys, monkeypatch).code == 0

    assert UserStore(project / "app.db").get_user("admin")


def test_a_blank_variable_is_no_variable(project, capsys, monkeypatch):
    monkeypatch.setenv(config.DEV_ADMIN_ENV, "   ")

    run = serve(project, capsys, monkeypatch)

    assert run.code == 2
    assert cli.NO_USERS in run.out


def test_the_bootstrap_never_touches_an_existing_admin(project, capsys, monkeypatch):
    password = secrets.token_urlsafe(12)
    monkeypatch.setenv(config.DEV_ADMIN_ENV, password)
    assert serve(project, capsys, monkeypatch).code == 0
    before = stored_hash(project)

    monkeypatch.setenv(config.DEV_ADMIN_ENV, secrets.token_urlsafe(12))
    run = serve(project, capsys, monkeypatch)

    assert run.code == 0
    assert DEV_WARNING not in run.out, "var yönetici bootstraple ezilemez"
    assert stored_hash(project) == before
    UserStore(project / "app.db").authenticate("admin", password)
