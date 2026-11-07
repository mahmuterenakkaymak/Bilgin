# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Database connections: one row per dataset in the app database (PLAN R7-22).

A dataset's SQL Server connection is data the admin fills in on a screen, not a file someone
edits: switching the active dataset switches the database with no restart. Only the non-secret
values are ever readable - the password lives in ``secret_blob`` as a DPAPI blob
(:mod:`nl2sql.engine.dpapi`), so the app database, the repository and every log stay free of the
plaintext, and a connection string is built when a session opens and never stored anywhere.

``public`` is what the API may answer: it says whether a password exists (``has_secret``) and
never carries one, ``secret`` hands the plaintext to the one caller about to connect. ``resolve``
is the single door that says which place a dataset's string comes from - its own environment
variable, the generic one, the stored row, none (PLAN R7-23). Refusals
carry the HTTP status the API will answer with, the way ``auth.store`` and ``start.ready`` do.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import sqlite3
import time
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from pathlib import Path

from nl2sql import config
from nl2sql.engine import dpapi
from nl2sql.engine._mssql import CONN_ENV
from nl2sql.i18n import t

AUTHS = ("sql", "windows")

# options_json's four keys (brief): an empty driver means "whatever newest is installed", a None
# port the server's default instance.
# ASSUMPTION: Encrypt and TrustServerCertificate default to yes: the newest driver encrypts by
# default and an internal SQL Server presents a self-signed certificate, so the form's own
# defaults have to connect without a second step.
OPTION_DEFAULTS = {"encrypt": True, "trust_server_certificate": True, "port": None, "driver": ""}
# The legacy driver ships with Windows, so a machine with no modern driver still gets a
# well-formed string and the driver's own "not installed" sentence instead of a broken one.
FALLBACK_DRIVER = "SQL Server"

# The form's refusals are catalog lines (R8-5): the route reads them in the language of the request,
# ``ConnError`` carries their key. These six names are imported by tests older than the catalogs, so
# each holds the program language's own sentence.
NO_SERVER_MESSAGE = t("conn.no_server")
NO_DATABASE_MESSAGE = t("conn.no_database")
BAD_AUTH_MESSAGE = t("conn.bad_auth")
NO_USERNAME_MESSAGE = t("conn.no_username")
NO_PASSWORD_MESSAGE = t("conn.no_password")
BAD_PORT_MESSAGE = t("conn.bad_port")

_CREATE = """
CREATE TABLE IF NOT EXISTS connections (
  dataset TEXT PRIMARY KEY,
  server TEXT NOT NULL,
  database TEXT NOT NULL,
  auth TEXT NOT NULL CHECK (auth IN ('sql', 'windows')),
  username TEXT NOT NULL DEFAULT '',
  secret_blob BLOB,
  options_json TEXT NOT NULL DEFAULT '{}',
  updated_by TEXT,
  updated_at TEXT NOT NULL,
  last_ok_at TEXT,
  last_error TEXT
)
"""

# COALESCE is what makes an empty password mean "keep it": the new blob is NULL then, so the
# stored one survives the update.
_SAVE = """
INSERT INTO connections (dataset, server, database, auth, username, secret_blob, options_json, updated_by, updated_at)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
ON CONFLICT(dataset) DO UPDATE SET
  server = excluded.server,
  database = excluded.database,
  auth = excluded.auth,
  username = excluded.username,
  secret_blob = COALESCE(excluded.secret_blob, connections.secret_blob),
  options_json = excluded.options_json,
  updated_by = excluded.updated_by,
  updated_at = excluded.updated_at
"""

# ``secret_blob`` is read only for whether it exists; ``public`` turns it into ``has_secret``.
_COLUMNS = (
    "dataset",
    "server",
    "database",
    "auth",
    "username",
    "options_json",
    "last_ok_at",
    "last_error",
    "secret_blob",
)
_READ = ", ".join(_COLUMNS)

_DRIVER_RE = re.compile(r"^ODBC Driver (\d+) for SQL Server$")
# A driver error quotes the connection string back; the secret is the value of these two keys.
_SECRET_RE = re.compile(r"(?i)\b(pwd|password)\s*=\s*[^;]*")


class ConnError(Exception):
    """Refusal of a connection operation: catalog key, its parameters and the HTTP status (R6-3).

    ``message`` is the sentence the callers older than the catalogs read, and it is always Turkish;
    an HTTP route builds the sentence itself from the key in the language of the request (R8-5).
    """

    def __init__(self, key: str, status: int, **params) -> None:
        super().__init__(t(key, config.DEFAULT_LANG, **params))
        self.key = key
        self.params = params
        self.status = status

    @property
    def message(self) -> str:
        return t(self.key, config.DEFAULT_LANG, **self.params)


class ConnectionStore:
    """The single door to the ``connections`` table: save, read, decrypt, record a check result."""

    def __init__(
        self, path: str | Path | None = None, clock: Callable[[], float] = time.time
    ) -> None:
        # The caller names the file; tests run on a scratch app db, never on data/bilgin.db (R6-1).
        self.path = Path(config.app_db_path() if path is None else path)
        self.clock = clock
        with _connect(self.path) as conn:
            conn.execute(_CREATE)

    def save(
        self,
        dataset: str,
        fields: dict | None,
        password: str | None = None,
        username: str = "",
    ) -> dict:
        """Write one dataset's connection; an empty password keeps the stored secret (R7-22)."""
        data = fields or {}
        server = str(data.get("server") or "").strip()
        database = str(data.get("database") or "").strip()
        auth = str(data.get("auth") or "sql").strip().lower()
        login = str(data.get("username") or "").strip()
        options = _options(data.get("options"))
        if not server:
            raise ConnError("conn.no_server", 422)
        if not database:
            raise ConnError("conn.no_database", 422)
        if auth not in AUTHS:
            raise ConnError("conn.bad_auth", 422)
        if auth == "sql" and not login:
            raise ConnError("conn.no_username", 422)
        secret = str(password) if password else ""
        if auth == "sql" and not secret and self._blob(dataset) is None:
            raise ConnError("conn.no_password", 422)
        # Windows auth has no password of its own: the service account connects, so a typed
        # value is dropped rather than stored for a string that will never use it.
        blob = dpapi.protect(secret.encode("utf-8"), dpapi.entropy_for(dataset)) if secret and auth == "sql" else None
        with _connect(self.path) as conn:
            conn.execute(
                _SAVE,
                (
                    dataset,
                    server,
                    database,
                    auth,
                    login,
                    blob,
                    json.dumps(options, sort_keys=True),
                    username,
                    self._now_iso(),
                ),
            )
        return self.public(dataset)

    def public(self, dataset: str) -> dict:
        """Contracts "connection (public)": never the secret, never a connection string."""
        row = self._read(dataset)
        if row is None:
            return {
                "dataset": dataset,
                "server": "",
                "database": "",
                "auth": "sql",
                "username": "",
                "options": dict(OPTION_DEFAULTS),
                "has_secret": False,
                "last_ok_at": None,
                "last_error": None,
                "state": "none",
            }
        return {
            "dataset": row["dataset"],
            "server": row["server"],
            "database": row["database"],
            "auth": row["auth"],
            "username": row["username"],
            "options": _options(row["options_json"]),
            "has_secret": row["secret_blob"] is not None,
            "last_ok_at": row["last_ok_at"],
            "last_error": row["last_error"],
            "state": "down" if row["last_error"] else ("ok" if row["last_ok_at"] else "unknown"),
        }

    def secret(self, dataset: str) -> str | None:
        """The stored password in plain text, for the caller about to connect; None when there is none."""
        blob = self._blob(dataset)
        if blob is None:
            return None
        return dpapi.unprotect(bytes(blob), dpapi.entropy_for(dataset)).decode("utf-8")

    def mark_ok(self, dataset: str) -> None:
        """Record that the database answered: the green dot, and the old error line is gone."""
        with _connect(self.path) as conn:
            conn.execute(
                "UPDATE connections SET last_ok_at = ?, last_error = NULL WHERE dataset = ?",
                (self._now_iso(), dataset),
            )

    def mark_error(self, dataset: str, error: str | None) -> None:
        """Record the driver's own sentence; scrubbed first, since it quotes the connection string."""
        with _connect(self.path) as conn:
            conn.execute(
                "UPDATE connections SET last_error = ? WHERE dataset = ?", (scrub(error), dataset)
            )

    # ------------------------------------------------------------------ internals

    def _read(self, dataset: str) -> dict | None:
        with _connect(self.path) as conn:
            row = conn.execute(
                f"SELECT {_READ} FROM connections WHERE dataset = ?", (dataset,)
            ).fetchone()
        return dict(zip(_COLUMNS, row)) if row else None

    def _blob(self, dataset: str) -> bytes | None:
        with _connect(self.path) as conn:
            row = conn.execute(
                "SELECT secret_blob FROM connections WHERE dataset = ?", (dataset,)
            ).fetchone()
        return row[0] if row else None

    def _now_iso(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(timespec="seconds")


def build_conn_str(row: dict, password: str | None = None, driver: str | None = None) -> str:
    """The ODBC string for one stored connection, used and dropped; ``ApplicationIntent`` is added by ``_mssql``."""
    options = _options(row.get("options"))
    name = str(driver or options["driver"] or newest_driver() or FALLBACK_DRIVER)
    server = str(row.get("server") or "")
    if options["port"]:
        server = f"{server},{options['port']}"
    parts = [
        f"DRIVER={{{name}}}",
        f"SERVER={server}",
        f"DATABASE={row.get('database') or ''}",
    ]
    if str(row.get("auth") or "sql") == "windows":
        parts.append("Trusted_Connection=yes")
    else:
        parts.append(f"UID={row.get('username') or ''}")
        parts.append(f"PWD={password or ''}")
    parts.append("Encrypt=" + ("yes" if options["encrypt"] else "no"))
    parts.append("TrustServerCertificate=" + ("yes" if options["trust_server_certificate"] else "no"))
    return ";".join(parts) + ";"


def resolve(dataset: str, store: ConnectionStore | None, active: str | None) -> dict:
    """Where a dataset's connection comes from, in the order of R7-23: env_dataset > env > stored > none."""
    own = _env(config.CONN_ENV_PREFIX + str(dataset).upper())
    if own:
        return {"source": "env_dataset", "conn_str": own}
    # The generic variable names the database the whole process asks: it belongs to the active
    # dataset only, and only while the backend is mssql, so the value sitting in the developer's
    # shell cannot quietly answer for a Run 1-6 test that runs on SQLite.
    if dataset == active and config.backend() == "mssql":
        generic = _env(CONN_ENV)
        if generic:
            return {"source": "env", "conn_str": generic}
    if store is not None:
        row = store.public(dataset)
        if row["state"] != "none":  # a row the admin saved on the screen; the secret comes with it
            return {"source": "stored", "conn_str": build_conn_str(row, store.secret(dataset))}
    return {"source": "none", "conn_str": None}


def newest_driver(drivers: Callable[[], Iterable[str]] | Iterable[str] | None = None) -> str:
    """The newest installed "ODBC Driver NN for SQL Server"; "" when the machine has none."""
    names = drivers() if callable(drivers) else (_installed() if drivers is None else drivers)
    best_name, best_number = "", -1
    for name in names:
        # Numeric: "ODBC Driver 9" is older than 17, which a text sort would get backwards.
        match = _DRIVER_RE.match(str(name).strip())
        if match and int(match.group(1)) > best_number:
            best_name, best_number = str(name).strip(), int(match.group(1))
    return best_name


def scrub(text: str | None, secret: str | None = None) -> str:
    """A driver sentence with its secrets out: every ``PWD=``/``Password=`` value and the literal."""
    value = "" if text is None else str(text)
    if secret:
        value = value.replace(str(secret), "***")
    return _SECRET_RE.sub(lambda match: f"{match.group(1)}=***", value)


def _env(name: str) -> str:
    """An environment variable's value, "" when it is unset or blank: a blank is no connection."""
    value = os.environ.get(name)
    return value.strip() if value and value.strip() else ""


def _options(value: object) -> dict:
    """The four option keys of a form body or of stored ``options_json``; missing ones default."""
    data = value
    if isinstance(data, str):
        data = json.loads(data or "{}")
    data = data if isinstance(data, dict) else {}
    return {
        "encrypt": bool(data.get("encrypt", OPTION_DEFAULTS["encrypt"])),
        "trust_server_certificate": bool(
            data.get("trust_server_certificate", OPTION_DEFAULTS["trust_server_certificate"])
        ),
        "port": _port(data.get("port")),
        "driver": str(data.get("driver") or ""),
    }


def _port(value: object) -> int | None:
    """Port of the form: blank means the default instance, anything outside the range is refused."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ConnError("conn.bad_port", 422) from None
    if not 1 <= number <= 65535:
        raise ConnError("conn.bad_port", 422)
    return number


def _installed() -> list[str]:
    try:
        import pyodbc
    except ImportError:
        return []
    try:
        return list(pyodbc.drivers())
    except pyodbc.Error:  # no driver manager on this machine, so there is no list to read
        return []


@contextlib.contextmanager
def _connect(path: Path):
    """Short-lived connection: the folder is opened first, a successful statement is committed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()
