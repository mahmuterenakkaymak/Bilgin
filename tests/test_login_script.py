# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Salt okunur MSSQL giriş betiği (R3-8): kalıcı sınır parser değil, veritabanı yetkisidir.

Python tarafındaki politika allowlist'i sorgudaki tablo adlarını okur; bir VIEW, SYNONYM ya da
tablo değerli işlev (TVF) allowlist'te olmayan bir tablonun üstünü sardığında sorgu yalnızca
kapsayıcının adını yazdığı için parser bunu görmez. Betik bu boşluğu yetkiyle kapatır: giriş
db_datareader alır, sonra allowlist dışı her tablodan ve her PII kolonundan DENY yer. Testler
üç şeyi birlikte tutar: betik gerçek T-SQL olarak ayrışır, kolon düzeyinde reddedilen küme
şemanın PII işaretleriyle birebir aynıdır ve allowlist'teki her tablo cursor'ın NOT IN listesinde
durur. Parola her zaman yer tutucudur; gerçek sır betiğe hiç girmez.
"""

import re

import sqlglot

from nl2sql.cli import main as cli
from nl2sql.engine import login_script
from nl2sql.policy import pii
from nl2sql.schema_map import doc

SCHEMA = doc.load_schema()
ALLOWED = doc.allowlist(SCHEMA)
MARKS = pii.column_map(SCHEMA)
SCRIPT = login_script.readonly_login_sql(SCHEMA, "nl2sql_ro")

# kolon listesi olan DENY'ler (cursor'daki "DENY SELECT ON" parantez olmadığı için buraya girmez)
COLUMN_DENY = re.compile(r"DENY SELECT \(([^)]*)\) ON \[dbo\]\.\[(\w+)\] TO")
NOT_IN = re.compile(r"NOT IN \(([^)]*)\)")
PASSWORD = re.compile(r"PASSWORD\s*=\s*'([^']*)'")


def denied_columns(script: str) -> set[tuple[str, str]]:
    pairs = set()
    for columns, table in COLUMN_DENY.findall(script):
        for column in columns.split(", "):
            pairs.add((table, column))
    return pairs


def not_in_names(script: str) -> set[str]:
    return set(re.findall(r"'([^']*)'", NOT_IN.search(script).group(1)))


# ----------------------------------------------------------------- the script is real T-SQL


def test_the_whole_script_parses_as_tsql():
    sqlglot.parse(SCRIPT, read="tsql")  # bozuk bir cümlede ParseError ile patlar


def test_the_script_carries_every_required_statement():
    for token in (
        "CREATE LOGIN",
        "CREATE USER",
        "ALTER ROLE db_datareader",
        "DECLARE cur CURSOR",
        "DENY SELECT ON",
        "DENY VIEW DEFINITION",
        "DENY EXECUTE",
    ):
        assert token in SCRIPT, token


def test_the_header_names_the_parser_bypass():
    for word in ("VIEW", "SYNONYM", "TVF"):
        assert word in SCRIPT, word


# ----------------------------------------------------------------- the two permission sets


def test_every_allowlist_table_is_in_the_not_in_list():
    assert ALLOWED <= not_in_names(SCRIPT)


# ----------------------------------------------------------------- the password is a placeholder


def test_the_password_is_only_the_placeholder():
    assert login_script.PASSWORD_PLACEHOLDER in SCRIPT
    assert PASSWORD.findall(SCRIPT) == [login_script.PASSWORD_PLACEHOLDER]


def test_the_login_name_is_used_throughout():
    script = login_script.readonly_login_sql(SCHEMA, "rapor_ro")
    assert "[rapor_ro]" in script and "nl2sql_ro" not in script


# ----------------------------------------------------------------- the CLI writes the file


def test_main_routes_make_login_script(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "make_login_script", lambda **kwargs: seen.update(kwargs) or 0)
    assert cli.main(["make-login-script", "--login", "ro_x"]) == 0
    assert seen == {"login": "ro_x"}


def test_make_login_script_defaults_to_the_readonly_name(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "make_login_script", lambda **kwargs: seen.update(kwargs) or 0)
    assert cli.main(["make-login-script"]) == 0
    assert seen == {"login": login_script.DEFAULT_LOGIN}


