# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T403: isteğin dili (PLAN R8-5, Contracts "request lang", "me PUT").

Dünya ``tests/test_web_auth.py`` ile aynı - kopya, import değil: gerçek mini küme, sahte model,
tmp yollar. ``request_lang`` üç kaynaktan çözülür (kişinin tercihi > Accept-Language > program
dili), o yüzden sıranın kendisi burada ölçülür; ``/api/ask``ta sinyalsiz bir soru arayüz dilini
olduğu gibi ``answer_lang`` olarak geri verir, yani uçtan uca aynı kapıdan da geçilir.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from nl2sql import config
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.web.app import create_app
from nl2sql.web.lang import request_lang

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"

PAROLA = "Bilgin2026!erp"
BAD_LANG = "Dil tr ya da en olmalı."

# Sinyali olmayan bir soru: detect_lang hiçbir dile karar veremez, arayüz dili olduğu gibi çıkar.
NO_SIGNAL = "STK001"
ENGLISH = "Total sales by city"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    monkeypatch.delenv("NL2SQL_LANG", raising=False)
    cli.build_database(dataset="mini")
    return tmp_path


@pytest.fixture
def session(project, capsys):
    capsys.readouterr()
    return open_session(
        dataset="mini",
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
    )


@pytest.fixture
def users(project) -> UserStore:
    return UserStore(project / "bilgin.db")


def build(session, project, users=None) -> TestClient:
    return TestClient(
        create_app(
            session,
            saved_path=project / "bilgin.db",
            static_dir=project / "static",
            users=users,
        )
    )


@pytest.fixture
def client(session, project, users) -> TestClient:
    users.add_user("eren", PAROLA, "admin")
    return build(session, project, users)


def login(client, username="eren", password=PAROLA):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def ask(client, question, accept_language=None):
    headers = {} if accept_language is None else {"accept-language": accept_language}
    return client.post("/api/ask", json={"question": question}, headers=headers)


def http_request(accept_language=None) -> Request:
    """Başlığı elle kurulmuş bir istek: ``request_lang`` yalnız ondan okur."""
    headers = [] if accept_language is None else [(b"accept-language", accept_language.encode())]
    return Request({"type": "http", "headers": headers})


def golden_question(session) -> str:
    return next(item for item in session.dataset.golden())["question"]


# ---------------------------------------------------------------------- çözülme sırası


def test_without_a_preference_or_a_header_the_program_language_wins(monkeypatch):
    monkeypatch.setenv("NL2SQL_LANG", "en")

    assert request_lang(http_request(), None) == "en"
    assert request_lang(http_request("de"), {"lang": None}) == "en"  # tanıdık başlık yok
    monkeypatch.delenv("NL2SQL_LANG", raising=False)
    assert request_lang(http_request(), None) == config.DEFAULT_LANG


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("en-US,en;q=0.9", "en"),
        ("tr-TR,tr;q=0.8", "tr"),
        ("de,fr;q=0.9", config.DEFAULT_LANG),  # tanıdık tek etiket yok
        ("de,en;q=0.5", "en"),  # ilk tanıdık etiket kazanır
        ("", config.DEFAULT_LANG),
    ],
)
def test_the_first_known_tag_of_accept_language_wins(header, expected):
    assert request_lang(http_request(header), None) == expected


@pytest.mark.parametrize(
    ("pref", "header", "expected"),
    [
        ("en", "tr", "en"),
        ("tr", "en", "tr"),
        ("en", "", "en"),
        ("", "en", "en"),  # tercih boş: başlık konuşur
        (None, "en", "en"),  # Run 7 dosyalarında tercih NULL doğar
    ],
)
def test_the_users_preference_beats_the_header(pref, header, expected):
    assert request_lang(http_request(header), {"lang": pref}) == expected


# ------------------------------------------------------------------------------ PUT me


def test_a_user_sets_their_own_language_and_it_survives_a_new_session(
    client, session, project, users
):
    login(client)
    assert client.get("/api/auth/me").json().get("lang") is None  # tercih yok: anahtar da yok

    changed = client.put("/api/auth/me", json={"lang": "en"})

    assert changed.status_code == 200
    assert changed.json() == {
        "username": "eren",
        "role": "admin",
        "business_role": "genel",
        "lang": "en",
    }
    assert users.get_user("eren")["lang"] == "en"

    fresh = build(session, project, users)  # yeni çerez kavanozu, aynı depo
    login(fresh)
    assert fresh.get("/api/auth/me").json()["lang"] == "en"
    assert ask(fresh, NO_SIGNAL).json()["answer_lang"] == "en"


@pytest.mark.parametrize("lang", ["de", "EN", "", "tr-TR", "english"])
def test_a_language_the_program_does_not_know_is_refused_and_nothing_is_written(client, users, lang):
    login(client)

    refused = client.put("/api/auth/me", json={"lang": lang})

    assert refused.status_code == 422
    assert refused.json() == {"detail": BAD_LANG}
    assert client.get("/api/auth/me").json().get("lang") is None
    assert users.get_user("eren")["lang"] is None


# ----------------------------------------------------------------------- anonim, soru dili


def test_an_app_without_users_reads_the_header(session, project):
    """Run 5 modu: kullanıcı yok, yani karar başlığın - program dili yalnız o da susarsa."""
    client = build(session, project)

    assert ask(client, NO_SIGNAL, "en-US,en;q=0.9").json()["answer_lang"] == "en"
    assert ask(client, NO_SIGNAL).json()["answer_lang"] == config.DEFAULT_LANG


def test_the_answer_language_is_the_questions_language_not_the_interfaces(client, session):
    login(client)
    client.put("/api/auth/me", json={"lang": "en"})

    turkish = ask(client, golden_question(session), "en").json()["answer_lang"]
    english = ask(client, ENGLISH, "tr").json()["answer_lang"]

    assert (turkish, english) == ("tr", "en")
