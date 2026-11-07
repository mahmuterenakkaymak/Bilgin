# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T227: kayıtlı sorular kullanıcının (PLAN R6-9, Contracts "saved row (ext.)").

Run 5'in dosyası yerinde büyür: ``username`` kolonu sonradan eklenir, eski satır NULL kalır ve
okunmaya devam eder. ``ALL`` yöneticinin görünümüdür — herkesin kaydı, NULL'lar da dahil. Kaydın
anahtarı ise Run 5'te neyse odur: kullanıcı kolonu yalnız kapılarda sorulur, içinden dönmez.
"""

import sqlite3

import pytest

from bilgin.web.saved import ALL, SavedStore

# Run 5'in sözleşmesi değişmez.
SAVED_KEYS = {"id", "question", "mode", "sql", "dataset", "created_at"}

# Run 5'in CREATE TABLE'ı aynen: göç, bu cümleyle kurulmuş bir dosyanın üstünde sınanır.
_CREATE_RUN5 = """
CREATE TABLE saved (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  question TEXT NOT NULL,
  mode TEXT,
  sql TEXT,
  dataset TEXT,
  created_at TEXT NOT NULL
)
"""


@pytest.fixture
def path(tmp_path):
    return tmp_path / "bilgin.db"


def run5_file(path):
    """Run 5'in dosyası: username kolonu yok, içerde bir eski kayıt var."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    with conn:
        conn.execute(_CREATE_RUN5)
        conn.execute(
            "INSERT INTO saved (question, mode, sql, dataset, created_at) VALUES (?, ?, ?, ?, ?)",
            ("Eski soru", "full", "SELECT 1", "mini", "2026-10-01T00:00:00+00:00"),
        )
    conn.close()
    return path


def columns(path):
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(saved)")}
    finally:
        conn.close()


def stored_username(path, id):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("SELECT username FROM saved WHERE id = ?", (id,)).fetchone()[0]
    finally:
        conn.close()


def questions(items):
    return [item["question"] for item in items]


# ------------------------------------------------------------------ göç


def test_a_run5_file_gains_the_column_and_keeps_its_row(path):
    run5_file(path)

    store = SavedStore(path)
    rows = store.list()

    assert "username" in columns(path)
    assert len(rows) == 1
    assert sorted(rows[0]) == sorted(SAVED_KEYS)
    assert (rows[0]["question"], rows[0]["mode"], rows[0]["sql"], rows[0]["dataset"]) == (
        "Eski soru", "full", "SELECT 1", "mini",
    )
    assert rows[0]["created_at"] == "2026-10-01T00:00:00+00:00"
    assert stored_username(path, rows[0]["id"]) is None


def test_an_old_row_shows_only_under_ALL(path):
    run5_file(path)
    store = SavedStore(path)

    assert questions(store.list(username="eren")) == []
    assert questions(store.list(username=ALL)) == ["Eski soru"]


def test_a_new_file_already_has_the_column(path):
    SavedStore(path).add("Yeni dosya", dataset="mini", username="eren")

    assert "username" in columns(path)
    assert stored_username(path, 1) == "eren"


# ------------------------------------------------------------------ kapılar


def test_a_user_lists_only_their_own_rows(path):
    store = SavedStore(path)
    store.add("Erenin sorusu", dataset="mini", username="eren")
    store.add("Kendisinin", dataset="mini", username="kymak")

    assert questions(store.list(username="eren")) == ["Erenin sorusu"]
    assert questions(store.list(username="kymak")) == ["Kendisinin"]


def test_ALL_sees_every_users_row_newest_first(path):
    store = SavedStore(path)
    first = store.add("Bir", username="eren")
    second = store.add("İki", username="kymak")

    assert [item["id"] for item in store.list()] == [second["id"], first["id"]]
    assert questions(store.list(username=ALL)) == ["İki", "Bir"]


def test_the_dataset_and_username_filters_combine(path):
    store = SavedStore(path)
    store.add("Mini, Eren", dataset="mini", username="eren")
    store.add("Mini, Kymak", dataset="mini", username="kymak")
    store.add("WWI, Eren", dataset="wwi", username="eren")

    assert questions(store.list("mini", username="eren")) == ["Mini, Eren"]
    assert questions(store.list("mini")) == ["Mini, Kymak", "Mini, Eren"]


def test_a_saved_item_never_carries_the_username(path):
    item = SavedStore(path).add("Anahtarlar", dataset="mini", username="eren")

    assert sorted(item) == sorted(SAVED_KEYS)
    assert "username" not in item


# ------------------------------------------------------------------ silme


def test_delete_refuses_another_users_row(path):
    store = SavedStore(path)
    item = store.add("Erenin kaydı", dataset="mini", username="eren")

    assert store.delete(item["id"], username="kymak") is False
    assert questions(store.list()) == ["Erenin kaydı"]
    assert store.delete(item["id"], username="eren") is True
    assert store.list() == []


def test_delete_without_a_username_removes_any_row(path):
    store = SavedStore(path)
    item = store.add("Yönetici siler", dataset="mini", username="eren")

    assert store.delete(item["id"]) is True
    assert store.delete(item["id"], username="eren") is False
