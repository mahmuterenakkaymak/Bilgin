# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T445: M28 entegrasyonu — dil akışının dört ucu da gerçek parçalarla koşuyor (PLAN R8-25).

Elde elle kurulmuş tek sahte yok: sayfa ``npm --prefix web run build``in gerçek çıktısı, kapı gerçek
``create_app``in gerçek ``UserStore``la üstünde durduğu gerçek oturum, dünya wwi kümesinin kendi
builder'ının tmp'de kurduğu SQLite, model ``cli.make_client``ın gerçek sahtesi - İngilizce altın
kümeyi de o oynatır (R8-10). Zincir sırayla okunur: derlenmiş sayfa çeviriyi ana pakete gömmez, iki
kataloğu da dinamik importtan çağırır; kişinin tercihi ``/api/auth/me``den okunur ve İngilizce bir
altın sorunun cevabı İngilizcedir; tercih ``PUT /api/auth/me``le değişince reddin cümlesi Türkçe
okunur. Son test paylaşılan kişinin tercihini değiştiriyor, o yüzden dosya sırasıyla koşar.
"""

import re

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from nl2sql import config, datasets
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.i18n import t
from nl2sql.web.app import BUILD_COMMAND, create_app

DATASET = "wwi"
# Arama istemeyen mod: iddia çeviride ve dilde, indeksin bulup bulmadığında değil.
MODE = "full"
PASSWORD = "Bilgin-2026-m28"
# Derlenmiş kataloğun ana paketteki hali: ``import(`./en-<hash>.js`)``.
CHUNK = re.compile(r"\./((?:en|tr)-[\w-]+\.js)")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """tmp'de kurulu wwi dünyası: db kümenin kendi builder'ından, kapı gerçek ``create_app``ten.

    ``config.ROOT`` tmp'ye çevrilir ki kümenin db ve indeks çıktıları da oraya yazılsın; arayüzün
    derlenmiş hali ``config.STATIC_DIR``de durduğu gibi okunur - o sabit importta çözüldüğü için
    tmp'nin altına bakmaz. Kişinin dili depoya yazılmış haliyle gelir: ``me``nin okuduğu alan orada.
    """
    folder = tmp_path_factory.mktemp("m28")
    mp = MonkeyPatch()
    mp.setattr(config, "ROOT", folder)
    # Küme SQLite; ortamda duran bir NL2SQL_BACKEND oturumu sunucuya çevirmesin.
    mp.setenv("NL2SQL_BACKEND", "sqlite")
    app_db = folder / "bilgin.db"
    ds = datasets.load_dataset(DATASET)
    ds.db_path.parent.mkdir(parents=True, exist_ok=True)
    ds.build_db(db_path=ds.db_path, sql_path=folder / "wwi.sql")

    store = UserStore(app_db)
    store.add_user("eren", PASSWORD, "user")
    store.set_lang(store.get_user("eren")["id"], "en")

    session = open_session(
        dataset=DATASET,
        llm="fake",
        audit_path=folder / "audit.jsonl",
        ask_log=folder / "asks.jsonl",
    )
    api = create_app(session, saved_path=app_db, static_dir=config.STATIC_DIR, users=store)
    yield api, ds, store
    mp.undo()


@pytest.fixture
def client(world):
    """Her testin kendi çerez kavanozu: oturumlar ayrı, depo ve dünya aynı."""
    api, _, _ = world
    return TestClient(api)


def login(client) -> dict:
    signed_in = client.post("/api/auth/login", json={"username": "eren", "password": PASSWORD})
    assert signed_in.status_code == 200, signed_in.text
    return signed_in.json()


# ------------------------------------------------------------------ derlenmiş sayfa


def test_the_page_pulls_both_catalogs_through_the_entry(world, client):
    """Sayfa ana paketi çağırır, çeviriyi ana paket dinamik importtan alır (R8-18)."""
    if not (config.STATIC_DIR / "index.html").is_file():
        pytest.skip(f"arayüz derlenmemiş: {BUILD_COMMAND}")

    page = client.get("/")

    assert page.status_code == 200 and page.headers["content-type"].startswith("text/html")
    assert page.text == (config.STATIC_DIR / "index.html").read_text(encoding="utf-8")
    entry = re.search(r'src="(/assets/index-[\w-]+\.js)"', page.text)
    assert entry, "sayfa derlenmiş ana paketi yüklemiyor"

    bundle = client.get(entry.group(1))
    assert bundle.status_code == 200
    names = CHUNK.findall(bundle.text)
    assert sorted({name.split("-")[0] for name in names}) == ["en", "tr"], names
    for name in names:
        # Katalog sayfanın yükledikleri arasında değilse iki dilin sözü birden inmez.
        assert name not in page.text, f"{name} ana pakete gömülmüş"
        assert client.get(f"/assets/{name}").status_code == 200


# ------------------------------------------------------------------ kişinin dili


def test_an_english_users_me_names_their_language(client):
    assert login(client) == {
        "username": "eren",
        "role": "user",
        "business_role": "genel",
        "lang": "en",
    }
    assert client.get("/api/auth/me").json() == login(client)


def test_an_english_golden_question_answers_in_english(world, client):
    _, ds, _ = world
    line = next(item for item in ds.golden("en") if item["id"] == "E01")

    login(client)
    body = client.post("/api/ask", json={"question": line["question"], "mode": MODE}).json()

    assert body.get("error") is None, body.get("error")
    assert body["status"] == "answered" and body["answer_lang"] == "en"
    assert body["sql"] == line["sql"]
    assert body["facts"][0]["label"] == t("facts.row_count", "en")


def test_switching_the_preference_switches_the_rejection(world, client):
    """Reddin cümlesi kişinin o anki tercihidir: PUT ile dönen dil bir sonraki cümleyi de taşır."""
    _, _, store = world
    login(client)

    english = client.post("/api/ask", json={"question": " "})
    assert english.status_code == 400
    assert english.json()["detail"] == t("app.blank_question", "en")

    switched = client.put("/api/auth/me", json={"lang": "tr"})
    assert switched.status_code == 200 and switched.json()["lang"] == "tr"

    turkish = client.post("/api/ask", json={"question": " "})
    assert 400 <= turkish.status_code < 500
    assert turkish.json()["detail"] == t("app.blank_question", "tr")
    assert UserStore(store.path).get_user("eren")["lang"] == "tr", "tercih dosyada da değişti"
