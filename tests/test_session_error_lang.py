"""T480: oturumun reddi İngilizce bir oturumda Türkçe konuşmuyor (PLAN R8-5).

Dünya test_web_datasets_api'ninki: kurulmuş mini küme, sahte model, tmp günlükler. Veritabanı
olmayan bir kümeye geçişin 409'u iki dilde de okunur. CLI'ın cümlesi ise ``SessionError``da
olduğu gibi durur: ekran çevrilirken terminal aynı satırı okumaya devam eder.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.app.session import NO_DB, SessionError, open_session
from nl2sql.cli import main as cli
from nl2sql.i18n import t
from nl2sql.i18n.detect import TURKISH_LETTERS
from nl2sql.index.store import dataset_arg
from nl2sql.web.app import create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
EN = {"Accept-Language": "en"}
KEY_ENV = "UNSLOTH_API_KEY"


@pytest.fixture
def project(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    cli.build_database(dataset="mini")
    capsys.readouterr()
    return tmp_path


@pytest.fixture
def session(project):
    return open_session(
        dataset="mini",
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
    )


@pytest.fixture
def client(session, project):
    app = create_app(session, saved_path=project / "bilgin.db", static_dir=project / "static")
    return TestClient(app)


def no_db_params(session) -> dict:
    """Kataloğun alanları: oturumun ölçemediği veritabanının yolu ve kümenin komut eklentisi."""
    return {"path": session.db_path, "ds": dataset_arg(session.dataset.name)}


def without_a_database(session) -> None:
    """Küme listeli ama ölçümü yok: geçişin 409 almasının koşulu budur."""
    session.db_path.unlink()


# ------------------------------------------------------------------ POST /api/datasets/active


def test_a_switch_to_an_unbuilt_dataset_speaks_the_request_language(client, session):
    without_a_database(session)

    response = client.post("/api/datasets/active", json={"name": "mini"}, headers=EN)

    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail == t("session.no_db", "en", **no_db_params(session))
    assert not any(char in TURKISH_LETTERS for char in detail), detail
    assert client.get("/api/health").json()["dataset"]["name"] == "mini"


@pytest.mark.parametrize("headers", [{"Accept-Language": "tr"}, {}])
def test_the_same_switch_under_turkish_says_todays_cli_sentence(headers, client, session):
    without_a_database(session)

    response = client.post("/api/datasets/active", json={"name": "mini"}, headers=headers)

    assert response.status_code == 409
    assert response.json()["detail"] == NO_DB.format(**no_db_params(session))


# ------------------------------------------------------------------ SessionError'ın kendisi


def test_open_session_keeps_the_cli_sentence_and_carries_the_catalog_key(session):
    without_a_database(session)

    with pytest.raises(SessionError) as exc:
        open_session(dataset="mini", llm="fake")

    assert str(exc.value) == NO_DB.format(**no_db_params(session))
    assert exc.value.exit_code == 2
    assert exc.value.key == "session.no_db"
    assert exc.value.params == no_db_params(session)


def test_a_missing_api_key_carries_its_own_key_and_says_the_same_sentence(project, monkeypatch):
    monkeypatch.delenv(KEY_ENV, raising=False)

    with pytest.raises(SessionError) as exc:
        open_session(dataset="mini", model="qwen27b-24k", llm="openai")

    assert exc.value.key == "session.key_missing"
    assert exc.value.params == {"env": KEY_ENV}
    assert str(exc.value) == t("session.key_missing", "tr", env=KEY_ENV)
