"""T331: M24 entegrasyonu — başlangıç ekranı elle kurulmuş tek sahte parça olmadan koşuyor.

Dünyanın her parçası kendi kapısından kurulur: kullanıcılar gerçek ``UserStore``, pano gerçek
``create_app``in üstünde gerçek ``open_session`` (ajan istemcisi ``cli.make_client``ın sahte altın
kaydı), kartlar kümenin kendi ``ready_questions.json``u — tohumu ``serve``ın çağırdığı
``ensure_seeded`` yazıyor, veritabanı ise kümenin kendi builder'ı. İddia: iki iş rolü kendi
kartlarını ve ``*`` kartını görür; ``*`` kartının SQL'i TTL içinde **iki kullanıcı için bir kez**
yürür (sayan kabuk gerçek yürütücünün üstündedir); bir kartı açmak konuşmanın 1. turudur ve takip
sorusu ``uses_turns``ı [1] olan 2. tur olur; yöneticinin taze bir cevaptan onayladığı kart satış
kullanıcısının panosuna düşer; kişinin çivilediği kartı öteki kullanıcı görmez; ve hiçbir
``GET /api/start`` ajanı uyandırmaz.
"""

from pathlib import Path
from typing import NamedTuple

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from nl2sql import config
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.datasets import load_dataset
from nl2sql.start.seed import ensure_seeded
from nl2sql.web.app import create_app

REPO = Path(__file__).resolve().parents[1]
DATASET = "synthetic_erp"
MODE = "full"
# PASSWORD_MIN_LEN'den uzun; üç hesap da aynı parolayı taşır, hiçbiri gerçek bir kullanıcı değil.
PASSWORD = "Bilgin-2026-m24"
EVERY_ROLE = "*"
# Kartın takip sorusu F01'in ikinci turudur: birinci turu bir kartın sorusuyla aynı cümle, yani
# kartı açmak zincirin birinci turunun yerine geçer (R7-13 zincirin tanımı).
F01 = next(chain for chain in load_dataset(DATASET).followups() if chain["id"] == "F01")
SEEDS = load_dataset(DATASET).ready_questions()
# Kullanıcı adı -> iş rolü: panonun süzgeci roldür, ad değil.
BOARDS = {"satis": "satis", "satinalma": "satin_alma"}


class CountingClient:
    """Ajan istemcisinin kabuğu: ``chat`` sayılır, cevabı sahte altın kayıt verir."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        return self._inner.chat(messages, tools)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class CountingExecutor:
    """Gerçek yürütücünün kabuğu: ``(kaynak, sql)`` sırası kartların kaç kez koştuğunu söyler."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self.calls: list[tuple[str, str]] = []

    def execute(self, sql, budget=None, source="", **kwargs):
        self.calls.append((source, sql))
        return self._inner.execute(sql, budget, source, **kwargs)

    def card_runs(self, sql: str) -> int:
        """Panonun yüklediği kartların sayısı: kaynakları ``start:`` olan yürüyüşler (R7-18)."""
        return sum(1 for source, text in self.calls if source.startswith("start:") and text == sql)

    def __getattr__(self, name):
        return getattr(self._inner, name)


class World(NamedTuple):
    """Akışın koştuğu tmp dünyası: kapı, sayan yürütücü ve doğan ajan istemcileri."""

    app: FastAPI
    executor: CountingExecutor
    clients: list


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Kümenin kurulu dünyası: db builder'dan, tohum ``ensure_seeded``den, kapı ``create_app``ten.

    ``config.ROOT`` tmp'de: db, denetim ve soru günlükleri de oraya yazılır. Yürütücü gerçek
    yürütücüdür; sayan kabuk onun üstüne oturur, yani kartın SQL'i aynı politika ve aynı
    salt okunur kapıdan geçer.
    """
    root = tmp_path_factory.mktemp("m24")
    mp = MonkeyPatch()
    mp.setattr(config, "ROOT", root)
    mp.setenv("NL2SQL_DATASETS_DIR", str(REPO / "datasets"))
    mp.setenv("NL2SQL_REAL_DATASETS_DIR", str(root / "real_datasets"))
    mp.setenv("NL2SQL_APP_DB", str(root / "bilgin.db"))
    mp.setenv("NL2SQL_BACKEND", "sqlite")

    app_db = root / "bilgin.db"
    users = UserStore(app_db)
    users.add_user("admin", PASSWORD, "admin", "yonetim")
    for username, role in BOARDS.items():
        users.add_user(username, PASSWORD, "user", role)

    dataset = load_dataset(DATASET)
    dataset.build_db()
    clients: list = []

    def make_agent(mode):
        """Ajanın istemcisi ``cli.make_client``ın sahtesidir; kaç kez koştuğu burada sayılır."""
        client = CountingClient(cli.make_client("fake", mode, dataset, None))
        clients.append(client)
        return client

    session = open_session(
        dataset=DATASET,
        llm="fake",
        audit_path=root / "logs" / "audit.jsonl",
        ask_log=root / "logs" / "asks.jsonl",
        client_factory=make_agent,
    )
    session.executor = CountingExecutor(session.executor)
    app = create_app(session, saved_path=app_db, static_dir=root / "static", users=users)
    assert ensure_seeded(app.state.ready, users, session.dataset, session.executor) == len(SEEDS)
    yield World(app, session.executor, clients)
    mp.undo()


# ------------------------------------------------------------------ yardımcı kapılar


def login(app: FastAPI, username: str) -> TestClient:
    """Kullanıcının kendi çerez kavanozu: her hesap aynı kapıdan, ayrı oturumdan geçer."""
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": username, "password": PASSWORD})
    assert response.status_code == 200, response.text
    return client


def board(world: World, client: TestClient) -> dict:
    """``GET /api/start``: kartların yükü. Model bu yolda hiçbir koşulda koşmaz (R7-18)."""
    woke = agent_calls(world)
    response = client.get("/api/start")
    assert response.status_code == 200, response.text
    assert agent_calls(world) == woke, "pano ajanı uyandırdı"
    return response.json()


def ask(client: TestClient, question: str, conversation_id: str | None = None) -> dict:
    body = client.post(
        "/api/ask",
        json={"question": question, "mode": MODE, "conversation_id": conversation_id},
    ).json()
    assert body.get("error") is None, body
    assert body["status"] == "answered", body
    return body


def agent_calls(world: World) -> int:
    return sum(client.calls for client in world.clients)


def titles(payload: dict) -> list[str]:
    return [card["title"] for card in payload["cards"]]


def loaded(card: dict) -> bool:
    """Kartın yükü gerçekten dolu mu: sayının değeri, grafiğin seçeneği, tablonun satırları."""
    if card.get("display") == "number":
        return card.get("value") is not None
    if card.get("display") == "chart":
        return bool(card.get("chart"))
    return bool(card.get("rows"))


def expected_titles(role: str) -> list[str]:
    """Kümenin tohumundan rolün panosu: kendi rolü + ``*``, ``position`` sonra kimlik sırasıyla."""
    lines = [(n, line) for n, line in enumerate(SEEDS) if line["business_role"] in (role, EVERY_ROLE)]
    return [line["title"] for _, line in sorted(lines, key=lambda pair: (pair[1]["position"], pair[0]))]


# ------------------------------------------------------------------ rolün panosu


def test_each_role_sees_its_own_cards_and_the_common_one(world):
    assert any(line["business_role"] == EVERY_ROLE for line in SEEDS), "tohumda * kartı yok"
    for username, role in BOARDS.items():
        payload = board(world, login(world.app, username))

        assert payload["business_role"] == role
        assert titles(payload) == expected_titles(role), "kendi rolü + *, sırası position/id"
        for card in payload["cards"]:
            assert not card.get("error"), f"{card['title']!r} yürümedi: {card.get('error')}"
            assert loaded(card), f"{card['title']!r} boş geldi ({card['display']})"
            assert card["personal"] is False, "tohum kart bir rolün kartıdır"


def test_the_common_card_ran_once_for_both_roles_inside_the_ttl(world):
    # Panolar yukarıdaki testte birer kez okundu; TTL (START_CACHE_S) henüz inmedi. ``*`` kartı iki
    # panonun da kartıdır ve iki yürüyüş değil bir yürüyüş gördü: anahtar kullanıcı değil karttır.
    for line in SEEDS:
        if line["business_role"] in (*BOARDS.values(), EVERY_ROLE):
            assert world.executor.card_runs(line["sql"]) == 1, f"{line['title']!r} bir daha koştu"


# ------------------------------------------------------------------ karttan açılan konuşma


def test_a_card_opens_a_conversation_whose_follow_up_is_turn_two(world):
    client = login(world.app, "satis")
    card = next(item for item in board(world, client)["cards"]
                if item["question"] == F01["turns"][0]["question"])

    woke = agent_calls(world)
    opened = client.post(f"/api/start/cards/{card['id']}/open").json()

    assert opened["status"] == "answered" and opened["error"] is None
    assert opened["turn"] == 1 and opened["context"] is None, "kart yeni konuşmanın 1. turu"
    assert [step["tool"] for step in opened["steps"]] == ["replay"], "kartı model yazmadı"
    assert opened["sql"] == F01["turns"][0]["sql"]
    assert agent_calls(world) == woke, "kartı açmak ajanı uyandırmadı"

    follow = ask(client, F01["turns"][1]["question"], opened["conversation_id"])

    assert follow["turn"] == 2 and follow["conversation_id"] == opened["conversation_id"]
    assert follow["context"]["uses_turns"] == [1], "takip sorusu kartın turuna dayanır"
    assert follow["sql"] == F01["turns"][1]["sql"]
    assert agent_calls(world) > woke, "takip sorusu ise ajanı koşturdu"


# ------------------------------------------------------------------ onay ve kişisel kart


def test_the_admins_fresh_approval_lands_on_the_satis_board(world):
    admin = login(world.app, "admin")
    question = load_dataset(DATASET).golden()[0]["question"]
    answer = ask(admin, question)

    added = admin.post(
        "/api/ready-questions",
        json={"audit_id": answer["audit_id"], "title": "Yöneticinin onayı", "business_role": "satis"},
    )

    assert added.status_code == 200, added.text
    assert added.json()["ready_question"]["approved"] is True

    satis = board(world, login(world.app, "satis"))
    assert "Yöneticinin onayı" in titles(satis)
    assert loaded(next(item for item in satis["cards"] if item["title"] == "Yöneticinin onayı"))
    assert "Yöneticinin onayı" not in titles(board(world, login(world.app, "satinalma")))


def test_a_pinned_card_is_its_owners_alone(world):
    satis = login(world.app, "satis")
    answer = ask(satis, load_dataset(DATASET).golden()[1]["question"])

    pinned = satis.post(
        "/api/start/cards", json={"audit_id": answer["audit_id"], "title": "Kişisel kartım"}
    )

    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["card"]["personal"] is True

    assert "Kişisel kartım" in titles(board(world, satis))
    assert "Kişisel kartım" not in titles(board(world, login(world.app, "satinalma")))


# ------------------------------------------------------------------ ajan hiç uyanmaz


def test_no_board_request_ever_woke_the_agent(world):
    woke = agent_calls(world)
    ask(login(world.app, "admin"), load_dataset(DATASET).golden()[2]["question"])
    assert agent_calls(world) > woke, "bir soru ajanı koşturdu; aşağıdaki yokluk ölçümü boş değil"
    woke = agent_calls(world)

    for username in ("admin", *BOARDS):
        assert board(world, login(world.app, username))["cards"], "pano boş kaldı"
        assert agent_calls(world) == woke, f"{username} panosu ajanı uyandırdı"
