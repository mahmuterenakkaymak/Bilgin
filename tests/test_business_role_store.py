"""T316: kullanıcının iş rolü (PLAN R7-16, Contracts "User (ext.)").

İş rolü Run 6'nın yetki rolünden (admin/user) ayrı bir şeydir: satışçı da yönetici olabilir.
Depo eski dosyayı ilk açışında kolonu ALTER TABLE ile sona ekler, o yüzden Run 6'da yazılmış
satırların hiçbiri boş kalmaz. Red cümlesi yazıyla burada durur: ekranda okunan satır değişmesin.
"""

import sqlite3

import pytest

from nl2sql import config
from nl2sql.auth.passwords import hash_password
from nl2sql.auth.store import UserError, UserStore

PAROLA = "Bilgin2026!erp"
REFUSED = "Geçersiz iş rolü."

# Run 6'da kullanıcı tablosu buydu: iş rolü kolonu hiç yoktu.
_OLD_USERS = """
CREATE TABLE users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_login_at TEXT
)
"""


@pytest.fixture
def store(tmp_path):
    return UserStore(tmp_path / "app.db")


def _old_file(path, names):
    """Kolonsuz kullanıcı tablosunu elle açar: göçün sınandığı şey tam olarak bu dosya."""
    with sqlite3.connect(path) as conn:
        conn.execute(_OLD_USERS)
        for name in names:
            conn.execute(
                "INSERT INTO users (username, password_hash, role, active, created_at)"
                " VALUES (?, ?, 'user', 1, '2026-10-20T08:00:00+00:00')",
                (name, hash_password(PAROLA)),
            )


def _columns(path):
    with sqlite3.connect(path) as conn:
        return [row[1] for row in conn.execute("PRAGMA table_info(users)")]


# ------------------------------------------------------------------------------ göç


def test_an_old_users_table_gains_the_column_and_every_row_reads_genel(tmp_path):
    path = tmp_path / "app.db"
    _old_file(path, ("eren", "ayse"))

    store = UserStore(path)

    assert _columns(path)[-1] == "business_role"
    assert [user["business_role"] for user in store.list_users()] == ["genel", "genel"]
    assert store.get_user("eren")["business_role"] == config.DEFAULT_BUSINESS_ROLE
    assert store.authenticate("eren", PAROLA)["business_role"] == "genel"  # eski parola da çalışır


def test_the_migration_runs_once_and_keeps_what_was_set(tmp_path):
    path = tmp_path / "app.db"
    _old_file(path, ("eren",))
    store = UserStore(path)
    store.update_user(store.get_user("eren")["id"], business_role="satis")

    assert UserStore(path).get_user("eren")["business_role"] == "satis"


# ------------------------------------------------------------------------ set / get


def test_a_new_user_defaults_to_genel_and_an_explicit_role_is_kept(store):
    default = store.add_user("eren", PAROLA, "user")
    satis = store.add_user("ayse", PAROLA, "admin", business_role="satis")

    assert default["business_role"] == config.DEFAULT_BUSINESS_ROLE
    assert satis["business_role"] == "satis"
    assert store.get_user("ayse") == satis
    assert {user["username"]: user["business_role"] for user in store.list_users()} == {
        "ayse": "satis",
        "eren": "genel",
    }


@pytest.mark.parametrize("role", list(config.BUSINESS_ROLES))
def test_every_plan_role_can_be_set_and_read_back(store, role):
    user = store.add_user("eren", PAROLA, "user")

    changed = store.update_user(user["id"], business_role=role)

    assert changed["business_role"] == role
    assert store.get_by_id(user["id"])["business_role"] == role
    # İş rolü yetki rolünün yerine geçmez: ötekileri olduğu gibi kalır.
    assert changed["role"] == user["role"]
    assert changed["created_at"] == user["created_at"]


def test_an_unsaid_business_role_stays_as_it_is(store):
    user = store.add_user("eren", PAROLA, "user", business_role="muhasebe")

    assert store.update_user(user["id"], active=False)["business_role"] == "muhasebe"


# ---------------------------------------------------------------------------- reddi


@pytest.mark.parametrize("value", ["Satis", "satici", "muhasebe ", "", "yonetim,muhasebe"])
def test_a_role_outside_the_plan_list_is_refused_on_add_and_update(store, value):
    with pytest.raises(UserError) as info:
        store.add_user("eren", PAROLA, "user", business_role=value)
    assert (info.value.status, info.value.message) == (422, REFUSED)
    assert store.count_users() == 0

    user = store.add_user("eren", PAROLA, "user")
    with pytest.raises(UserError) as info:
        store.update_user(user["id"], business_role=value)
    assert (info.value.status, info.value.message) == (422, REFUSED)
    assert store.get_by_id(user["id"]) == user  # hiçbir değişiklik uygulanmadı
