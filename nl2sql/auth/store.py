"""Kullanıcı hesapları: uygulamanın kendi SQLite dosyasında users ve settings.

Parola kolonunda yalnız ``auth.passwords`` karması durur; dışarı giden her sözlük sözleşme
"User (public)" alanlarıdır, yani ``password_hash`` hiçbir yerde taşınmaz. Kayıtlı sorularla
aynı dosya, aynı kısa ömürlü bağlantı biçimi: FastAPI yol koşucuları iş parçacıkları arasında
dolaştığı için tek bağlantıyı paylaşmak güvenli olmaz.
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from nl2sql import config
from nl2sql.auth.passwords import check_new_password, hash_password

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")
ROLES = ("admin", "user")

# Sözleşme "User (public)": okuma sorgusu hash'i hiç seçmez, o yüzden yanlışlıkla da çıkmaz.
_COLUMNS = ("id", "username", "role", "active", "created_at", "last_login_at")
_SELECT = ", ".join(_COLUMNS)

DUPLICATE_MESSAGE = "Bu kullanıcı adı zaten var."
NOT_FOUND_MESSAGE = "Kullanıcı bulunamadı."
LAST_ADMIN_MESSAGE = "Son etkin yönetici pasifleştirilemez ya da rolü düşürülemez."
BAD_NAME_MESSAGE = (
    "Kullanıcı adı 3-32 karakter olmalı ve yalnız küçük harf, rakam, . _ - içerebilir."
)
BAD_ROLE_MESSAGE = "Rol admin ya da user olmalı."

_CREATE = (
    """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_login_at TEXT
)
""",
    """
CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,
  user_id INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
)
""",
    """
CREATE TABLE IF NOT EXISTS login_failures (
  username TEXT NOT NULL,
  ts REAL NOT NULL
)
""",
    """
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT
)
""",
)


class UserError(Exception):
    """Kullanıcı işleminin reddi: mesajı ve HTTP durumuyla birlikte taşınır (R6-3)."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class UserStore:
    """``users`` ve ``settings`` tablolarının tek kapısı; oturum ve kilitlenme aynı dosyada."""

    def __init__(
        self, path: str | Path | None = None, clock: Callable[[], float] = time.time
    ) -> None:
        # Yolu çağıran söylemezse R6-1'in okuyucusu: testler atık dosyada koşar, data/bilgin.db'ye dokunulmaz.
        self.path = Path(config.app_db_path() if path is None else path)
        self.clock = clock
        with _connect(self.path) as conn:
            for ddl in _CREATE:
                conn.execute(ddl)

    # ------------------------------------------------------------------ users

    def add_user(self, username: str, password: str, role: str) -> dict:
        """Kullanıcıyı açar ve public sözlüğünü döndürür; ad küçük harfe katlanır."""
        name = str(username).lower()
        if not USERNAME_RE.match(name):
            raise UserError(BAD_NAME_MESSAGE, 422)
        if role not in ROLES:
            raise UserError(BAD_ROLE_MESSAGE, 422)
        refused = check_new_password(password)
        if refused:
            raise UserError(refused, 422)
        with _connect(self.path) as conn:
            try:
                conn.execute(
                    "INSERT INTO users (username, password_hash, role, active, created_at)"
                    " VALUES (?, ?, ?, 1, ?)",
                    (name, hash_password(password), role, self._now_iso()),
                )
            except sqlite3.IntegrityError:
                raise UserError(DUPLICATE_MESSAGE, 409) from None
        return self.get_user(name)

    def get_user(self, username: str) -> dict | None:
        """Ada göre kullanıcı; böyle bir kullanıcı yoksa None."""
        # ASSUMPTION: okuma yolları yoklukta None döner, 404'ü çağıran kendi verir (authenticate de None bekler).
        return self._one(f"SELECT {_SELECT} FROM users WHERE username = ?", (str(username).lower(),))

    def get_by_id(self, id: int) -> dict | None:
        """Kimliğe göre kullanıcı; böyle bir kullanıcı yoksa None."""
        return self._one(f"SELECT {_SELECT} FROM users WHERE id = ?", (id,))

    def list_users(self) -> list[dict]:
        """Bütün kullanıcılar, ada göre; CLI ``user list`` ve yönetici ekranı buradan okur."""
        with _connect(self.path) as conn:
            rows = conn.execute(f"SELECT {_SELECT} FROM users ORDER BY username").fetchall()
        return [_public(row) for row in rows]

    def count_users(self) -> int:
        """Kullanıcı sayısı (bootstrap "kullanıcı var mı" sorusu buradan okunur)."""
        with _connect(self.path) as conn:
            return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]

    def update_user(
        self, id: int, role: str | None = None, active: bool | None = None, password: str | None = None
    ) -> dict:
        """Rolü, etkinliği ve/veya parolayı değiştirir; son etkin yöneticiyi korur."""
        user = self.get_by_id(id)
        if user is None:
            raise UserError(NOT_FOUND_MESSAGE, 404)
        if role is not None and role not in ROLES:
            raise UserError(BAD_ROLE_MESSAGE, 422)
        refused = check_new_password(password) if password is not None else None
        if refused:
            raise UserError(refused, 422)
        if user["role"] == "admin" and user["active"] and (role == "user" or active is False):
            if self._count_active_admins() <= 1:
                raise UserError(LAST_ADMIN_MESSAGE, 409)

        sets, args = [], []
        if role is not None:
            sets.append("role = ?")
            args.append(role)
        if active is not None:
            sets.append("active = ?")
            args.append(1 if active else 0)
        if password is not None:
            sets.append("password_hash = ?")
            args.append(hash_password(password))
        if sets:
            with _connect(self.path) as conn:
                conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", (*args, id))
                if password is not None or active is False:
                    conn.execute("DELETE FROM sessions WHERE user_id = ?", (id,))
        return self.get_by_id(id)

    # --------------------------------------------------------------- settings

    def get_setting(self, key: str) -> str | None:
        """Ayarın değeri; böyle bir anahtar yoksa None (sözleşme "settings")."""
        with _connect(self.path) as conn:
            row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_setting(self, key: str, value: str) -> None:
        """Ayarı yazar ya da üzerine yazar."""
        with _connect(self.path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
            )

    # --------------------------------------------------------------- internals

    def _now_iso(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(timespec="seconds")

    def _count_active_admins(self) -> int:
        with _connect(self.path) as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM users WHERE role = 'admin' AND active = 1"
            ).fetchone()[0]

    def _one(self, sql: str, args: tuple) -> dict | None:
        with _connect(self.path) as conn:
            row = conn.execute(sql, args).fetchone()
        return _public(row) if row else None


def _public(row: tuple) -> dict:
    user = dict(zip(_COLUMNS, row))
    user["active"] = bool(user["active"])
    return user


@contextlib.contextmanager
def _connect(path: Path):
    """Kısa ömürlü bağlantı: gereken klasör açılır, başarılı işlem yerine konur."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()
