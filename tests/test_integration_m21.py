# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T295: M21 entegrasyonu — tek konuşma, iki uç: ekranın üç turu, komut satırının dördüncüsü.

Elle yapılmış sahte parça yok: hesaplar gerçek ``user add`` komutundan geçer (gerçek ``UserStore``,
gerçek parola sorması), dünya kümenin kendi ``builder``ının kurduğu sentetik ERP üzerinde gerçek
``open_session`` ve gerçek ``create_app``, model ``--llm fake``in altın kaydı. Konuşmanın tek
dosyası uygulamanın kendi veritabanı: ekranın açtığı thread'i ``ask --conversation`` kendi ucundan
sürdürür, yani dördüncü turun ilk üçüyle işi yalnız o dosyadır. Kimlikler yalnız yanıtlardan okunur.
İddia: üç tur tek konuşmadır, özetler ``CONV_KEEP_ROWS``le sınırlıdır, tarih turları konuşmayla
birlikte gösterir, sahibi olmayan 404 okur, komut satırı aynı threadi ``tur 4`` diye sürdürür.
Son test konuşmayı büyüttüğü için en sonda durur.
"""

import getpass
from pathlib import Path
from typing import NamedTuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from nl2sql import config
from nl2sql.app.conversations import ConversationStore
from nl2sql.app.session import Session, open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.datasets import load_dataset
from nl2sql.web.app import create_app

REPO = Path(__file__).resolve().parents[1]
DATASET = "synthetic_erp"
PAROLA = "Bilgin2026!m21"
ADMIN, OTHER = "admin", "muhasebe"

# Ekranın üç turu: 12 satırlık bir cevap (özet kesilir), tam sınırda 5 satır ve tek satır.
WEB_TURNS = ("Q05", "Q02", "Q03")
CLI_TURN = "Q04"
# Sözleşme cümlesi: olmayanla başkasınınki aynı şeyi söyler.
NOT_FOUND = {"detail": "Konuşma bulunamadı."}


class World(NamedTuple):
    """Akışın koştuğu tmp dünyası: uygulama dosyası, oturum, kapı ve iki girişmiş tarayıcı."""

    root: Path
    session: Session
    app: FastAPI
    admin: TestClient
    other: TestClient


def login(app, username) -> TestClient:
    """Giriş yapmış tarayıcı: çerez kavanozu kendine, kapı aynı uygulamaya ait."""
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": username, "password": PAROLA})
    assert response.status_code == 200, f"{username} giriş yapamadı: {response.status_code}"
    return client


def question(session, qid) -> str:
    return next(item for item in session.dataset.golden() if item["id"] == qid)["question"]


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """CLI'den eklenmiş iki hesap, kümenin kendi kurduğu veritabanı, tek uygulama dosyası.

    ``config.ROOT`` tmp'ye çevrilir ki kümenin çıktıları (``data/test.db``) ve uygulamanın kendi
    dosyası oraya doğsun; ``datasets/`` okunur, depo kökündeki ``real_datasets/`` açılmaz.
    """
    root = tmp_path_factory.mktemp("m21")
    mp = MonkeyPatch()
    mp.setattr(config, "ROOT", root)
    mp.setenv("NL2SQL_DATASETS_DIR", str(REPO / "datasets"))
    mp.setenv("NL2SQL_REAL_DATASETS_DIR", str(root / "real_datasets"))
    mp.setenv("NL2SQL_APP_DB", str(root / "bilgin.db"))
    mp.setenv("NL2SQL_BACKEND", "sqlite")
    mp.setattr(getpass, "getpass", lambda prompt="": PAROLA)

    # Hesaplar komutun kendisinden: parolayı sorar, karmayı gerçek UserStore'a yazar (R6-8).
    assert cli.main(["user", "add", ADMIN, "--role", "admin"]) == 0
    assert cli.main(["user", "add", OTHER]) == 0

    load_dataset(DATASET).build_db()
    session = open_session(
        dataset=DATASET,
        llm="fake",
        audit_path=root / "logs" / "audit.jsonl",
        ask_log=root / "logs" / "asks.jsonl",
    )
    app = create_app(
        session,
        saved_path=root / "bilgin.db",
        static_dir=root / "static",
        users=UserStore(root / "bilgin.db"),
    )
    yield World(root, session, app, login(app, ADMIN), login(app, OTHER))
    mp.undo()


@pytest.fixture(scope="module")
def thread(world):
    """Ekranın açtığı konuşma: üç tur, ``(kimlik, payloadlar)``; kimlik yalnız yanıttan okunur."""
    payloads = []
    for qid in WEB_TURNS:
        response = world.admin.post(
            "/api/ask",
            json={
                "question": question(world.session, qid),
                "mode": "full",
                "conversation_id": payloads[0]["conversation_id"] if payloads else None,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "answered", body.get("error")
        payloads.append(body)

    assert len({item["conversation_id"] for item in payloads}) == 1, "üç tur tek konuşmadır"
    return payloads[0]["conversation_id"], payloads


# ------------------------------------------------------------------ üç tur tek konuşma


def test_the_three_web_turns_are_one_conversation(world, thread):
    conversation_id, payloads = thread

    assert [item["turn"] for item in payloads] == [1, 2, 3]
    assert [item["dataset"] for item in payloads] == [DATASET] * 3
    assert payloads[0]["context"] is None, "ilk turun dayandığı tur yok"


# ------------------------------------------------------------------ GET /api/conversations/{id}


def test_the_thread_reads_back_with_capped_rows(world, thread):
    conversation_id, payloads = thread

    body = world.admin.get(f"/api/conversations/{conversation_id}").json()

    assert set(body) == {"conversation", "turns"}
    assert body["conversation"]["id"] == conversation_id
    assert body["conversation"]["username"] == ADMIN
    assert body["conversation"]["dataset"] == DATASET
    first = question(world.session, WEB_TURNS[0])
    assert body["conversation"]["title"] == first[: config.CONV_TITLE_CHARS]
    assert [turn["n"] for turn in body["turns"]] == [1, 2, 3]
    assert [turn["question"] for turn in body["turns"]] == [item["question"] for item in payloads]
    for turn, item in zip(body["turns"], payloads):
        assert turn["status"] == "answered" and turn["sql"] == item["sql"]
        assert turn["audit_id"] == item["audit_id"]
        assert turn["answer_text"] == item["answer_text"]
        assert turn["summary"]["columns"] == item["columns"]
        # Miras kalan kadarı: satırlar kesik, sayının kendisi cevabınki.
        assert len(turn["summary"]["rows"]) <= config.CONV_KEEP_ROWS
        assert turn["summary"]["row_count"] == item["row_count"]
    assert payloads[0]["row_count"] > config.CONV_KEEP_ROWS, "kesilen bir cevap yoktu"
    assert len(body["turns"][0]["summary"]["rows"]) == config.CONV_KEEP_ROWS


# ------------------------------------------------------------------ GET /api/history


def test_history_shows_the_three_turns_with_the_conversation(world, thread):
    conversation_id, payloads = thread

    items = world.admin.get("/api/history").json()["history"]

    assert [item["audit_id"] for item in items] == [p["audit_id"] for p in reversed(payloads)]
    assert [item["turn"] for item in items] == [3, 2, 1]
    assert {item["conversation_id"] for item in items} == {conversation_id}


# ------------------------------------------------------------------ sahiplik


def test_the_second_user_neither_sees_nor_continues_it(world, thread):
    conversation_id, _ = thread

    assert world.other.get("/api/conversations").json()["conversations"] == []
    assert world.other.get(f"/api/conversations/{conversation_id}").json() == NOT_FOUND
    refused = world.other.post(
        "/api/ask",
        json={"question": question(world.session, CLI_TURN), "mode": "full",
              "conversation_id": conversation_id},
    )
    assert refused.status_code == 404, "yabancı kimlikle soru da konuşmaya düşmez"
    assert [turn["n"] for turn in
            world.admin.get(f"/api/conversations/{conversation_id}").json()["turns"]] == [1, 2, 3]


# ------------------------------------------------------------------ CLI: aynı threadin 4. turu


def test_the_cli_continues_the_same_conversation_as_turn_four(world, thread, capsys):
    conversation_id, _ = thread
    capsys.readouterr()

    code = cli.main(
        ["ask", question(world.session, CLI_TURN), "--dataset", DATASET, "--llm", "fake",
         "--mode", "full", "--conversation", conversation_id]
    )
    out = capsys.readouterr().out

    assert code == 0, out
    assert f"Konuşma: {conversation_id} · tur 4" in out
    turns = ConversationStore(config.app_db_path()).get(conversation_id)["turns"]
    assert [turn["n"] for turn in turns] == [1, 2, 3, 4]
    assert turns[3]["question"] == question(world.session, CLI_TURN)
    assert turns[3]["status"] == "answered"
    assert len(turns[3]["summary"]["rows"]) <= config.CONV_KEEP_ROWS
