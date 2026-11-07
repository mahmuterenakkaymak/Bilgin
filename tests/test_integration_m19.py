# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T243: M19 entegrasyonu — roller elle kurulmuş sahte nesnelerle değil, gerçek dünyada sınanır.

Depo gerçek ``UserStore``, kapı gerçek ``create_app``, dünya gerçek ``open_session``: mini
kümesinin tmp'ye kopyalanmış hâli, orada kurulan SQLite ve oraya yazılan kurallar. Yöneticinin
kural düzenlemesi de bu yüzden ölçülüyor — fixture'ın kendi ``rules.json``ına tek bayt yazılmaz.
Üç hesap aynı parolayla girer ve hesaplar yöneticinin kendi API'sinden açılır. İddia tek cümle:
kimse başkasının sorusunu ne görür ne indirebilir, kuralı yalnız yönetici yazar, yönetici de
bir oturumu kapatabilir.
"""

import shutil
from pathlib import Path
from typing import NamedTuple

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from bilgin import config, datasets
from bilgin.app.session import open_session
from bilgin.auth.store import UserStore
from bilgin.web.app import NO_ASK, create_app
from bilgin.web.authz import NOT_ADMIN, NO_SESSION

DATASET = "mini"
# İndeks istemeyen mod: burada ölçülen rol kapılarıdır, vektörler değil.
MODE = "full"
PAROLA = "Bilgin2026!m19"
ADMIN, ALI, AYSE = "admin", "ali", "ayse"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "datasets" / "mini"


class World(NamedTuple):
    """Akışın koştuğu dünya: tmp kopya, oturum, depo ve üç giriş yapmış tarayıcı."""

    rules_path: Path
    session: object
    store: UserStore
    admin: TestClient
    ali: TestClient
    ayse: TestClient
    ali_id: str
    ali_question: str
    ayse_question: str


def login(app, username) -> TestClient:
    """Giriş yapmış tarayıcı: her kullanıcının çerez kavanozu kendi, kapı ise tek."""
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": username, "password": PAROLA})
    assert response.status_code == 200, f"{username} giriş yapamadı: {response.status_code}"
    return client


def question(session, qid) -> str:
    return next(item for item in session.dataset.golden() if item["id"] == qid)["question"]


def ask(client, text) -> str:
    body = client.post("/api/ask", json={"question": text, "mode": MODE}).json()
    assert body["status"] == "answered", body["error"]
    return body["audit_id"]


def questions(client) -> list[str]:
    return [item["question"] for item in client.get("/api/history").json()["history"]]


@pytest.fixture(scope="module")
def world(tmp_path_factory) -> World:
    """tmp'ye kopyalanmış mini dünyası: db, kurallar, soru günlüğü ve hesaplar orada doğar.

    ``config.ROOT`` tmp'ye çevrilir ki kümenin çıktıları da oraya yazılsın; depo gerçek bir
    ``UserStore`` dosyasıdır, kapı CLI'nin ``serve``iyle aynı ``create_app`` çağrısıdır.
    """
    folder = tmp_path_factory.mktemp("m19")
    datasets_dir = folder / "datasets"
    shutil.copytree(FIXTURE, datasets_dir / DATASET)
    mp = MonkeyPatch()
    mp.setattr(config, "ROOT", folder)
    mp.setenv("BILGIN_DATASETS_DIR", str(datasets_dir))
    mp.setenv("BILGIN_APP_DB", str(folder / "bilgin.db"))
    ds = datasets.load_dataset(DATASET)
    ds.db_path.parent.mkdir(parents=True, exist_ok=True)
    ds.build_db(db_path=ds.db_path, sql_path=folder / "mini.sql")

    app_db = folder / "bilgin.db"
    store = UserStore(app_db)
    store.add_user(ADMIN, PAROLA, "admin")  # bootstrapün yazdığı tek yönetici
    session = open_session(
        dataset=DATASET,
        llm="fake",
        audit_path=folder / "audit.jsonl",
        ask_log=folder / "asks.jsonl",
    )
    api = create_app(session, saved_path=app_db, static_dir=folder / "static", users=store)

    admin = login(api, ADMIN)
    for name in (ALI, AYSE):  # hesaplar ekranın yoluyla: yöneticinin kendi API'si
        created = admin.post(
            "/api/users", json={"username": name, "password": PAROLA, "role": "user"}
        )
        assert created.status_code == 200, created.text
    ali, ayse = login(api, ALI), login(api, AYSE)
    ali_question, ayse_question = question(session, "Q01"), question(session, "Q02")
    ali_id = ask(ali, ali_question)
    ask(ayse, ayse_question)

    yield World(
        rules_path=ds.rules_path,
        session=session,
        store=store,
        admin=admin,
        ali=ali,
        ayse=ayse,
        ali_id=ali_id,
        ali_question=ali_question,
        ayse_question=ayse_question,
    )
    mp.undo()


# ------------------------------------------------------------------ geçmiş kişiye özel


def test_each_user_sees_only_their_own_asks(world):
    assert questions(world.ali) == [world.ali_question]
    assert questions(world.ayse) == [world.ayse_question]

    admin = questions(world.admin)
    assert world.ali_question in admin and world.ayse_question in admin


# ------------------------------------------------------------------ replay ve dışa aktarım


def test_ayse_cannot_replay_or_export_alis_ask(world):
    denied = world.ayse.post(f"/api/replay/{world.ali_id}")
    assert (denied.status_code, denied.json()) == (404, {"detail": NO_ASK})
    for ext in ("csv", "xlsx"):
        response = world.ayse.get(f"/api/export/{world.ali_id}.{ext}")
        assert (response.status_code, response.json()) == (404, {"detail": NO_ASK})

    assert world.ali.get(f"/api/export/{world.ali_id}.csv").status_code == 200
    assert world.admin.post(f"/api/replay/{world.ali_id}").json()["status"] == "answered"


# ------------------------------------------------------------------ kural yazımı


def test_a_user_cannot_write_a_rule(world):
    refused = world.ali.post(
        "/api/rules",
        json={"id": "alinin_kurali", "term": "Ali'nin terimi", "definition": "Ali böyle diyor."},
    )

    assert (refused.status_code, refused.json()) == (403, {"detail": NOT_ADMIN})
    assert "alinin_kurali" not in [rule["id"] for rule in world.session.rules]
    assert "alinin_kurali" not in world.rules_path.read_text(encoding="utf-8")


def test_the_admin_edits_a_rule_on_the_copy_and_sees_both_histories(world):
    rules = world.admin.get("/api/rules").json()["rules"]
    edited = {**rules[0], "term": "Ciro (düzeltilmiş)"}

    response = world.admin.put(f"/api/rules/{rules[0]['id']}", json=edited)

    assert response.status_code == 200, response.text
    assert [rule["term"] for rule in response.json()["rules"]][0] == edited["term"]
    assert world.session.rules[0]["term"] == edited["term"], "oturum da tazelendi"
    # Kural tmp kopyada değişti: depodaki fixture'ın dosyası olduğu gibi kaldı.
    assert edited["term"] in world.rules_path.read_text(encoding="utf-8")
    assert edited["term"] not in (FIXTURE / "rules.json").read_text(encoding="utf-8")

    admin = questions(world.admin)
    assert world.ali_question in admin and world.ayse_question in admin


# ------------------------------------------------------------------ oturumun sonu


def test_the_admin_deactivates_ayse_and_her_session_dies(world):
    ayse_id = world.store.get_user(AYSE)["id"]

    response = world.admin.put(f"/api/users/{ayse_id}", json={"active": False})

    assert response.status_code == 200
    assert response.json()["user"]["active"] is False
    dead = world.ayse.get("/api/auth/me")
    assert (dead.status_code, dead.json()) == (401, {"detail": NO_SESSION})
    assert world.ayse.get("/api/history").status_code == 401
    assert world.ali.get("/api/history").status_code == 200, "ali'nin oturumu yerinde"
