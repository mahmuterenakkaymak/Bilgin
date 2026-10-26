"""T319: hazır sorunun SQL'i bir soru kaydından gelir (PLAN R7-17).

İstemci hiç SQL göndermez: onay, soru günlüğündeki kaydın cümlesini aynı politika ve salt okunur
yürütücüden bir daha geçirir. Kapalı bir kolon (R4-7) orada da döner ve satıra hiçbir şey
yazılmaz; yürütücünün cümlesi neyse 422 onu söyler. Görünürlük R6-9'un süzgecidir: yönetici
``asklog._ALL`` ile kümenin her kaydını görür, kullanıcı yalnız kendi sorusunu - başkasının kaydı
onun için hiç yoktur, yani red 403 değil 404'tür. Görünüm uydurulmaz, yürüyen sonuçtan okunur:
tek sayı number, aylık seri chart, liste table.
"""

import copy

import pytest

from nl2sql import config
from nl2sql.app import asklog
from nl2sql.app.session import open_session
from nl2sql.engine.executor import LocalExecutor
from nl2sql.schema_map import build, doc
from nl2sql.start.ready import ReadyError, ReadyStore, approve_from_audit, personal_from_audit

NOT_FOUND = "Bu soru geçmişte bulunamadı."
DATASET = "synthetic_erp"

TOTAL_SQL = "SELECT SUM(STHAR_GCMIK * STHAR_NF) AS NET_CIRO FROM TBLSTHAR WHERE STHAR_HTUR = 'S'"
MONTHLY_SQL = (
    "SELECT LEFT(STHAR_TARIH, 7) AS AY, SUM(STHAR_GCMIK * STHAR_NF) AS CIRO"
    " FROM TBLSTHAR WHERE STHAR_HTUR = 'S' GROUP BY LEFT(STHAR_TARIH, 7) ORDER BY AY"
)
LIST_SQL = "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT WHERE IL = 'ANKARA' ORDER BY CARI_KOD"


@pytest.fixture
def world(tmp_path):
    """Kurulmuş sentetik ERP, gerçek oturum ve hazır soru deposu: model hiç çağrılmaz."""
    db = tmp_path / "test.db"
    build.build_db(config.SEED, db, db.with_suffix(".sql"))
    session = open_session(
        dataset=DATASET,
        llm="fake",
        db_path=db,
        audit_path=tmp_path / "audit.jsonl",
        ask_log=tmp_path / "asks.jsonl",
    )
    return session, ReadyStore(tmp_path / "app.db")


def _ask(session, audit_id, sql, question="Net ciro ne kadar?", username=None):
    """Soru günlüğünün satırı: ``sql`` o soruda gerçekten yürümüş cümledir (R5-4'ün alanları)."""
    asklog.record_ask(
        {
            "audit_id": audit_id,
            "dataset": DATASET,
            "question": question,
            "status": "answered" if sql else "failed",
            "sql": sql,
            "username": username,
        },
        session.ask_log,
    )
    return audit_id


def _close_column(session, table, column):
    """Şemanın kopyasında tek kolonu kapatan yürütücü (R4-7): oturum onu kullanmaya başlar."""
    closed = copy.deepcopy(session.schema)
    for row in closed["tables"]:
        if row["name"].upper() == table:
            for field in row["columns"]:
                if field["name"].upper() == column:
                    field["deny"] = True
    session.executor = LocalExecutor(
        db_path=session.db_path,
        allowlist=doc.allowlist(closed),
        audit_path=session.audit_path,
        pii_schema=closed,
    )


# --------------------------------------------------------------------- onay: kaydın SQL'i


def test_an_answered_ask_becomes_an_approved_card_carrying_the_records_sql(world):
    session, store = world
    _ask(session, "a1", TOTAL_SQL, username="eren")

    card = approve_from_audit(
        session, store, "a1", "admin", asklog._ALL, {"title": "Net ciro", "business_role": "muhasebe"}
    )

    assert card["sql"] == TOTAL_SQL, "kartın SQL'i istemciden değil kaydın cümlesinden gelir"
    assert card["approved"] is True and card["audit_id"] == "a1"
    assert (card["dataset"], card["business_role"], card["created_by"]) == (DATASET, "muhasebe", "admin")
    # söylenmeyen soru kayıttan, sıra kendi varsayılanından
    assert card["question"] == "Net ciro ne kadar?" and card["position"] == 0
    assert store.list_for(DATASET, "muhasebe", "ayse") == [card]


def test_a_card_can_be_moved_to_another_role_by_its_admin(world):
    session, store = world
    _ask(session, "a2", LIST_SQL, question="Ankara carileri kim?", username="ayse")

    card = approve_from_audit(
        session,
        store,
        "a2",
        "admin",
        asklog._ALL,
        {"title": "Ankara carileri", "business_role": "*", "position": 3},
    )

    assert (card["display"], card["business_role"], card["position"]) == ("table", "*", 3)
    assert [c["title"] for c in store.list_for(DATASET, "satis", "ayse")] == ["Ankara carileri"]


def test_an_unknown_audit_id_is_404_and_nothing_is_stored(world):
    session, store = world

    with pytest.raises(ReadyError) as info:
        approve_from_audit(session, store, "yok", "admin", asklog._ALL, {"business_role": "*"})

    assert (info.value.status, info.value.message) == (404, NOT_FOUND)
    assert store.list_all(DATASET) == []


def test_an_ask_that_was_never_answered_has_no_sql_to_approve(world):
    session, store = world
    _ask(session, "bos", "")

    with pytest.raises(ReadyError) as info:
        approve_from_audit(session, store, "bos", "admin", asklog._ALL, {"business_role": "*"})

    assert (info.value.status, info.value.message) == (404, NOT_FOUND)
    assert store.list_all(DATASET) == []


# ------------------------------------------------------------------------- kapalı kolon


def test_a_sql_reading_a_closed_column_is_refused_with_the_executors_sentence_and_stores_nothing(world):
    session, store = world
    _ask(session, "d1", TOTAL_SQL)
    _close_column(session, "TBLSTHAR", "STHAR_NF")

    with pytest.raises(ReadyError) as info:
        approve_from_audit(session, store, "d1", "admin", asklog._ALL, {"title": "Ciro", "business_role": "*"})

    assert info.value.status == 422
    assert "STHAR_NF" in info.value.message, "reddin cümlesi yürütücünün kapalı kolon cümlesidir"
    assert store.list_all(DATASET) == []


# ------------------------------------------------------------------- görünümün önerisi


@pytest.mark.parametrize(
    "sql, display",
    [(TOTAL_SQL, "number"), (MONTHLY_SQL, "chart"), (LIST_SQL, "table")],
    ids=["tek sayı", "aylık seri", "liste"],
)
def test_the_display_is_read_from_the_answered_result(world, sql, display):
    session, store = world
    _ask(session, "g1", sql, question="Sonuç ne?")

    card = approve_from_audit(session, store, "g1", "admin", asklog._ALL, {"business_role": "genel"})

    assert card["display"] == display


def test_a_display_the_caller_chose_wins_over_the_suggested_one(world):
    session, store = world
    _ask(session, "g2", MONTHLY_SQL, question="Aylık ciro ne?")

    card = approve_from_audit(
        session, store, "g2", "admin", asklog._ALL, {"display": "table", "business_role": "genel"}
    )

    assert card["display"] == "table"


# ------------------------------------------------------------------------- kişisel kart


def test_a_user_pins_their_own_ask_as_a_personal_card(world):
    session, store = world
    _ask(session, "k1", LIST_SQL, question="Ankara carileri kim?", username="ayse")

    card = personal_from_audit(session, store, "k1", "ayse", {"title": "Ankara carileri"})

    assert card["sql"] == LIST_SQL and card["approved"] is True
    assert card["business_role"] is None and card["created_by"] == "ayse"
    assert [c["title"] for c in store.list_for(DATASET, "satis", "ayse")] == ["Ankara carileri"]
    assert store.list_for(DATASET, "satis", "eren") == []


def test_a_user_cannot_make_a_card_from_another_users_ask(world):
    session, store = world
    _ask(session, "k2", LIST_SQL, question="Ankara carileri kim?", username="eren")

    with pytest.raises(ReadyError) as info:
        personal_from_audit(session, store, "k2", "ayse", {"title": "Ankara carileri"})

    assert (info.value.status, info.value.message) == (404, NOT_FOUND)
    assert store.list_all(DATASET) == []


def test_the_seventh_personal_card_from_an_ask_is_refused(world):
    session, store = world
    for n in range(config.PERSONAL_CARDS):
        _ask(session, f"k{n}", LIST_SQL, question=f"Soru {n}?", username="ayse")
        personal_from_audit(session, store, f"k{n}", "ayse", {"title": f"Kart {n}"})

    _ask(session, "kk", LIST_SQL, question="Yedinci soru?", username="ayse")
    with pytest.raises(ReadyError) as info:
        personal_from_audit(session, store, "kk", "ayse", {"title": "Yedinci kart"})

    assert info.value.status == 409
    assert len(store.list_for(DATASET, "satis", "ayse")) == config.PERSONAL_CARDS
