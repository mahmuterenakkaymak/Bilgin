# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T318: hazır soru deposu (PLAN R7-17, R7-18, Contracts "ready question").

Kartın SQL'i satıra onaylayanın sorusundan yazılır; depo o SQL'i hiç üretmez ve değiştirmez.
Görünürlüğün kuralı şudur: kullanıcının kendi iş rolünün onaylı kartları + ``*`` kartları + kendi
kişisel kartları. Onaylanmamış satır ve başka kümenin satırı başlangıç ekranında hiç yoktur;
kişisel kartın sınırı ``PERSONAL_CARDS``, başkasının kişisel kartı silinmez (404 - kart yokmuş
gibi davranır, kim olduğunu sızdırmaz). Red cümleleri yazıyla burada durur.
"""

import pytest

from bilgin import config
from bilgin.start.ready import ReadyError, ReadyStore

CAP_REFUSED = "En fazla 6 kişisel kart ekleyebilirsiniz."
ROLE_REFUSED = "Geçersiz iş rolü."
DISPLAY_REFUSED = "Geçersiz görünüm: number, chart ya da table olmalı."
NOT_FOUND = "Hazır soru bulunamadı."

CONTRACT_FIELDS = {
    "id",
    "dataset",
    "business_role",
    "title",
    "question",
    "sql",
    "display",
    "position",
    "created_by",
    "approved",
    "audit_id",
    "created_at",
}


@pytest.fixture
def store(tmp_path):
    return ReadyStore(tmp_path / "app.db")


def _add(store, title, **fields):
    """Kısa ekleme: sözleşmenin zorunlu alanları sabit, gerisi çağırandan."""
    card = {
        "dataset": "erp",
        "business_role": "satis",
        "question": f"{title} kaç?",
        "sql": "SELECT 1",
        "display": "number",
        "approved": True,
        "audit_id": f"audit-{title}",
    } | fields
    return store.add(title=title, **card)


def _titles(cards):
    return [card["title"] for card in cards]


# ----------------------------------------------------------------------- sözleşme


def test_a_new_row_reads_back_with_exactly_the_contract_fields(store):
    card = _add(store, "Ciro", position=3, created_by="ayse", audit_id="A-7")

    assert set(card) == CONTRACT_FIELDS
    assert (card["dataset"], card["business_role"], card["title"]) == ("erp", "satis", "Ciro")
    assert (card["question"], card["sql"], card["display"]) == ("Ciro kaç?", "SELECT 1", "number")
    assert (card["position"], card["created_by"], card["audit_id"]) == (3, "ayse", "A-7")
    assert card["approved"] is True and isinstance(card["created_at"], str)
    assert store.get(card["id"]) == card


def test_an_unapproved_row_defaults_to_pending_and_no_creator(store):
    card = _add(store, "Stok", approved=False, business_role=None)

    assert (card["approved"], card["created_by"], card["position"]) == (False, None, 0)
    assert store.get(card["id"])["approved"] is False
    assert store.get(9999) is None


@pytest.mark.parametrize("role", ["Satis", "satici", "muhasebe ", "", "yonetim,muhasebe"])
def test_a_business_role_outside_the_plan_list_is_refused(store, role):
    with pytest.raises(ReadyError) as info:
        _add(store, "Ciro", business_role=role)

    assert (info.value.status, info.value.message) == (422, ROLE_REFUSED)
    assert store.list_all("erp") == []


@pytest.mark.parametrize("display", ["grafik", "Number", "tablo", ""])
def test_a_display_outside_the_plan_list_is_refused(store, display):
    with pytest.raises(ReadyError) as info:
        _add(store, "Ciro", display=display)

    assert (info.value.status, info.value.message) == (422, DISPLAY_REFUSED)
    assert store.list_all("erp") == []


# --------------------------------------------------------------- görünürlük: rol


def test_each_business_role_sees_its_own_cards_and_the_star_ones(store):
    for role in config.BUSINESS_ROLES:
        _add(store, f"{role} kartı", business_role=role)
    _add(store, "herkese açık", business_role="*")

    for role in config.BUSINESS_ROLES:
        assert _titles(store.list_for("erp", role, "ayse")) == [f"{role} kartı", "herkese açık"]


def test_a_role_never_sees_another_roles_card(store):
    _add(store, "satış kartı", business_role="satis")
    _add(store, "satın alma kartı", business_role="satin_alma")

    assert _titles(store.list_for("erp", "satis", "ayse")) == ["satış kartı"]
    assert _titles(store.list_for("erp", "satin_alma", "ayse")) == ["satın alma kartı"]


def test_a_user_without_a_business_role_sees_only_the_star_cards(store):
    _add(store, "satış kartı", business_role="satis")
    _add(store, "herkese açık", business_role="*")

    assert _titles(store.list_for("erp", None, "ayse")) == ["herkese açık"]


# --------------------------------------------------------- görünürlük: kişisel kart


def test_a_personal_card_shows_only_for_its_creator(store):
    _add(store, "ayse kişisel", business_role=None, created_by="ayse")

    assert _titles(store.list_for("erp", "satis", "ayse")) == ["ayse kişisel"]
    assert store.list_for("erp", "satis", "eren") == []
    assert store.list_for("erp", "muhasebe", "eren") == []
    assert store.list_for("erp", "satis") == []  # kullanıcı söylenmemiş: kişisel kart yok


def test_a_personal_card_of_an_unapproved_kind_is_not_on_the_screen(store):
    _add(store, "onaylı rol", business_role="satis")
    _add(store, "bekleyen rol", business_role="satis", approved=False)
    _add(store, "onaylı kişisel", business_role=None, created_by="ayse")
    _add(store, "bekleyen kişisel", business_role=None, created_by="ayse", approved=False)

    assert _titles(store.list_for("erp", "satis", "ayse")) == ["onaylı rol", "onaylı kişisel"]


def test_no_card_of_another_dataset_is_ever_listed(store):
    _add(store, "erp satışı", business_role="satis")
    _add(store, "erp herkese", business_role="*")
    _add(store, "erp kişisel", business_role=None, created_by="ayse")
    _add(store, "wwi satışı", dataset="wwi", business_role="satis")
    _add(store, "wwi herkese", dataset="wwi", business_role="*")
    _add(store, "wwi kişisel", dataset="wwi", business_role=None, created_by="ayse")

    assert _titles(store.list_for("erp", "satis", "ayse")) == ["erp satışı", "erp herkese", "erp kişisel"]
    assert _titles(store.list_for("wwi", "satis", "ayse")) == ["wwi satışı", "wwi herkese", "wwi kişisel"]
    assert _titles(store.list_all("wwi")) == ["wwi satışı", "wwi herkese", "wwi kişisel"]


def test_cards_come_in_position_order_and_then_by_id(store):
    _add(store, "son", position=20)
    _add(store, "ilk", position=1)
    _add(store, "ortası", position=10)
    _add(store, "aynı sıra", position=10)

    assert _titles(store.list_for("erp", "satis", "ayse")) == ["ilk", "ortası", "aynı sıra", "son"]


# ---------------------------------------------------------------- yönetici listesi


def test_list_all_shows_pending_and_approved_apart(store):
    _add(store, "onaylı", approved=True)
    _add(store, "bekleyen", approved=False)
    _add(store, "bekleyen kişisel", business_role=None, created_by="ayse", approved=False)

    assert _titles(store.list_all("erp")) == ["onaylı", "bekleyen", "bekleyen kişisel"]
    assert _titles(store.list_all("erp", pending=True)) == ["bekleyen", "bekleyen kişisel"]
    assert _titles(store.list_all("erp", pending=False)) == ["onaylı"]


# --------------------------------------------------------------------- kişisel sınır


def test_the_seventh_personal_card_is_refused_and_nothing_is_stored(store):
    for n in range(config.PERSONAL_CARDS):
        _add(store, f"kişisel {n}", business_role=None, created_by="ayse")

    with pytest.raises(ReadyError) as info:
        _add(store, "yedinci", business_role=None, created_by="ayse")

    assert (info.value.status, info.value.message) == (409, CAP_REFUSED)
    assert len(store.list_for("erp", "satis", "ayse")) == config.PERSONAL_CARDS


def test_the_personal_cap_belongs_to_a_user_not_to_the_dataset_or_the_role_cards(store):
    for n in range(config.PERSONAL_CARDS):
        _add(store, f"ayse {n}", business_role=None, created_by="ayse")
        _add(store, f"rol {n}", business_role="satis")

    assert _add(store, "eren 1", business_role=None, created_by="eren")["created_by"] == "eren"
    assert _add(store, "wwi 1", dataset="wwi", business_role=None, created_by="ayse")["dataset"] == "wwi"
    # ayse'nin erp ekranı: 6 kişisel + 6 rol kartı; eren'in ve wwi'nin kartları burada değil
    assert len(store.list_for("erp", "satis", "ayse")) == config.PERSONAL_CARDS * 2


def test_a_deleted_personal_card_frees_its_place_in_the_cap(store):
    cards = [_add(store, f"kişisel {n}", business_role=None, created_by="ayse") for n in range(config.PERSONAL_CARDS)]

    store.delete(cards[0]["id"], username="ayse")

    assert _add(store, "yeni kişisel", business_role=None, created_by="ayse")["title"] == "yeni kişisel"


# ---------------------------------------------------------------------------- silme


def test_another_users_personal_card_cannot_be_deleted_and_stays_put(store):
    card = _add(store, "ayse kişisel", business_role=None, created_by="ayse")

    with pytest.raises(ReadyError) as info:
        store.delete(card["id"], username="eren")

    assert (info.value.status, info.value.message) == (404, NOT_FOUND)
    assert store.get(card["id"]) == card


def test_a_creator_deletes_their_own_personal_card(store):
    card = _add(store, "ayse kişisel", business_role=None, created_by="ayse")

    store.delete(card["id"], username="ayse")

    assert store.get(card["id"]) is None
    assert store.list_for("erp", "satis", "ayse") == []


def test_a_role_card_deletes_for_the_admin_route_without_a_username(store):
    card = _add(store, "rol kartı", business_role="satis")

    store.delete(card["id"])

    assert store.get(card["id"]) is None


def test_deleting_an_unknown_row_is_404(store):
    with pytest.raises(ReadyError) as info:
        store.delete(4242, username="ayse")

    assert (info.value.status, info.value.message) == (404, NOT_FOUND)


# ------------------------------------------------------------------------ değiştirme


def test_an_update_changes_only_what_is_said(store):
    card = _add(store, "Ciro", position=2, display="number")

    changed = store.update(card["id"], title="Aylık ciro", approved=False, audit_id="A-9", sql="SELECT 2")

    assert changed["title"] == "Aylık ciro" and changed["approved"] is False
    assert (changed["audit_id"], changed["sql"]) == ("A-9", "SELECT 2")
    # söylenmeyen alanlar olduğu gibi kaldı
    assert (changed["question"], changed["display"], changed["position"]) == ("Ciro kaç?", "number", 2)
    assert (changed["dataset"], changed["business_role"], changed["created_at"]) == (
        card["dataset"],
        card["business_role"],
        card["created_at"],
    )
    assert store.get(card["id"]) == changed


def test_an_update_can_move_a_card_to_another_business_role_or_position(store):
    card = _add(store, "Ciro", business_role="satis", position=1)

    moved = store.update(card["id"], business_role="*", position=9)

    assert (moved["business_role"], moved["position"]) == ("*", 9)
    assert _titles(store.list_for("erp", "muhasebe", "ayse")) == ["Ciro"]


@pytest.mark.parametrize("fields", [{"business_role": "Satis"}, {"display": "grafik"}])
def test_an_update_outside_the_plan_values_is_refused_and_changes_nothing(store, fields):
    card = _add(store, "Ciro")

    with pytest.raises(ReadyError) as info:
        store.update(card["id"], **fields)

    assert info.value.status == 422
    assert store.get(card["id"]) == card


def test_an_update_of_an_unknown_row_is_404(store):
    with pytest.raises(ReadyError) as info:
        store.update(4242, title="Ciro")

    assert (info.value.status, info.value.message) == (404, NOT_FOUND)


# ------------------------------------------------------------------- aynı dosya, tek kapı


def test_the_store_shares_the_app_file_with_the_other_stores(tmp_path):
    from bilgin.auth.store import UserStore

    path = tmp_path / "app.db"
    card = ReadyStore(path).add("erp", "*", "Ciro", "Ciro kaç?", "SELECT 1", "number")

    assert UserStore(path).count_users() == 0  # aynı dosya, kullanıcı tablosuna dokunulmadı
    assert ReadyStore(path).get(card["id"]) == card  # ikinci açılış tabloyu bozmaz
