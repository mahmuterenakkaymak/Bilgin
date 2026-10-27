"""Kullanıcı hesapları: uygulamanın kendi SQLite dosyasında users ve settings.

Parola kolonunda yalnız ``auth.passwords`` karması durur; dışarı giden her sözlük sözleşme
"User (public)" alanlarıdır, yani ``password_hash`` hiçbir yerde taşınmaz. Kayıtlı sorularla
aynı dosya, aynı kısa ömürlü bağlantı biçimi: FastAPI yol koşucuları iş parçacıkları arasında
dolaştığı için tek bağlantıyı paylaşmak güvenli olmaz.
"""

from __future__ import annotations

import contextlib
import hashlib
import math
import re
import secrets
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from nl2sql import config
from nl2sql.auth.passwords import check_new_password, hash_password, verify_password
from nl2sql.i18n import t

USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")
ROLES = ("admin", "user")

# Sözleşme "User (public)" ve Run 7 "User (ext.)": okuma sorgusu hash'i hiç seçmez, o yüzden yanlışlıkla da çıkmaz.
_COLUMNS = (
    "id",
    "username",
    "role",
    "active",
    "created_at",
    "last_login_at",
    "business_role",
    "lang",
)
_SELECT = ", ".join(_COLUMNS)

# R8-5: her reddin cümlesi kataloğun ``auth.*`` satırıdır ve bir red onu anahtarıyla taşır.
# ASSUMPTION: bu üç adı cli/main.py ve testleri import eder, o yüzden anahtarlarını değil program
# dilinin cümlesini taşırlar.
DUPLICATE_MESSAGE = t("auth.duplicate")
NOT_FOUND_MESSAGE = t("auth.user_not_found")
LAST_ADMIN_MESSAGE = t("auth.last_admin")

_CREATE = (
    f"""
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin', 'user')),
  active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  last_login_at TEXT,
  lang TEXT,
  business_role TEXT NOT NULL DEFAULT '{config.DEFAULT_BUSINESS_ROLE}'
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
    """Kullanıcı işleminin reddi: kataloğun anahtarı, parametreleri ve HTTP durumuyla birlikte (R6-3).

    ``message`` eski çağıranların okuduğu cümledir ve her zaman Türkçedir; HTTP yolu cümleyi isteğin
    dilinden kendisi kurar, yani anahtarı ve parametrelerini olduğu gibi taşır (R8-5).
    """

    def __init__(self, key: str, status: int, **params) -> None:
        super().__init__(t(key, config.DEFAULT_LANG, **params))
        self.key = key
        self.params = params
        self.status = status

    @property
    def message(self) -> str:
        return t(self.key, config.DEFAULT_LANG, **self.params)


class LoginError(UserError):
    """Giriş denemesinin reddi: 401 kimlik hatası, 429 geçici kilit (R6-4).

    ``UserError``dan türer: reddeden şey yine bir kullanıcı işlemidir ve yol koşucusu tek
    ``except`` ile mesajı ve durumu olduğu gibi kullanıcıya gösterebilir.
    """


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
            _add_lang(conn)
            _add_business_role(conn)

    # ------------------------------------------------------------------ users

    def add_user(
        self,
        username: str,
        password: str,
        role: str,
        business_role: str = config.DEFAULT_BUSINESS_ROLE,
    ) -> dict:
        """Kullanıcıyı açar ve public sözlüğünü döndürür; ad küçük harfe katlanır."""
        name = str(username).lower()
        if not USERNAME_RE.match(name):
            raise UserError("auth.bad_name", 422)
        if role not in ROLES:
            raise UserError("auth.bad_role", 422)
        if business_role not in config.BUSINESS_ROLES:
            raise UserError("auth.bad_business_role", 422)
        if check_new_password(password):
            # ASSUMPTION: passwords.py'nin tek reddi kısa parola, o yüzden tek anahtar; kataloğun
            # satırı onun cümlesidir.
            raise UserError("auth.password_short", 422, n=config.PASSWORD_MIN_LEN)
        with _connect(self.path) as conn:
            try:
                conn.execute(
                    "INSERT INTO users (username, password_hash, role, active, created_at, business_role)"
                    " VALUES (?, ?, ?, 1, ?, ?)",
                    (name, hash_password(password), role, self._now_iso(), business_role),
                )
            except sqlite3.IntegrityError:
                raise UserError("auth.duplicate", 409) from None
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
        self,
        id: int,
        role: str | None = None,
        active: bool | None = None,
        password: str | None = None,
        business_role: str | None = None,
    ) -> dict:
        """Rolü, etkinliği, parolayı ve/veya iş rolünü değiştirir; son etkin yöneticiyi korur."""
        user = self.get_by_id(id)
        if user is None:
            raise UserError("auth.user_not_found", 404)
        if role is not None and role not in ROLES:
            raise UserError("auth.bad_role", 422)
        if business_role is not None and business_role not in config.BUSINESS_ROLES:
            raise UserError("auth.bad_business_role", 422)
        if password is not None and check_new_password(password):
            raise UserError("auth.password_short", 422, n=config.PASSWORD_MIN_LEN)
        if user["role"] == "admin" and user["active"] and (role == "user" or active is False):
            if self._count_active_admins() <= 1:
                raise UserError("auth.last_admin", 409)

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
        if business_role is not None:
            sets.append("business_role = ?")
            args.append(business_role)
        if sets:
            with _connect(self.path) as conn:
                conn.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = ?", (*args, id))
                if password is not None or active is False:
                    conn.execute("DELETE FROM sessions WHERE user_id = ?", (id,))
        return self.get_by_id(id)

    def set_lang(self, id: int, lang: str) -> dict:
        """Kişinin kendi arayüz dilini yazar ve public sözlüğünü döndürür (R8-5).

        Tercih ``LANGUAGES`` dışıysa reddedilir; ``None`` hiçbir tercih yapılmadığıdır ve yalnız
        ``add_user``da doğar - buradan geri silinmez, kişinin dili hep bir dildir.
        """
        if lang not in config.LANGUAGES:
            raise UserError("auth.bad_lang", 422)
        if self.get_by_id(id) is None:
            raise UserError("auth.user_not_found", 404)
        with _connect(self.path) as conn:
            conn.execute("UPDATE users SET lang = ? WHERE id = ?", (lang, id))
        return self.get_by_id(id)

    # ------------------------------------------------------- login, lockout, sessions

    def authenticate(self, username: str, password: str) -> dict:
        """Adı ve parolayı doğrular; başarılıysa public kullanıcıyı döndürür, değilse LoginError.

        Bilinmeyen ad, yanlış parola ve pasif kullanıcı aynı 401 satırını verir: hangisi olduğu
        saldırgana bilgi vermesin. Üçü de ``login_failures`` satırı bırakır, böylece kilitlenme
        sayacı bilinmeyen adlar için de işler.
        """
        name = str(username).lower()
        remaining = self._locked_for(name)
        if remaining is not None:
            raise LoginError("auth.locked", 429, minutes=math.ceil(remaining / 60))
        row = self._credential(name)
        # ASSUMPTION: kilit eşiği dolunca onu dolduran denemenin kendisi 401 alır; 429 sonraki
        # denemelerdir (kilit, geçmiş denemelerin bir sonucudur ve giriş denemesinden önce sorgulanır).
        if row is None or not verify_password(password, row[1]) or not row[2]:
            self._record_failure(name)
            raise LoginError("auth.login_failed", 401)
        with _connect(self.path) as conn:
            conn.execute("DELETE FROM login_failures WHERE username = ?", (name,))
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (self._now_iso(), row[0]))
        return self.get_by_id(row[0])

    def create_session(self, user: dict) -> str:
        """Oturum açar: ham anahtar yalnız çağırana döner, dosyaya sha256 izi yazılır (sözleşme)."""
        token = secrets.token_urlsafe(32)
        now = self.clock()
        with _connect(self.path) as conn:
            conn.execute(
                "INSERT INTO sessions (token_hash, user_id, created_at, expires_at)"
                " VALUES (?, ?, ?, ?)",
                (_token_hash(token), user["id"], _iso(now), _iso(now + config.SESSION_HOURS * 3600)),
            )
        return token

    def session_user(self, token: str) -> dict | None:
        """Oturumun kullanıcısı; süre geçmişse satır silinir, kullanıcı pasifse None."""
        if not token:
            return None
        digest = _token_hash(token)
        with _connect(self.path) as conn:
            row = conn.execute(
                "SELECT user_id, expires_at FROM sessions WHERE token_hash = ?", (digest,)
            ).fetchone()
            if row is None:
                return None
            if row[1] <= self._now_iso():  # ISO metinleri aynı biçimde: sözel sıralama saat sırası
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (digest,))
                return None
        user = self.get_by_id(row[0])
        return user if user and user["active"] else None

    def delete_session(self, token: str) -> None:
        """Oturumu kapatır; tanınmayan anahtar sessizce geçilir (çerez zaten silinmiş olabilir)."""
        with _connect(self.path) as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash = ?", (_token_hash(token),))

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

    def _credential(self, name: str) -> tuple | None:
        """Doğrulama için gereken üç alan; public okuma hash'i hiç seçmediği için ayrı sorgu."""
        with _connect(self.path) as conn:
            return conn.execute(
                "SELECT id, password_hash, active FROM users WHERE username = ?", (name,)
            ).fetchone()

    def _record_failure(self, name: str) -> None:
        with _connect(self.path) as conn:
            conn.execute(
                "INSERT INTO login_failures (username, ts) VALUES (?, ?)", (name, self.clock())
            )

    def _locked_for(self, name: str) -> float | None:
        """Kilitliyse kilidin bitmesine kalan saniye; değilse None.

        Sayaç yalnız ``LOGIN_WINDOW_MIN`` dakikalık penceredeki denemeleri sayar; eşik dolduysa
        kilit son denemeden ``LOCKOUT_MIN`` dakika sonrasına kadar sürer.
        """
        now = self.clock()
        with _connect(self.path) as conn:
            count, last = conn.execute(
                "SELECT COUNT(*), MAX(ts) FROM login_failures WHERE username = ? AND ts >= ?",
                (name, now - config.LOGIN_WINDOW_MIN * 60),
            ).fetchone()
        if count < config.LOGIN_MAX_FAILURES:
            return None
        return max(last + config.LOCKOUT_MIN * 60 - now, 0.0) or None


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, timezone.utc).isoformat(timespec="seconds")


def _token_hash(token: str) -> str:
    """Oturum anahtarının dosyada duran izi: çerez sızsa da anahtar geri okunamaz."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _public(row: tuple) -> dict:
    user = dict(zip(_COLUMNS, row))
    user["active"] = bool(user["active"])
    return user


def _add_business_role(conn) -> None:
    """Run 6 dosyalarında iş rolü kolonu yoktur: sona eklenir, eski satırlar varsayılanı okur (R7-16)."""
    if "business_role" in {row[1] for row in conn.execute("PRAGMA table_info(users)")}:
        return
    # ASSUMPTION: ALTER TABLE bağlama parametresi kabul etmediği için varsayılan DDL metnine yazılır;
    # değer config'in sabit listesinden gelir, kullanıcı girdisi değildir.
    conn.execute(
        "ALTER TABLE users ADD COLUMN business_role TEXT NOT NULL DEFAULT"
        f" '{config.DEFAULT_BUSINESS_ROLE}'"
    )


def _add_lang(conn) -> None:
    """Run 7 dosyalarında dil tercihi kolonu yoktur: sona eklenir, eski satır tercihsiz doğar (R8-5).

    İş rolünden önce koşulur: iki kolonu da olmayan Run 6 dosyasında ``business_role`` son kolon
    olarak kalmalı (test_business_role_store onu birebir ölçer).
    """
    if "lang" in {row[1] for row in conn.execute("PRAGMA table_info(users)")}:
        return
    conn.execute("ALTER TABLE users ADD COLUMN lang TEXT")


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
