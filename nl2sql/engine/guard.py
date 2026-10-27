"""Read-only guard for a SQL Server connection (PLAN R7-24).

Before a connection is stored, the database itself is asked what the login can do: ``sysadmin``
or ``db_owner`` membership, the five database-level powers, and whether a sample of the dataset's
own tables is really readable. A login that writes or manages is refused here, because the durable
boundary is a login that cannot write - ``ApplicationIntent=ReadOnly`` and the Python policy are
the layers behind it, not the boundary.

Every answer is one Turkish line for ``#conn-result``. A driver error is the report's single line
and goes through ``connections.scrub`` first, since a driver quotes the connection string back.
``connect`` is the seam a test uses instead of a real SQL Server.

The login is bounded: pyodbc waits forever by default, so an unreachable host used to leave the
request - and the admin's form with it - open with no report at all. A timed-out login is a driver
error like any other, which is to say an ordinary failed line.
"""

from __future__ import annotations

import os
from collections.abc import Iterable

from nl2sql import config
from nl2sql.engine import connections
from nl2sql.engine.login_script import DEFAULT_SCHEMA
from nl2sql.schema_map import doc

POWER_MESSAGE = "Bu giriş yazabiliyor ya da yönetebiliyor; salt okunur bir giriş kullanın."
CONNECT_MESSAGE = "Bağlantı kurulamadı; sunucu, veritabanı ve giriş bilgilerini denetleyin."

LOGIN_TIMEOUT_S = 5  # seconds the driver is given for the login before it is a failed line
LOGIN_TIMEOUT_ENV = "NL2SQL_CONN_LOGIN_TIMEOUT_S"  # widened only for a genuinely slow link

_DATABASE_PERMISSIONS = ("INSERT", "UPDATE", "DELETE", "ALTER", "EXECUTE")

# (check, the query whose answer is 1 when the login is too powerful, the line when it is not)
_POWER_CHECKS = (
    ("sysadmin", "SELECT IS_SRVROLEMEMBER('sysadmin')", "Bu giriş bir sunucu yöneticisi (sysadmin) değil."),
    ("db_owner", "SELECT IS_MEMBER('db_owner')", "Bu giriş veritabanı sahibi (db_owner) değil."),
) + tuple(
    (
        permission.lower(),
        f"SELECT HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', '{permission}')",
        f"Bu girişin {permission} yetkisi yok.",
    )
    for permission in _DATABASE_PERMISSIONS
)


def readonly_guard(
    conn_str: str,
    tables: Iterable[str],
    connect=None,
    login_script_url: str | None = None,
) -> dict:
    """Contracts "guard report": what this login may do, in Turkish, plus the tables it cannot see.

    ``connect`` replaces the connector (``pyodbc.connect`` by default); ``login_script_url`` is the
    dataset's own generated read-only login script, echoed back so the screen can link to it.
    """
    conn = None
    try:
        conn = (connect or _connect)(conn_str)
        lines, missing, powerful = _check(conn, tables)
    except Exception as exc:  # the driver's own sentence, scrubbed, is then the whole report
        return {
            "ok": False,
            "lines": [_line("connect", False, f"{CONNECT_MESSAGE} {_text(exc)}")],
            "missing_tables": [],
            "login_script_url": login_script_url,
        }
    finally:
        if conn is not None:
            conn.close()
    # ASSUMPTION (R7-24): only a power refuses the save; an invisible table is reported, since a map
    # may name a table this database does not have and the admin has to see which one.
    return {
        "ok": not powerful,
        "lines": lines,
        "missing_tables": missing,
        "login_script_url": login_script_url,
    }


def _check(conn, tables: Iterable[str]) -> tuple[list[dict], list[str], bool]:
    """One line per check: the seven powers, then a sample of the dataset's own tables."""
    lines: list[dict] = []
    powerful = False
    for check, sql, ok_message in _POWER_CHECKS:
        too_powerful = _answer(conn, sql) == 1
        powerful = powerful or too_powerful
        lines.append(
            _line(check, not too_powerful, POWER_MESSAGE if too_powerful else ok_message)
        )
    missing: list[str] = []
    for name in _sample(tables):
        readable = _answer(conn, _select_sql(name)) == 1
        if not readable:
            missing.append(name)
        lines.append(_line("table", readable, _table_message(name, readable)))
    return lines, missing, powerful


def _answer(conn, sql: str):
    """The one value a probe answers; NULL is neither a power nor a readable table."""
    row = conn.execute(sql).fetchone()
    return row[0] if row else None


def _sample(tables: Iterable[str]) -> list[str]:
    """Up to ``CONN_TABLE_SAMPLE`` names, sorted so that the same map always reports the same lines."""
    names = {str(name).strip() for name in tables if str(name).strip()}
    return sorted(names)[: config.CONN_TABLE_SAMPLE]


def _select_sql(table: str) -> str:
    """HAS_PERMS_BY_NAME wants a schema-qualified name; the map keeps a bare one for dbo (R4-5)."""
    schema, name = doc.split_name(table)
    target = f"{schema or DEFAULT_SCHEMA}.{name}".replace("'", "''")
    return f"SELECT HAS_PERMS_BY_NAME('{target}', 'OBJECT', 'SELECT')"


def _table_message(name: str, readable: bool) -> str:
    if readable:
        return f"{name} bu girişle okunabiliyor."
    return f"{name} bu girişle okunamıyor: tablo yok ya da SELECT yetkisi yok."


def _line(check: str, ok: bool, message: str) -> dict:
    return {"check": check, "ok": bool(ok), "message": message}


def _text(exc: BaseException) -> str:
    """The driver's sentence on one line, with every ``PWD=``/``Password=`` value out of it."""
    return connections.scrub(" ".join(str(exc).split()))


def _connect(conn_str: str):
    """The real connector: pyodbc is imported lazily, the way the MSSQL backend imports it."""
    import pyodbc

    return pyodbc.connect(conn_str, timeout=_login_timeout_s())


def _login_timeout_s() -> int:
    """Whole seconds of login patience; the env widens it, anything else falls back to the bound."""
    try:
        return max(1, int(os.environ.get(LOGIN_TIMEOUT_ENV, "") or LOGIN_TIMEOUT_S))
    except ValueError:
        return LOGIN_TIMEOUT_S
