# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T285: konuşma deposu (PLAN R7-2).

Depo kayıtlı sorular ve kullanıcılarla aynı SQLite dosyasını kullanır: kendi iki tablosunu açar,
yanındaki ``saved`` ve ``users`` tablolarına dokunmaz. Bir konuşma tek kullanıcıya ve tek kümeye
aittir, o yüzden başkasının konuşması ``get``ten None olarak çıkar - API'nin 404'ü buradan okunur.
Saat verilebilir: listenin sırası ``updated_at`` ile ölçüldüğü için testler adımı kendisi sayar.
"""

import sqlite3

import pytest

from bilgin import config
from bilgin.app.conversations import ALL, ConversationStore
from bilgin.auth.store import UserStore
from bilgin.web.saved import SavedStore

PAROLA = "Bilgin2026!erp"


class Clock:
    """Her çağrıda bir dakika ilerleyen saat: iki işlemin güncellenme saati farklı düşsün."""

    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.t = start

    def __call__(self) -> float:
        self.t += 60.0
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def store(tmp_path, clock):
    return ConversationStore(tmp_path / "app.db", clock=clock)


def _turn(question="Kim en çok satışı yaptı?", **fields):
    turn = {
        "question": question,
        "status": "answered",
        "sql": "SELECT 1",
        "columns": ["CARİ", "TUTAR"],
        "summary": {"columns": ["CARİ", "TUTAR"], "row_count": 1, "rows": [["832", "1.234,56"]], "facts": []},
        "answer_text": "En çok satışı 832 numaralı cari yaptı.",
        "audit_id": "abc123def456",
    }
    turn.update(fields)
    return turn


def _tables(path):
    with sqlite3.connect(path) as conn:
        return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


# ------------------------------------------------------------------ create, title, id


def test_create_returns_unguessable_id_and_cuts_title(tmp_path):
    store = ConversationStore(tmp_path / "app.db", clock=Clock())
    id = store.create(username="eren", dataset="wwi", title="Son " + "s" * 200)
    assert len(id) == 32 and all(c in "0123456789abcdef" for c in id)  # uuid4().hex
    conversation = store.get(id)["conversation"]
    assert conversation["title"] == "Son " + "s" * (config.CONV_TITLE_CHARS - 4)
    assert conversation["username"] == "eren"
    assert conversation["dataset"] == "wwi"
    assert conversation["created_at"] == conversation["updated_at"]


def test_create_without_a_user_is_single_user_mode(tmp_path):
    store = ConversationStore(tmp_path / "app.db", clock=Clock())
    id = store.create(dataset="wwi", title="Merhaba")
    assert store.get(id)["conversation"]["username"] is None
    assert store.get(id, username="eren") is None  # tek kullanıcılı kayıt kimseye ait değil
    assert store.get(id, username=ALL) is not None


# ---------------------------------------------------------------------------- turns


def test_turns_are_numbered_from_one_and_bump_updated_at(store):
    id = store.create(username="eren", dataset="wwi", title="İlk soru")
    created = store.get(id)["conversation"]["updated_at"]

    assert store.add_turn(id, _turn("Kim en çok satışı yaptı?")) == 1
    assert store.add_turn(id, _turn("Bu müşteriye başka ne sattık?")) == 2

    thread = store.get(id)
    assert [turn["n"] for turn in thread["turns"]] == [1, 2]
    assert thread["turns"][0]["question"] == "Kim en çok satışı yaptı?"
    assert thread["conversation"]["updated_at"] > created
    # Contracts "StoredTurn": özet sözlük olarak döner, kolonlar JSON olarak değil.
    assert thread["turns"][1]["summary"]["rows"] == [["832", "1.234,56"]]
    assert set(thread["turns"][1]) == {
        "n",
        "question",
        "choice",
        "status",
        "sql",
        "answer_text",
        "audit_id",
        "created_at",
        "summary",
    }


def test_complete_turn_writes_on_the_pending_clarification_turn(store):
    id = store.create(username="eren", dataset="wwi", title="Hangi müşteri?")
    n = store.add_turn(
        id,
        _turn("Hangi müşteri?", status="needs_clarification", sql=None, answer_text="Hangi müşteriyi kastettin?"),
    )
    assert n == 1
    assert store.complete_turn(id, 1, _turn(choice="832 - Tailspin Toys")) == 1

    turns = store.get(id)["turns"]
    assert len(turns) == 1  # seçim yeni tur açmadı, bekleyen turu tamamladı
    assert turns[0]["n"] == 1 and turns[0]["status"] == "answered"
    assert turns[0]["choice"] == "832 - Tailspin Toys"
    assert turns[0]["sql"] == "SELECT 1"

    # Artık bekleyen netleştirme değil: ikinci bir tamamlama yok, sıra 2'ye geçer.
    assert store.complete_turn(id, 1, _turn(choice="yok")) is None
    assert store.get(id)["turns"][0]["choice"] == "832 - Tailspin Toys"
    assert store.add_turn(id, _turn("Peki geçen ayla kıyasla?")) == 2


# ----------------------------------------------------------------------- ownership


def test_another_users_conversation_does_not_exist(store):
    id = store.create(username="eren", dataset="wwi", title="Benim sorum")
    assert store.get(id, username="eren") is not None
    assert store.get(id, username="ayse") is None
    assert store.get(id, username=ALL) is not None  # yönetici görünümü
    assert store.get("0" * 32, username=ALL) is None


def test_conversation_of_another_dataset_does_not_exist(store):
    id = store.create(username="eren", dataset="wwi", title="WWI sorusu")
    assert store.get(id, username="eren", dataset="wwi") is not None
    assert store.get(id, username="eren", dataset="synthetic_erp") is None
    assert store.get(id, username="eren") is not None  # küme sorulmamışsa filtre yok


# ---------------------------------------------------------------------------- list


def test_list_is_newest_updated_first_with_turn_counts(store):
    first = store.create(username="eren", dataset="wwi", title="Birinci")
    second = store.create(username="eren", dataset="wwi", title="İkinci")
    assert [item["id"] for item in store.list(username="eren", dataset="wwi")] == [second, first]

    store.add_turn(first, _turn())
    store.add_turn(first, _turn())

    items = store.list(username="eren", dataset="wwi")
    assert [item["id"] for item in items] == [first, second]  # bir tur eklemek konuşmayı en üste taşır
    assert [item["turns"] for item in items] == [2, 0]
    assert set(items[0]) == {"id", "title", "dataset", "created_at", "updated_at", "turns"}


def test_list_keeps_other_users_and_datasets_out(store):
    mine = store.create(username="eren", dataset="wwi", title="Benim")
    store.create(username="ayse", dataset="wwi", title="Onun")
    elsewhere = store.create(username="eren", dataset="synthetic_erp", title="Başka küme")

    assert [item["id"] for item in store.list(username="eren", dataset="wwi")] == [mine]
    # Küme filtresi söylenmezse kullanıcının öteki kümesindeki konuşması da gelir.
    assert [item["id"] for item in store.list(username="eren")] == [elsewhere, mine]
    assert len(store.list()) == 3  # ALL = herkesin konuşması (yönetici)


# -------------------------------------------------------------------------- delete


def test_delete_removes_the_turns_and_refuses_a_stranger(store):
    id = store.create(username="eren", dataset="wwi", title="Silinecek")
    store.add_turn(id, _turn())
    other = store.create(username="ayse", dataset="wwi", title="Durmalı")
    store.add_turn(other, _turn())

    assert store.delete(id, username="ayse") is False
    assert store.get(id, username=ALL) is not None

    assert store.delete(id, username="eren") is True
    assert store.get(id, username=ALL) is None
    with sqlite3.connect(store.path) as conn:
        left = conn.execute("SELECT COUNT(*) FROM turns WHERE conversation_id = ?", (id,)).fetchone()[0]
    assert left == 0  # tur satırları konuşmayla birlikte gitti
    assert store.delete(id, username="eren") is False
    assert store.get(other, username=ALL) is not None


# ------------------------------------------------------------------------ history


def test_last_turns_keeps_answered_turns_oldest_first(store):
    id = store.create(username="eren", dataset="wwi", title="Zincir")
    store.add_turn(id, _turn("Birinci"))
    store.add_turn(id, _turn("İkinci", status="failed", answer_text="Sunucuya ulaşılamadı."))
    store.add_turn(id, _turn("Üçüncü", status="needs_clarification"))
    store.add_turn(id, _turn("Dördüncü"))
    store.add_turn(id, _turn("Beşinci"))

    history = store.last_turns(id, 2)
    assert [turn["n"] for turn in history] == [4, 5]  # son ikisi, eskiden yeniye
    assert set(history[0]) == {"n", "question", "choice", "sql", "summary"}
    assert history[0]["summary"]["row_count"] == 1

    assert [turn["n"] for turn in store.last_turns(id, 10)] == [1, 4, 5]  # hata ve netleştirme yok
    assert store.last_turns(id, 0) == []


# ------------------------------------------------------------- shared app database


def test_tables_join_the_saved_and_users_file_without_touching_them(tmp_path):
    path = tmp_path / "bilgin.db"
    saved = SavedStore(path)
    saved.add("Kim en çok satışı yaptı?", sql="SELECT 1", dataset="wwi", username="eren")
    users = UserStore(path)
    users.add_user("eren", PAROLA, "admin")

    store = ConversationStore(path)
    id = store.create(username="eren", dataset="wwi", title="Ortak dosya")
    store.add_turn(id, _turn())

    assert {"saved", "users", "conversations", "turns"} <= _tables(path)
    assert [item["question"] for item in saved.list()] == ["Kim en çok satışı yaptı?"]
    assert [user["username"] for user in users.list_users()] == ["eren"]
    assert store.get(id, username="eren")["turns"][0]["n"] == 1

    # Aynı dosya yeniden açıldığında tablolar yerinde ve satırlar korunur.
    again = ConversationStore(path)
    assert again.get(id, username="eren")["conversation"]["title"] == "Ortak dosya"
