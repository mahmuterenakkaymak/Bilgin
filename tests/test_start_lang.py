# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T408: başlangıç ekranının ve hazır soruların cümleleri isteğin dilinde (PLAN R8-5).

Dünya ``tests/test_web_start_api.py`` ile aynı gerçeklikte - kopya, import değil: kurulmuş sentetik
ERP, sahte ajan, tmp uygulama dosyası. Dil tek bir başlıkla seçilir, ``Accept-Language``: aynı
dünyanın reddi iki dilde de okunur. tr tarafı 2026-10-27'de ekranda okunan cümleye sabittir -
katalog bir gün bozulursa buradan anlaşılır; İngilizce taraf kataloğun kendi satırıdır.

Kartın yürümeyen cümlesi de kataloğundur: kart, sohbetin aynı hatada söylediğini söyler. Tohum
satırları ve kayıtlı başlıklar ise veridir, yani yazıldıkları gibi okunurlar.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.app import asklog
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.i18n import t
from nl2sql.i18n.scan import user_literals
from nl2sql.schema_map import build
from nl2sql.start import cards, ready, seed, suggest
from nl2sql.web import start_api
from nl2sql.web.app import create_app

DATASET = "synthetic_erp"
PAROLA = "Bilgin2026!erp"

TOTAL_SQL = "SELECT SUM(STHAR_GCMIK * STHAR_NF) AS NET_CIRO FROM TBLSTHAR WHERE STHAR_HTUR = 'S'"
LIST_SQL = "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT WHERE IL = 'ANKARA' ORDER BY CARI_KOD"
BAD_SQL = "SELECT YOK_SUTUNU FROM TBLSTSABIT"
# Soru kendi dilini söylemiyor: cevabın dili o zaman isteğin dilidir (R8-6).
NEUTRAL = "2026?"

# 2026-10-27'de ekranda okunan cümleler: Türkçe yolun kataloğa taşınırken değişmediğinin ölçütü.
TODAY = {
    "start.not_found": "Hazır soru bulunamadı.",
    "start.bad_role": "Geçersiz iş rolü.",
    "start.bad_display": "Geçersiz görünüm: number, chart ya da table olmalı.",
    "start.personal_cap": "En fazla {n} kişisel kart ekleyebilirsiniz.",
    "start.unknown_field": "Tanınmayan hazır soru alanı: {fields}.",
    "start.no_ask": "Bu soru geçmişte bulunamadı.",
    "start.no_job": "Öneri işi bulunamadı.",
    "start.open_note": "Karttan açıldı: kayıtlı SQL yeniden çalıştırıldı, model SQL yazmadı.",
    "start.open_step": "Hazır soru ({id}) kayıtlı SQL ile açıldı.",
    "card.refresh_too_soon": "Bu kart az önce yenilendi; {n} sn sonra yeniden deneyin.",
    "ask.fail.exec:sql": "Sorgu veritabanında çalıştırılamadı.",
}

REJECTIONS = (
    "personal_cap",
    "refresh_too_soon",
    "no_card_open",
    "no_card_unpin",
    "no_ask",
    "no_job",
    "bad_role",
    "bad_display",
    "unknown_field",
)

# Tohumun tek Türkçe satırı koşumun bastığı nottur; önerininki modeli okuduğu istektir - ikisi de
# kullanıcıya görünmez, o yüzden kataloğa taşınmaz (R8-4ün allow listesi).
MODULES = (
    (start_api, ()),
    (ready, ()),
    (cards, ()),
    (suggest, ("SYSTEM", "SECTIONS")),
    (seed, ("SKIPPED",)),
)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    """Kurulmuş sentetik ERP bir kez: kartlar gerçek veride koşar, veriler testler arasında değişmez."""
    path = tmp_path_factory.mktemp("startlang") / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture
def world(db, tmp_path):
    """Bir uygulamanın dünyası: sahte ajan, üç kimlik, tmp uygulama dosyası ve boş kartlar."""
    session = open_session(
        dataset=DATASET,
        llm="fake",
        db_path=db,
        audit_path=tmp_path / "audit.jsonl",
        ask_log=tmp_path / "asks.jsonl",
        client_factory=lambda mode: fake.FakeLLM(fake.never_submit()),
    )
    users = UserStore(tmp_path / "bilgin.db")
    users.add_user("yonetici", PAROLA, "admin", "yonetim")
    users.add_user("satis1", PAROLA, "user", "satis")
    users.add_user("satin1", PAROLA, "user", "satin_alma")
    app = create_app(
        session, saved_path=tmp_path / "bilgin.db", static_dir=tmp_path / "static", users=users
    )
    return SimpleNamespace(app=app, session=session, store=app.state.ready)


def client(app, username: str, lang: str) -> TestClient:
    """Başlığı sabitlenmiş bir kullanıcının çerez kavanozu: dil tek başlığın işidir (R8-5)."""
    made = TestClient(app)
    made.headers["accept-language"] = lang
    granted = made.post("/api/auth/login", json={"username": username, "password": PAROLA})
    assert granted.status_code == 200, f"{username} giriş yapamadı: {granted.status_code}"
    return made


def expected(key: str, lang: str, **params) -> str:
    """Türkçe bugün okunan cümle, İngilizce kataloğun kendi satırı (R8-5)."""
    return TODAY[key].format(**params) if lang == "tr" else t(key, lang, **params)


def card(world, role, title, sql=TOTAL_SQL, display="number", question="Ne kadar?") -> dict:
    """Onaylı bir hazır soru satırı: depoya HTTPden değil, doğrudan - kapı onu okumak için."""
    return world.store.add(
        DATASET, role, title, question, sql, display, approved=True
    )


def ask_record(world, audit_id: str, question: str, sql: str = LIST_SQL, username="satis1") -> str:
    """Soru günlüğünün satırı: ``sql`` o soruda gerçekten yürümüş cümledir (R5-4ün alanları)."""
    asklog.record_ask(
        {
            "audit_id": audit_id,
            "dataset": DATASET,
            "question": question,
            "status": "answered",
            "sql": sql,
            "username": username,
        },
        world.session.ask_log,
    )
    return audit_id


def detail_of(response, status: int) -> str:
    """Reddin cümlesi: durum da ölçülmüş olsun diye önce ona bakılır, sonra detay okunur."""
    assert response.status_code == status, f"{response.status_code}: {response.text}"
    return response.json()["detail"]


def reject(name: str, lang: str, made: TestClient, world) -> tuple[str, str]:
    """Adı geçen reddi koşar: (beklenen cümle, cevabın okunan cümlesi)."""
    if name == "personal_cap":
        for n in range(config.PERSONAL_CARDS):
            ask_record(world, f"k{n}", f"Soru {n}?")
            assert made.post("/api/start/cards", json={"audit_id": f"k{n}"}).status_code == 200
        ask_record(world, "kk", "Yedinci soru?")
        response = made.post("/api/start/cards", json={"audit_id": "kk"})
        wanted = expected("start.personal_cap", lang, n=config.PERSONAL_CARDS)
        return wanted, detail_of(response, 409)
    if name == "refresh_too_soon":
        pinned = card(world, "satis", "Net ciro")
        assert made.post(f"/api/start/cards/{pinned['id']}/refresh").status_code == 200
        response = made.post(f"/api/start/cards/{pinned['id']}/refresh")
        wanted = expected("card.refresh_too_soon", lang, n=config.CARD_REFRESH_MIN_S)
        return wanted, detail_of(response, 429)
    if name == "no_card_open":
        other = card(world, "satin_alma", "Satın alma kartı")
        return expected("start.not_found", lang), detail_of(
            made.post(f"/api/start/cards/{other['id']}/open"), 404
        )
    if name == "no_card_unpin":
        role_card = card(world, "satis", "Satış kartı")
        return expected("start.not_found", lang), detail_of(
            made.delete(f"/api/start/cards/{role_card['id']}"), 404
        )
    if name == "no_ask":
        response = made.post("/api/start/cards", json={"audit_id": "olmayan"})
        return expected("start.no_ask", lang), detail_of(response, 404)
    if name == "no_job":
        admin = client(world.app, "yonetici", lang)
        response = admin.get("/api/ready-questions/suggest/" + "0" * 32)
        return expected("start.no_job", lang), detail_of(response, 404)
    if name == "bad_role":
        admin = client(world.app, "yonetici", lang)
        ask_record(world, "a1", "Net ciro ne kadar?", username="yonetici")
        response = admin.post(
            "/api/ready-questions", json={"audit_id": "a1", "business_role": "yok_rol"}
        )
        return expected("start.bad_role", lang), detail_of(response, 422)
    if name == "bad_display":
        admin = client(world.app, "yonetici", lang)
        audit_id = ask_record(world, "a1", "Net ciro ne kadar?", username="yonetici")
        created = admin.post("/api/ready-questions", json={"audit_id": audit_id, "business_role": "*"})
        row_id = created.json()["ready_question"]["id"]
        response = admin.put(f"/api/ready-questions/{row_id}", json={"display": "resim"})
        return expected("start.bad_display", lang), detail_of(response, 422)
    admin = client(world.app, "yonetici", lang)
    row = card(world, "*", "Ortak kart")
    response = admin.put(f"/api/ready-questions/{row['id']}", json={"renk": "kirmizi"})
    return expected("start.unknown_field", lang, fields="renk"), detail_of(response, 422)


@pytest.mark.parametrize("lang", ["tr", "en"])
@pytest.mark.parametrize("name", REJECTIONS)
def test_a_rejection_reads_the_request_language(name, lang, world):
    wanted, detail = reject(name, lang, client(world.app, "satis1", lang), world)

    assert detail == wanted


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_a_failing_card_says_why_the_way_a_thread_says_it(lang, world):
    """Kartın yürümeyen cümlesi kataloğundur: sürücünün teknik cümlesi ekrana değil sohbete düşer."""
    card(world, "satis", "Kırık kart", BAD_SQL)

    body = client(world.app, "satis1", lang).get("/api/start").json()

    assert body["cards"][0]["error"] == expected("ask.fail.exec:sql", lang)


@pytest.mark.parametrize("lang", ["tr", "en"])
def test_opening_a_card_without_a_language_of_its_own_answers_in_the_request_language(lang, world):
    """Kartın sorusu dil söylemiyorsa cevabın dili soranın dilidir; not ve adım o dildedir (R8-6)."""
    pinned = card(world, "satis", "Dilsiz kart", TOTAL_SQL, question=NEUTRAL)

    response = client(world.app, "satis1", lang).post(f"/api/start/cards/{pinned['id']}/open")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "answered" and payload["answer_lang"] == lang
    assert payload["notes"] == [expected("start.open_note", lang)]
    assert payload["steps"][0]["summary"] == expected("start.open_step", lang, id=pinned["id"])


def test_no_turkish_literal_is_left_in_the_five_modules():
    for module, allow in MODULES:
        assert user_literals(module.__file__, allow=allow) == []
