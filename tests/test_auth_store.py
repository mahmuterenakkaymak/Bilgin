"""T225: kullanıcı deposu (PLAN R6-3).

Depo kayıtlı sorularla aynı SQLite dosyasını kullanır: kendi tablolarını açar, ``saved``
tablosuna ve satırlarına dokunmaz. Dönen her sözlük sözleşme "User (public)" biçimidir, yani
``password_hash`` hiçbir yerden çıkmaz; parolalar yalnız scrypt karması olarak durur.
"""

import json
import sqlite3
from datetime import datetime, timezone

import pytest

from nl2sql.auth import passwords
from nl2sql.auth.store import UserError, UserStore
from nl2sql.web.saved import SavedStore

PAROLA = "Bilgin2026!erp"
YENI_PAROLA = "BaskaParola2026!"
LAST_ADMIN = "Son etkin yönetici pasifleştirilemez ya da rolü düşürülemez."


@pytest.fixture
def store(tmp_path):
    return UserStore(tmp_path / "app.db")


def _stored_hash(store, id):
    with sqlite3.connect(store.path) as conn:
        return conn.execute("SELECT password_hash FROM users WHERE id = ?", (id,)).fetchone()[0]


def _add_session(store, id):
    """Oturum satırını elle açar: token üretimi R6-4'ün, burada yalnız silme sınanır."""
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "INSERT INTO sessions (token_hash, user_id, created_at, expires_at)"
            " VALUES (?, ?, '2026-10-25T08:00:00+00:00', '2099-01-01T08:00:00+00:00')",
            (f"token-{id}", id),
        )


def _sessions(store, id):
    with sqlite3.connect(store.path) as conn:
        return conn.execute("SELECT token_hash FROM sessions WHERE user_id = ?", (id,)).fetchall()


# ----------------------------------------------------------------------- add/get/list


def test_add_get_list_and_count(store):
    created = store.add_user("eren", PAROLA, "admin")
    assert created["username"] == "eren"
    assert created["role"] == "admin"
    assert created["active"] is True
    assert created["last_login_at"] is None
    assert isinstance(created["id"], int)
    assert store.get_user("eren") == created
    assert store.get_by_id(created["id"]) == created
    assert store.count_users() == 1
    assert store.list_users() == [created]


def test_unknown_user_reads_as_none(store):
    assert store.get_user("yok") is None
    assert store.get_by_id(999) is None
    assert store.list_users() == []
    assert store.count_users() == 0


def test_list_is_ordered_by_username(store):
    for name in ("zeynep", "ahmet", "mehmet"):
        store.add_user(name, PAROLA, "user")
    assert [u["username"] for u in store.list_users()] == ["ahmet", "mehmet", "zeynep"]


def test_username_folded_to_lower(store):
    user = store.add_user("Eren.K", PAROLA, "user")
    assert user["username"] == "eren.k"
    assert store.get_user("EREN.K") == user
    assert store.count_users() == 1


def test_created_at_follows_the_injected_clock(tmp_path):
    ts = 1_764_000_000.0
    store = UserStore(tmp_path / "app.db", clock=lambda: ts)
    expected = datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")
    assert store.add_user("eren", PAROLA, "user")["created_at"] == expected


def test_two_stores_on_the_same_file(tmp_path):
    path = tmp_path / "app.db"
    UserStore(path).add_user("eren", PAROLA, "admin")
    assert UserStore(path).count_users() == 1  # CREATE IF NOT EXISTS: ikinci açılış veri taşımaz


def test_all_four_tables_are_created(tmp_path):
    store = UserStore(tmp_path / "app.db")
    with sqlite3.connect(store.path) as conn:
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"users", "sessions", "login_failures", "settings"} <= names


# ---------------------------------------------------------------------- refusals


def test_duplicate_username_409(store):
    store.add_user("eren", PAROLA, "admin")
    with pytest.raises(UserError) as info:
        store.add_user("eren", YENI_PAROLA, "user")
    assert (info.value.status, info.value.message) == (409, "Bu kullanıcı adı zaten var.")
    assert store.count_users() == 1


@pytest.mark.parametrize("name", ["", "ab", "a" * 33, "eren k", "eren!", "şaban", "ErEn:"])
def test_bad_username_422(store, name):
    with pytest.raises(UserError) as info:
        store.add_user(name, PAROLA, "user")
    assert info.value.status == 422
    assert "Kullanıcı adı" in info.value.message


@pytest.mark.parametrize("role", ["Admin", "yönetici", "", "superuser"])
def test_bad_role_422_on_add_and_update(store, role):
    with pytest.raises(UserError) as info:
        store.add_user("eren", PAROLA, role)
    assert (info.value.status, info.value.message) == (422, "Rol admin ya da user olmalı.")
    user = store.add_user("eren", PAROLA, "user")
    with pytest.raises(UserError) as info:
        store.update_user(user["id"], role=role)
    assert (info.value.status, info.value.message) == (422, "Rol admin ya da user olmalı.")
    assert store.get_by_id(user["id"]) == user


def test_short_password_422_on_add_and_update(store):
    message = "Parola en az 10 karakter olmalı."
    with pytest.raises(UserError) as info:
        store.add_user("eren", "Kisa1!", "user")
    assert (info.value.status, info.value.message) == (422, message)
    user = store.add_user("eren", PAROLA, "user")
    before = _stored_hash(store, user["id"])
    with pytest.raises(UserError) as info:
        store.update_user(user["id"], password="Kisa1!")
    assert (info.value.status, info.value.message) == (422, message)
    assert _stored_hash(store, user["id"]) == before


def test_update_unknown_user_404(store):
    with pytest.raises(UserError) as info:
        store.update_user(999, role="user")
    assert (info.value.status, info.value.message) == (404, "Kullanıcı bulunamadı.")


# ------------------------------------------------------------------- last admin guard


def test_last_active_admin_refuses_demote_and_deactivate(store):
    first = store.add_user("bir", PAROLA, "admin")
    second = store.add_user("iki", PAROLA, "admin")
    assert store.update_user(second["id"], role="user")["role"] == "user"  # artık tek yönetici bir
    for kwargs in ({"role": "user"}, {"active": False}, {"role": "user", "active": False}):
        with pytest.raises(UserError) as info:
            store.update_user(first["id"], **kwargs)
        assert (info.value.status, info.value.message) == (409, LAST_ADMIN)
    assert store.get_by_id(first["id"]) == first  # hiçbir değişiklik uygulanmadı


def test_second_active_admin_makes_both_allowed(store):
    first = store.add_user("bir", PAROLA, "admin")
    second = store.add_user("iki", PAROLA, "admin")
    third = store.add_user("dort", PAROLA, "admin")
    assert store.update_user(first["id"], role="user")["role"] == "user"
    assert store.update_user(second["id"], active=False)["active"] is False
    assert store.get_by_id(third["id"])["active"] is True  # üçüncü hâlâ etkin yönetici


def test_admin_promote_and_plain_user_changes_are_free(store):
    user = store.add_user("kullanici", PAROLA, "user")
    assert store.update_user(user["id"], active=False)["active"] is False
    assert store.update_user(user["id"], active=True)["active"] is True
    assert store.update_user(user["id"], role="admin")["role"] == "admin"


def test_inactive_admin_may_be_demoted(store):
    """Etkin olmayan yönetici "son etkin yönetici" değildir; düşürülebilir."""
    first = store.add_user("bir", PAROLA, "admin")
    store.add_user("iki", PAROLA, "admin")  # ikisi de etkinken bir pasifleşir, sonra tek kalır
    store.update_user(first["id"], active=False)
    assert store.update_user(first["id"], role="user")["role"] == "user"


# --------------------------------------------------------------------- password, sessions


def test_password_change_rehashes_and_keeps_the_rest(store):
    user = store.add_user("eren", PAROLA, "user")
    before = _stored_hash(store, user["id"])
    changed = store.update_user(user["id"], password=YENI_PAROLA)
    after = _stored_hash(store, user["id"])
    assert after != before
    assert passwords.verify_password(YENI_PAROLA, after) is True
    assert passwords.verify_password(PAROLA, after) is False
    assert {k: changed[k] for k in ("id", "username", "role", "active", "created_at")} == {
        k: user[k] for k in ("id", "username", "role", "active", "created_at")
    }


def test_password_change_and_deactivation_drop_sessions(store):
    store.add_user("yonetici", PAROLA, "admin")  # bekçi tamponu: eren düşürülüp pasifleşebilir
    user = store.add_user("eren", PAROLA, "user")
    _add_session(store, user["id"])
    store.update_user(user["id"], password=YENI_PAROLA)
    assert _sessions(store, user["id"]) == []

    _add_session(store, user["id"])
    store.update_user(user["id"], role="admin")  # rol değişimi oturumu düşürmez
    assert len(_sessions(store, user["id"])) == 1

    store.update_user(user["id"], active=False)
    assert _sessions(store, user["id"]) == []


def test_other_users_sessions_survive(store):
    first = store.add_user("bir", PAROLA, "admin")
    second = store.add_user("iki", PAROLA, "admin")
    _add_session(store, first["id"])
    _add_session(store, second["id"])
    store.update_user(first["id"], password=YENI_PAROLA)
    assert len(_sessions(store, second["id"])) == 1


# ------------------------------------------------------------------------------ settings


def test_settings_round_trip(store):
    assert store.get_setting("active_dataset") is None
    store.set_setting("active_dataset", "wwi")
    assert store.get_setting("active_dataset") == "wwi"
    store.set_setting("active_dataset", "synthetic_erp")  # üzerine yazar, çoğaltmaz
    assert store.get_setting("active_dataset") == "synthetic_erp"
    assert store.get_setting("baska") is None


# ------------------------------------------------------------- saved untouched, no hash


def test_saved_table_and_rows_in_the_same_file_are_untouched(tmp_path):
    path = tmp_path / "app.db"
    saved = SavedStore(path)
    saved.add("Kimin faturası yüksek?", mode="full", sql="SELECT 1", dataset="wwi")
    before = saved.list()

    store = UserStore(path)
    store.add_user("eren", PAROLA, "user")
    store.set_setting("active_dataset", "wwi")
    store.update_user(store.get_user("eren")["id"], active=False, password=YENI_PAROLA)

    assert saved.list() == before
    assert saved.list(dataset="wwi") == before
    with sqlite3.connect(path) as conn:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(saved)")]
    # R6-9 sonradan bir kolon eklerse eklerin sonunda kalır; UserStore hiçbirini silmez/değiştirmez.
    assert columns[:6] == ["id", "question", "mode", "sql", "dataset", "created_at"]


def test_no_returned_dict_carries_the_hash_or_the_plain_password(store):
    user = store.add_user("eren", PAROLA, "admin")
    store.add_user("kullanici", PAROLA, "user")
    store.update_user(user["id"], role="admin", active=True)
    users = [user, *store.list_users(), store.get_user("eren"), store.get_by_id(user["id"])]
    assert users
    for item in users:
        assert "password_hash" not in item
        assert set(item) == {"id", "username", "role", "active", "created_at", "last_login_at"}
        assert PAROLA not in json.dumps(item, ensure_ascii=False)
    assert PAROLA not in _stored_hash(store, user["id"])
