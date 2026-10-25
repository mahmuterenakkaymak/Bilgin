"""T226: giriş, kilitlenme ve oturum (PLAN R6-4).

Saat enjekte edilir: deneme penceresi, kilit süresi ve oturum ömrü gerçek zamanı beklemez.
Bilinmeyen ad, yanlış parola ve pasif kullanıcı aynı satırı verir; ham oturum anahtarı yalnız
çağırana döner, dosyada sha256 izi durur.
"""

import hashlib
import sqlite3
from datetime import datetime, timezone

import pytest

from nl2sql import config
from nl2sql.auth.store import LoginError, UserStore

PAROLA = "Bilgin2026!erp"
YENI_PAROLA = "BaskaParola2026!"
YANLIS = "YanlisParola2026!"
FAILED = "Kullanıcı adı ya da parola hatalı."


class Clock:
    """Testin çevirdiği saat: dakikaları ileri almak yeterli."""

    def __init__(self) -> None:
        self.ts = 1_764_000_000.0

    def __call__(self) -> float:
        return self.ts

    def advance(self, minutes: float) -> None:
        self.ts += minutes * 60


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def store(tmp_path, clock) -> UserStore:
    return UserStore(tmp_path / "app.db", clock=clock)


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _fail(store, username, password) -> LoginError:
    with pytest.raises(LoginError) as info:
        store.authenticate(username, password)
    return info.value


def _failures(store, username) -> list:
    with sqlite3.connect(store.path) as conn:
        return conn.execute(
            "SELECT ts FROM login_failures WHERE username = ?", (username,)
        ).fetchall()


def _sessions(store) -> list:
    with sqlite3.connect(store.path) as conn:
        return conn.execute("SELECT * FROM sessions").fetchall()


# ----------------------------------------------------------------------- hatalı giriş


def test_unknown_wrong_password_and_inactive_share_one_message(store):
    store.add_user("eren", PAROLA, "user")
    passive = store.add_user("pasif", PAROLA, "user")
    store.update_user(passive["id"], active=False)
    for name, password in (("yok.boyle", PAROLA), ("eren", YANLIS), ("pasif", PAROLA)):
        error = _fail(store, name, password)
        assert (error.status, error.message) == (401, FAILED)
    for name in ("yok.boyle", "eren", "pasif"):
        assert len(_failures(store, name)) == 1  # üçü de sayaca işler


def test_success_clears_failures_and_stamps_last_login(store, clock):
    user = store.add_user("eren", PAROLA, "admin")
    _fail(store, "EREN", YANLIS)
    assert len(_failures(store, "eren")) == 1
    clock.advance(1)
    signed_in = store.authenticate("EREN", PAROLA)
    assert signed_in == {**user, "last_login_at": _iso(clock.ts)}
    assert "password_hash" not in signed_in
    assert _failures(store, "eren") == []


# ------------------------------------------------------------------------- kilitlenme


def test_fifth_failure_locks_and_the_right_password_is_refused(store):
    store.add_user("eren", PAROLA, "user")
    for _ in range(config.LOGIN_MAX_FAILURES):
        assert _fail(store, "eren", YANLIS).status == 401
    error = _fail(store, "eren", PAROLA)
    assert error.status == 429
    assert error.message == (
        f"Çok fazla hatalı deneme. {config.LOCKOUT_MIN} dakika sonra yeniden deneyin."
    )


def test_lockout_counts_down_and_then_releases(store, clock):
    store.add_user("eren", PAROLA, "user")
    for _ in range(config.LOGIN_MAX_FAILURES):
        _fail(store, "eren", YANLIS)
    clock.advance(config.LOCKOUT_MIN - 1)
    error = _fail(store, "eren", PAROLA)
    assert (error.status, error.message) == (
        429,
        "Çok fazla hatalı deneme. 1 dakika sonra yeniden deneyin.",
    )
    clock.advance(1)
    assert store.authenticate("eren", PAROLA)["username"] == "eren"


def test_failures_older_than_the_window_do_not_count(store, clock):
    store.add_user("eren", PAROLA, "user")
    for _ in range(config.LOGIN_MAX_FAILURES - 1):
        _fail(store, "eren", YANLIS)
    clock.advance(config.LOGIN_WINDOW_MIN + 1)
    assert _fail(store, "eren", YANLIS).status == 401  # eşik yeniden sıfırdan sayılır
    assert store.authenticate("eren", PAROLA)["username"] == "eren"


def test_unknown_username_locks_like_a_known_one(store):
    for _ in range(config.LOGIN_MAX_FAILURES):
        assert _fail(store, "yok.boyle", YANLIS).status == 401
    assert _fail(store, "Yok.Boyle", PAROLA).status == 429  # ada göre kilit, ad küçük harfle katlanır
    assert len(_failures(store, "yok.boyle")) == config.LOGIN_MAX_FAILURES  # kilitli deneme sayılmaz


# ---------------------------------------------------------------------------- oturum


def test_session_is_valid_then_expired(store, clock):
    user = store.add_user("eren", PAROLA, "admin")
    token = store.create_session(user)
    assert store.session_user(token) == user
    clock.advance(config.SESSION_HOURS * 60 - 1)
    assert store.session_user(token) == user
    clock.advance(2)
    assert store.session_user(token) is None
    assert _sessions(store) == []  # süresi geçen satır okunurken silindi


def test_table_never_holds_the_raw_token(store):
    user = store.add_user("eren", PAROLA, "user")
    token = store.create_session(user)
    rows = _sessions(store)
    assert len(rows) == 1
    assert all(token not in str(value) for row in rows for value in row)
    stored, user_id, created, expires = rows[0]
    assert stored == hashlib.sha256(token.encode("utf-8")).hexdigest()
    assert user_id == user["id"]
    assert created < expires


def test_delete_session_removes_only_its_own_row(store):
    first = store.add_user("bir", PAROLA, "user")
    second = store.add_user("iki", PAROLA, "user")
    one = store.create_session(first)
    two = store.create_session(second)
    store.delete_session(one)
    assert store.session_user(one) is None
    assert store.session_user(two) == second
    store.delete_session("bilinmeyen-anahtar")  # tanımadığı anahtar için patlamaz
    assert store.session_user("bilinmeyen-anahtar") is None
    assert store.session_user("") is None


def test_deactivated_users_session_gives_none(store):
    user = store.add_user("eren", PAROLA, "user")
    token = store.create_session(user)
    with sqlite3.connect(store.path) as conn:  # update_user oturumu siler; satır elle pasifleşir
        conn.execute("UPDATE users SET active = 0 WHERE id = ?", (user["id"],))
    assert store.session_user(token) is None


def test_password_change_kills_existing_sessions(store):
    user = store.add_user("eren", PAROLA, "user")
    token = store.create_session(user)
    store.update_user(user["id"], password=YENI_PAROLA)
    assert store.session_user(token) is None
    assert store.authenticate("eren", YENI_PAROLA)["username"] == "eren"
