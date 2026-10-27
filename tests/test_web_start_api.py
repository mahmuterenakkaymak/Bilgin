"""T321: başlangıç ekranının ve hazır soruların API kapıları (PLAN R7-17, R7-18).

Dünya ``tests/test_ready_approve.py`` ile aynı - kopya, import değil: kurulmuş sentetik ERP,
gerçek oturum, tmp uygulama dosyası. Ölçülen burada kapının kendisi: kartı kimin gördüğü oturumun
**iş rolü**, kartın yükü yürütücünün döndürdükleri, modelin çağrısı ise sıfır. Sayacın sıfır
kalması sözleşmenin kendisidir - ne ekranı yerleştirmek ne kartı açmak SQL yazdırır; kartın
cümlesi onayda yürüdüğü yerden bir daha yürür, konuşmanın 1. turu olur.

Kullanıcının hiçbir yanıtı ``sql`` taşımaz (R7-17): kart yükünü gösterir, cümlesini değil.
"""

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.app import asklog
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.schema_map import build
from nl2sql.web.app import create_app

DATASET = "synthetic_erp"
PAROLA = "Bilgin2026!erp"
NOT_ADMIN = "Bu işlem yalnız yöneticiye açık."
NO_CARD = "Hazır soru bulunamadı."

TOTAL_SQL = "SELECT SUM(STHAR_GCMIK * STHAR_NF) AS NET_CIRO FROM TBLSTHAR WHERE STHAR_HTUR = 'S'"
LIST_SQL = "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT WHERE IL = 'ANKARA' ORDER BY CARI_KOD"
MONTHLY_SQL = (
    "SELECT LEFT(STHAR_TARIH, 7) AS AY, SUM(STHAR_GCMIK * STHAR_NF) AS CIRO"
    " FROM TBLSTHAR WHERE STHAR_HTUR = 'S' GROUP BY LEFT(STHAR_TARIH, 7) ORDER BY AY"
)
BAD_SQL = "SELECT YOK_SUTUNU FROM TBLSTSABIT"
ALIAS_SQL = "SELECT COUNT(*) AS MUSTERI_KARTI FROM TBLCASABIT"
SCHEMA_SQL = "SELECT MAX(STHAR_NF) AS STHAR_NF FROM TBLSTHAR WHERE STHAR_HTUR = 'S'"


class CountingFake(fake.FakeLLM):
    """Ajan istemcisinin kendisi, bir de sayacı (R7-29): burada ölçülen tek şey kaç çağrı olduğu."""

    def __init__(self, script) -> None:
        super().__init__(script)
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        return super().chat(messages, tools)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    """Kurulmuş sentetik ERP bir kez: kartlar gerçek veride koşar, veriler testler arasında değişmez."""
    path = tmp_path_factory.mktemp("startapi") / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture
def world(db, tmp_path):
    """Bir uygulamanın dünyası: sayaçlı ajan, üç kimlik, tmp uygulama dosyası ve boş kartlar."""
    agent = CountingFake(fake.never_submit())
    session = open_session(
        dataset=DATASET,
        llm="fake",
        db_path=db,
        audit_path=tmp_path / "audit.jsonl",
        ask_log=tmp_path / "asks.jsonl",
        client_factory=lambda mode: agent,
    )
    users = UserStore(tmp_path / "bilgin.db")
    users.add_user("yonetici", PAROLA, "admin", "yonetim")
    users.add_user("satis1", PAROLA, "user", "satis")
    users.add_user("satin1", PAROLA, "user", "satin_alma")
    app = create_app(
        session, saved_path=tmp_path / "bilgin.db", static_dir=tmp_path / "static", users=users
    )
    return SimpleNamespace(app=app, session=session, users=users, agent=agent, store=app.state.ready)


def as_user(app, username) -> TestClient:
    """Aynı uygulamanın ayrı çerez kavanozu olan ikinci tarayıcısı, girişi yapılmış hâli."""
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": username, "password": PAROLA})
    assert response.status_code == 200, f"{username} giriş yapamadı: {response.status_code}"
    return client


def card(world, role, title, sql=TOTAL_SQL, display="number", approved=True) -> dict:
    """Onaylı bir hazır soru satırı: depoya HTTPden değil, doğrudan - kapı onu okumak için."""
    return world.store.add(DATASET, role, title, "Ne kadar?", sql, display, approved=approved)


def ask_record(world, audit_id, sql, username=None, question="Ne kadar?") -> str:
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


def assert_no_sql(payload) -> None:
    """Kullanıcının gördüğü hiçbir yanıt SQL taşımaz (R7-17): kart yalnız yükünü gösterir."""
    if isinstance(payload, dict):
        assert "sql" not in payload, payload
        for value in payload.values():
            assert_no_sql(value)
    elif isinstance(payload, list):
        for value in payload:
            assert_no_sql(value)


# ---------------------------------------------------------------------- yerleştirme (GET)


def test_start_renders_the_visible_cards_without_running_the_agent(world):
    mine = card(world, "satis", "Net ciro")
    shared = card(world, "*", "Aylık ciro", MONTHLY_SQL, "chart")
    card(world, "satin_alma", "Alış")
    client = as_user(world.app, "satis1")

    response = client.get("/api/start")

    assert response.status_code == 200
    body = response.json()
    assert [c["id"] for c in body["cards"]] == [mine["id"], shared["id"]]
    assert body["business_role"] == "satis"
    assert body["cards"][0]["value"] is not None and body["cards"][0]["label"]
    assert body["cards"][1]["chart"]["type"]
    assert all(c["refreshed_at"] for c in body["cards"])
    assert world.agent.calls == 0, "başlangıç ekranı modeli koşurmaz"
    assert_no_sql(body)


def test_a_number_card_reads_its_alias_the_way_a_thread_reads_it(world):
    card(world, "satis", "Müşteri sayısı", ALIAS_SQL)
    client = as_user(world.app, "satis1")

    body = client.get("/api/start").json()

    assert body["cards"][0]["value"] is not None
    assert body["cards"][0]["label"] == "Musteri karti"


def test_a_card_whose_column_is_a_schema_column_keeps_the_description(world):
    card(world, "satis", "En yüksek net birim fiyat", SCHEMA_SQL)
    client = as_user(world.app, "satis1")

    body = client.get("/api/start").json()

    assert body["cards"][0]["label"] == "Hareketin net birim fiyatı (KDV hariç)"


def test_each_business_role_gets_its_own_cards_plus_the_common_ones(world):
    card(world, "satis", "Satış kartı")
    card(world, "satin_alma", "Satın alma kartı")
    card(world, "*", "Ortak kart")
    card(world, "muhasebe", "Muhasebe kartı")

    seen = {
        name: sorted(c["title"] for c in as_user(world.app, name).get("/api/start").json()["cards"])
        for name in ("satis1", "satin1")
    }

    assert seen == {
        "satis1": ["Ortak kart", "Satış kartı"],
        "satin1": ["Ortak kart", "Satın alma kartı"],
    }


def test_an_unapproved_card_is_absent_and_its_open_and_refresh_are_404(world):
    draft = card(world, "*", "Taslak", approved=False)
    client = as_user(world.app, "satis1")

    assert client.get("/api/start").json()["cards"] == []
    opened = client.post(f"/api/start/cards/{draft['id']}/open")
    refreshed = client.post(f"/api/start/cards/{draft['id']}/refresh")

    assert opened.status_code == 404 and opened.json() == {"detail": NO_CARD}
    assert refreshed.status_code == 404, "onaysız satır hiçbir koşulda yürümez"


# --------------------------------------------------------------------------------- açmak


def test_opening_a_card_answers_as_turn_1_of_a_new_conversation_without_the_agent(world):
    pinned = card(world, "satis", "Ankara carileri", LIST_SQL, "table")
    client = as_user(world.app, "satis1")

    response = client.post(f"/api/start/cards/{pinned['id']}/open")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "answered" and payload["sql"] == LIST_SQL
    assert payload["conversation_id"] and payload["turn"] == 1
    assert payload["answer_text"] and payload["narration_source"]
    assert payload["rows"], "cevabın satırları yürütücünün döndürdükleridir"
    assert world.agent.calls == 0, "kartı açmak SQL yazdırmaz"

    thread = client.get(f"/api/conversations/{payload['conversation_id']}").json()
    assert [turn["n"] for turn in thread["turns"]] == [1]
    assert thread["turns"][0]["question"] == "Ne kadar?"
    history = client.get("/api/history").json()["history"][0]
    assert (history["audit_id"], history["turn"]) == (payload["audit_id"], 1)


def test_opening_another_roles_card_is_404_and_runs_nothing(world):
    pinned = card(world, "satin_alma", "Satın alma kartı")
    client = as_user(world.app, "satis1")

    response = client.post(f"/api/start/cards/{pinned['id']}/open")

    assert response.status_code == 404 and response.json() == {"detail": NO_CARD}
    assert not world.session.ask_log.exists(), "görünmeyen kart yürütülmez, satırı da bırakılmaz"


# ------------------------------------------------------------------------------ yenilemek


def test_refresh_reruns_the_card_and_the_second_one_inside_the_window_is_429(world):
    pinned = card(world, "satis", "Net ciro")
    client = as_user(world.app, "satis1")

    first = client.post(f"/api/start/cards/{pinned['id']}/refresh")
    second = client.post(f"/api/start/cards/{pinned['id']}/refresh")

    assert first.status_code == 200 and first.json()["card"]["refreshed_at"]
    assert_no_sql(first.json())
    assert second.status_code == 429
    assert second.json() == {
        "detail": f"Bu kart az önce yenilendi; {config.CARD_REFRESH_MIN_S} sn sonra yeniden deneyin."
    }


# ------------------------------------------------------------------------ kişisel kartlar


def test_a_user_pins_their_own_answer_and_no_one_else_can_delete_it(world):
    ask_record(world, "a1", LIST_SQL, username="satis1", question="Ankara carileri kim?")
    mine = as_user(world.app, "satis1")
    other = as_user(world.app, "satin1")

    pinned = mine.post(
        "/api/start/cards", json={"audit_id": "a1", "title": "Ankara carileri", "display": "table"}
    )

    assert pinned.status_code == 200
    card_body = pinned.json()["card"]
    assert (card_body["title"], card_body["display"], card_body["personal"]) == (
        "Ankara carileri",
        "table",
        True,
    )
    assert card_body["rows"], "kartın yükü yürütücünün döndürdükleridir"
    assert_no_sql(pinned.json())
    assert [c["id"] for c in other.get("/api/start").json()["cards"]] == []
    assert other.delete(f"/api/start/cards/{card_body['id']}").status_code == 404
    assert mine.delete(f"/api/start/cards/{card_body['id']}").status_code == 200
    assert mine.get("/api/start").json()["cards"] == []


def test_pinning_another_users_answer_is_404_and_a_role_card_is_not_ones_to_delete(world):
    ask_record(world, "a2", LIST_SQL, username="satin1", question="Ankara carileri kim?")
    role_card = card(world, "satis", "Satış kartı")
    mine = as_user(world.app, "satis1")

    refused = mine.post("/api/start/cards", json={"audit_id": "a2", "title": "Başkasının sorusu"})
    deleted = mine.delete(f"/api/start/cards/{role_card['id']}")

    assert refused.status_code == 404
    assert deleted.status_code == 404, "rol kartı kişinin panosundan silinmez"
    assert world.store.get(role_card["id"]) is not None


def test_the_seventh_personal_card_is_the_stores_409_sentence(world):
    mine = as_user(world.app, "satis1")
    for n in range(config.PERSONAL_CARDS):
        ask_record(world, f"k{n}", LIST_SQL, username="satis1", question=f"Soru {n}?")
        assert mine.post("/api/start/cards", json={"audit_id": f"k{n}"}).status_code == 200

    ask_record(world, "kk", LIST_SQL, username="satis1", question="Yedinci soru?")
    refused = mine.post("/api/start/cards", json={"audit_id": "kk"})

    assert refused.status_code == 409
    assert refused.json() == {
        "detail": f"En fazla {config.PERSONAL_CARDS} kişisel kart ekleyebilirsiniz."
    }


# --------------------------------------------------------------------- hazır sorular (admin)


def test_a_user_cannot_reach_the_ready_question_store(world):
    client = as_user(world.app, "satis1")

    for method, path, body in (
        ("GET", "/api/ready-questions", None),
        ("POST", "/api/ready-questions", {}),
        ("PUT", "/api/ready-questions/1", {}),
        ("DELETE", "/api/ready-questions/1", None),
    ):
        response = client.request(method, path, json=body)
        assert response.status_code == 403, f"{method} {path} kullanıcıya {response.status_code}"
        assert response.json() == {"detail": NOT_ADMIN}


def test_an_admin_approves_from_an_ask_lists_updates_and_deletes(world):
    ask_record(world, "a1", TOTAL_SQL, username="satis1", question="Net ciro ne kadar?")
    admin = as_user(world.app, "yonetici")

    created = admin.post(
        "/api/ready-questions",
        json={"audit_id": "a1", "title": "Net ciro", "business_role": "satis", "sql": "DROP TABLE X"},
    )

    assert created.status_code == 200
    row = created.json()["ready_question"]
    assert row["sql"] == TOTAL_SQL, "SQL istemciden değil kaydın cümlesinden gelir"
    assert (row["approved"], row["question"], row["display"]) == (True, "Net ciro ne kadar?", "number")
    assert [r["id"] for r in admin.get("/api/ready-questions").json()["ready_questions"]] == [row["id"]]
    assert admin.get("/api/ready-questions?pending=true").json()["ready_questions"] == []
    assert admin.get("/api/ready-questions?dataset=baska").json()["ready_questions"] == []

    moved = admin.put(
        f"/api/ready-questions/{row['id']}", json={"title": "Ciro", "approved": False, "business_role": "*"}
    )
    updated = moved.json()["ready_question"]
    assert (updated["title"], updated["approved"], updated["business_role"]) == ("Ciro", False, "*")
    assert [r["id"] for r in admin.get("/api/ready-questions?pending=true").json()["ready_questions"]] == [
        row["id"]
    ]

    assert admin.delete(f"/api/ready-questions/{row['id']}").json() == {"deleted": row["id"]}
    assert admin.get("/api/ready-questions").json()["ready_questions"] == []


def test_reapproving_moves_the_card_to_the_new_records_sql_and_a_dead_record_is_404(world):
    ask_record(world, "a1", TOTAL_SQL, username="satis1")
    ask_record(world, "a2", LIST_SQL, username="satis1")
    admin = as_user(world.app, "yonetici")
    row = admin.post("/api/ready-questions", json={"audit_id": "a1", "business_role": "*"}).json()[
        "ready_question"
    ]

    moved = admin.put(f"/api/ready-questions/{row['id']}", json={"audit_id": "a2"})

    assert moved.json()["ready_question"]["sql"] == LIST_SQL
    assert moved.json()["ready_question"]["audit_id"] == "a2"
    refused = admin.put(f"/api/ready-questions/{row['id']}", json={"audit_id": "yok"})
    assert refused.status_code == 404
    assert refused.json() == {"detail": "Bu soru geçmişte bulunamadı."}


def test_an_approval_that_does_not_run_is_422_with_the_executors_sentence_and_stores_nothing(world):
    ask_record(world, "a1", BAD_SQL, username="satis1")
    admin = as_user(world.app, "yonetici")

    refused = admin.post("/api/ready-questions", json={"audit_id": "a1", "business_role": "*"})

    assert refused.status_code == 422
    assert "YOK_SUTUNU" in refused.json()["detail"]
    assert admin.get("/api/ready-questions").json()["ready_questions"] == []
