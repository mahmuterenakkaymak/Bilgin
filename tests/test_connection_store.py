# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T333: bağlantı deposu, bağlantı dizesi ve sır temizliği (PLAN R7-22).

Depo, yöneticinin ekrandan doldurduğu SQL Server bağlantısının tek evidir; parola satırda
yalnız DPAPI şifresiyle durur, yani ne dosyanın kendisinde ne de dışarı giden bir sözlükte düz
metin olarak bulunur. Bağlantı dizesi bir yere yazılmaz: yalnız kurulurken üretilir ve sürücü
cümleleri ekrana ya da satıra inmeden önce ``scrub``tan geçer.
"""

from __future__ import annotations

import json
import sqlite3
import sys

import pytest

from nl2sql.auth.store import UserStore
from nl2sql.engine import connections
from nl2sql.engine.connections import (
    ConnError,
    ConnectionStore,
    build_conn_str,
    newest_driver,
    scrub,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI yalnız Windows'ta vardır")

PAROLA = "Bilgin2026!parola"
GIZLI = "GizliParola7"

# Sözleşme "connection PUT body": formun götürdüğü alanlar; options boşu varsayılanları verir.
FIELDS = {"server": "10.0.0.5", "database": "DNAEGITIM", "auth": "sql", "username": "bilgin_ro"}
OPTIONS = {"encrypt": True, "trust_server_certificate": True, "port": None, "driver": ""}


@pytest.fixture
def store(tmp_path):
    return ConnectionStore(tmp_path / "app.db")


def _blob(path, dataset="wwi_real"):
    """Satırın depodaki hali: şifrenin kendisi değil, DPAPI blobu."""
    with sqlite3.connect(path) as conn:
        return conn.execute(
            "SELECT secret_blob FROM connections WHERE dataset = ?", (dataset,)
        ).fetchone()[0]


def _row(path, dataset="wwi_real"):
    with sqlite3.connect(path) as conn:
        row = conn.execute(
            "SELECT dataset, server, database, auth, username, options_json, updated_by"
            " FROM connections WHERE dataset = ?",
            (dataset,),
        ).fetchone()
    return row


# ------------------------------------------------------------------------ sır: yaz, koru, değiştir


def test_a_saved_password_comes_back_for_the_same_dataset(store):
    saved = store.save("wwi_real", FIELDS, PAROLA, "eren")

    assert saved["has_secret"] is True
    assert store.secret("wwi_real") == PAROLA


def test_the_stored_blob_is_not_the_password(store, tmp_path):
    store.save("wwi_real", FIELDS, PAROLA, "eren")

    blob = _blob(tmp_path / "app.db")
    assert blob and PAROLA.encode("utf-8") not in blob


def test_an_empty_password_keeps_the_stored_secret(store):
    store.save("wwi_real", FIELDS, PAROLA, "eren")

    changed = store.save("wwi_real", {**FIELDS, "database": "AutoAI_DB"}, "", "ayse")

    assert changed["database"] == "AutoAI_DB"
    assert changed["has_secret"] is True
    assert store.secret("wwi_real") == PAROLA


def test_a_typed_password_replaces_the_stored_one(store):
    store.save("wwi_real", FIELDS, PAROLA, "eren")

    store.save("wwi_real", FIELDS, "YeniParola!2026", "eren")

    assert store.secret("wwi_real") == "YeniParola!2026"


def test_a_dataset_with_no_row_has_no_secret(store):
    assert store.secret("yok") is None
    assert store.public("yok")["has_secret"] is False


# ---------------------------------------------------------------------------- public sözleşmesi


def test_public_carries_the_contract_fields_and_never_the_secret(store):
    store.save("wwi_real", {**FIELDS, "options": {"port": 14330, "driver": "ODBC Driver 18 for SQL Server"}}, PAROLA, "eren")

    row = store.public("wwi_real")

    assert row == {
        "dataset": "wwi_real",
        "server": "10.0.0.5",
        "database": "DNAEGITIM",
        "auth": "sql",
        "username": "bilgin_ro",
        "options": {
            "encrypt": True,
            "trust_server_certificate": True,
            "port": 14330,
            "driver": "ODBC Driver 18 for SQL Server",
        },
        "has_secret": True,
        "last_ok_at": None,
        "last_error": None,
        "state": "unknown",
    }
    assert PAROLA not in json.dumps(row, ensure_ascii=False)


def test_an_unstored_dataset_reads_as_none_state(store):
    assert store.public("wwi_real") == {
        "dataset": "wwi_real",
        "server": "",
        "database": "",
        "auth": "sql",
        "username": "",
        "options": OPTIONS,
        "has_secret": False,
        "last_ok_at": None,
        "last_error": None,
        "state": "none",
    }


def test_saving_keeps_one_row_per_dataset(store, tmp_path):
    store.save("wwi_real", FIELDS, PAROLA, "eren")

    store.save("wwi_real", {**FIELDS, "server": "10.0.0.9"}, "", "ayse")

    with sqlite3.connect(tmp_path / "app.db") as conn:
        assert conn.execute("SELECT COUNT(*) FROM connections").fetchone()[0] == 1
    assert _row(tmp_path / "app.db")[:2] == ("wwi_real", "10.0.0.9")
    assert _row(tmp_path / "app.db")[6] == "ayse"  # updated_by son yazanı taşır


# ------------------------------------------------------------------------------ reddedilen form


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        ({**FIELDS, "server": "  "}, connections.NO_SERVER_MESSAGE),
        ({**FIELDS, "database": ""}, connections.NO_DATABASE_MESSAGE),
        ({**FIELDS, "auth": "ntlm"}, connections.BAD_AUTH_MESSAGE),
        ({**FIELDS, "username": ""}, connections.NO_USERNAME_MESSAGE),
        ({**FIELDS, "options": {"port": 0}}, connections.BAD_PORT_MESSAGE),
        ({**FIELDS, "options": {"port": 70000}}, connections.BAD_PORT_MESSAGE),
        ({**FIELDS, "options": {"port": "abc"}}, connections.BAD_PORT_MESSAGE),
    ],
)
def test_an_incomplete_form_is_refused_with_its_own_sentence(store, fields, message):
    with pytest.raises(ConnError) as info:
        store.save("wwi_real", fields, PAROLA, "eren")

    assert (info.value.status, info.value.message) == (422, message)
    assert store.public("wwi_real")["state"] == "none"  # hiçbir şey yazılmadı


def test_the_first_sql_save_needs_a_password(store):
    with pytest.raises(ConnError) as info:
        store.save("wwi_real", FIELDS, "", "eren")

    assert info.value.status == 422
    assert store.public("wwi_real")["has_secret"] is False


def test_windows_auth_needs_neither_username_nor_password(store):
    saved = store.save("wwi_real", {**FIELDS, "auth": "windows", "username": ""}, "", "eren")

    assert saved["auth"] == "windows"
    assert saved["has_secret"] is False
    assert store.secret("wwi_real") is None


# --------------------------------------------------------------------------- bağlantı dizesi


def test_the_sql_string_carries_uid_and_pwd(store):
    row = store.save("wwi_real", FIELDS, PAROLA, "eren")

    text = connections.build_conn_str(row, PAROLA, "ODBC Driver 18 for SQL Server")

    assert text.startswith("DRIVER={ODBC Driver 18 for SQL Server};SERVER=10.0.0.5;DATABASE=DNAEGITIM;")
    assert "UID=bilgin_ro;" in text
    assert f"PWD={PAROLA};" in text
    assert "Trusted_Connection" not in text
    assert "Encrypt=yes;" in text and "TrustServerCertificate=yes;" in text


def test_the_windows_string_authenticates_with_the_machine_account(store):
    row = store.save("wwi_real", {**FIELDS, "auth": "windows", "username": ""}, "", "eren")

    text = connections.build_conn_str(row, None, "ODBC Driver 17 for SQL Server")

    assert "Trusted_Connection=yes" in text
    assert "PWD" not in text and "UID" not in text
    assert PAROLA not in text


def test_a_port_is_written_on_the_server_as_host_port(store):
    row = store.save("wwi_real", {**FIELDS, "options": {"port": 14330}}, PAROLA, "eren")

    assert "SERVER=10.0.0.5,14330;" in connections.build_conn_str(row, PAROLA, "D")

    plain = store.save("wwi_real", {**FIELDS, "options": {"port": None}}, PAROLA, "eren")
    assert "SERVER=10.0.0.5;" in connections.build_conn_str(plain, PAROLA, "D")


def test_encrypt_and_trust_follow_their_own_boxes(store):
    row = store.save(
        "wwi_real",
        {**FIELDS, "options": {"encrypt": False, "trust_server_certificate": False}},
        PAROLA,
        "eren",
    )

    text = connections.build_conn_str(row, PAROLA, "D")

    assert "Encrypt=no;" in text and "TrustServerCertificate=no;" in text


def test_the_stored_driver_is_used_when_the_caller_names_none(store):
    row = store.save("wwi_real", {**FIELDS, "options": {"driver": "ODBC Driver 17 for SQL Server"}}, PAROLA, "eren")

    assert "DRIVER={ODBC Driver 17 for SQL Server};" in connections.build_conn_str(row, PAROLA)


# --------------------------------------------------------------------------------- sürücü seçimi


def test_newest_driver_picks_the_highest_number_and_ignores_other_names():
    names = [
        "SQL Server",
        "ODBC Driver 11 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 9 for SQL Server",
    ]

    assert newest_driver(names) == "ODBC Driver 18 for SQL Server"
    assert newest_driver(list(reversed(names))) == "ODBC Driver 18 for SQL Server"


def test_newest_driver_also_takes_the_callable_shape_of_pyodbc_drivers():
    assert newest_driver(lambda: ["ODBC Driver 17 for SQL Server"]) == "ODBC Driver 17 for SQL Server"


def test_newest_driver_is_empty_when_the_machine_has_no_modern_driver():
    assert newest_driver(["SQL Server", "ODBC Driver 18 for Postgres"]) == ""


# ------------------------------------------------------------------------------ sır temizliği


@pytest.mark.parametrize(
    "text",
    [
        f"[28000] Login failed; PWD={GIZLI};UID=bilgin_ro;",
        f"[08001] TCP Provider; Password={GIZLI};Trusted_Connection=no;",
        f"connect failed: pwd = {GIZLI}",
    ],
)
def test_scrub_takes_out_a_password_keyword(text):
    assert GIZLI not in scrub(text)


def test_scrub_keeps_the_rest_of_the_drivers_sentence():
    text = f"[28000] Login failed for user 'bilgin_ro'; PWD={GIZLI}; Server=10.0.0.5,1433"

    assert scrub(text) == "[28000] Login failed for user 'bilgin_ro'; PWD=***; Server=10.0.0.5,1433"


def test_scrub_takes_out_the_literal_secret_too():
    assert GIZLI not in scrub(f"Login failed for 'bilgin_ro' (parola {GIZLI} yanlış)", GIZLI)
    assert scrub("herhangi bir cümle", GIZLI) == "herhangi bir cümle"


def test_scrub_survives_an_empty_failure():
    assert scrub(None) == ""
    assert scrub("") == ""


# ---------------------------------------------------------------------------- durum izi


def test_mark_ok_and_mark_error_move_the_state(store):
    store.save("wwi_real", FIELDS, PAROLA, "eren")
    assert store.public("wwi_real")["state"] == "unknown"

    store.mark_error("wwi_real", f"Login failed; PWD={GIZLI};")

    down = store.public("wwi_real")
    assert down["state"] == "down"
    assert GIZLI not in down["last_error"]

    store.mark_ok("wwi_real")

    ok = store.public("wwi_real")
    assert ok["state"] == "ok"
    assert ok["last_error"] is None
    assert ok["last_ok_at"]


def test_marking_a_dataset_with_no_row_changes_nothing(store):
    store.mark_ok("yok")
    store.mark_error("yok", "sunucuya ulaşılamadı")

    assert store.public("yok")["state"] == "none"


def test_the_store_creates_its_table_in_an_app_db_that_has_only_users(tmp_path):
    UserStore(tmp_path / "app.db")  # Run 6'in dosyası: connections tablosu hiç yok

    store = ConnectionStore(tmp_path / "app.db")

    assert store.public("wwi_real")["state"] == "none"
    assert store.save("wwi_real", FIELDS, PAROLA, "eren")["server"] == "10.0.0.5"
