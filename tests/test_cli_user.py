# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``user``: kullanıcı hesapları komut satırından (R6-8).

Parola hiçbir komutun argümanı değildir: iki kez ``getpass``den geçer ve uyuşmazsa hiçbir satır
yazılmaz. Komut login istemez — kendi makinesinin dosyasını kendi yönetir. ``NL2SQL_APP_DB`` testin
kendi tmp dosyasına çevrilir, yani ``data/bilgin.db``ye dokunulmaz.
"""

import getpass
import sqlite3

import pytest

from nl2sql.auth.passwords import verify_password
from nl2sql.auth.store import DUPLICATE_MESSAGE, LAST_ADMIN_MESSAGE, NOT_FOUND_MESSAGE, UserStore
from nl2sql.cli import main as cli

PAROLA = "Parola2026!"
YENI = "YeniParola2026!"
KISA = "Kisa1!"


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Kullanıcı dosyası: komut yolu kendisi çağıran ``config.app_db_path``den okur."""
    path = tmp_path / "app.db"
    monkeypatch.setenv("NL2SQL_APP_DB", str(path))
    return path


def type_passwords(monkeypatch, *values) -> list[str]:
    """``getpass.getpass``in yerinde sıradaki parolayı döndüren sahte girdi; sorulanlar da birikir."""
    asked: list[str] = []
    remaining = list(values)

    def fake(prompt=""):
        asked.append(prompt)
        return remaining.pop(0)

    monkeypatch.setattr(getpass, "getpass", fake)
    return asked


def users(path) -> dict:
    """Ada göre public kullanıcılar; ``user list``in okuduğu aynı kaynaktır."""
    return {user["username"]: user for user in UserStore(path).list_users()}


def stored_hashes(path) -> dict:
    """Karma yalnız dosyada durur: ekranın onu hiç basmadığı buradan doğrulanır."""
    conn = sqlite3.connect(path)
    try:
        return dict(conn.execute("SELECT username, password_hash FROM users"))
    finally:
        conn.close()


# ------------------------------------------------------------------ add + list


def test_add_an_admin_and_a_user_and_list_them(db, monkeypatch, capsys):
    asked = type_passwords(monkeypatch, PAROLA, PAROLA, PAROLA, PAROLA)

    assert cli.main(["user", "add", "admin", "--role", "admin"]) == 0
    assert cli.main(["user", "add", "muhasebe"]) == 0
    out = capsys.readouterr().out

    assert "✓ admin eklendi (rol admin)." in out
    assert "✓ muhasebe eklendi (rol user)." in out, "--role söylenmeyince user gelir"
    assert asked == ["Parola: ", "Parola (tekrar): "] * 2

    UserStore(db).authenticate("admin", PAROLA)  # son giriş kolonu bir kez dolsun
    assert cli.main(["user", "list"]) == 0
    listing = capsys.readouterr().out

    for column in ("Kullanıcı", "Rol", "Durum", "Son giriş"):
        assert column in listing
    assert "admin" in listing and "muhasebe" in listing
    assert "etkin" in listing
    assert users(db)["admin"]["last_login_at"] in listing
    assert "-" in listing, "hiç giriş yapmamış kullanıcının hanesi boş kalmasın"
    assert "scrypt$" not in listing and PAROLA not in listing
    assert all(hash_ not in listing for hash_ in stored_hashes(db).values())


# ------------------------------------------------------------------ reddedilen parolalar


def test_a_mismatch_prompts_again_and_writes_nothing(db, monkeypatch, capsys):
    asked = type_passwords(monkeypatch, PAROLA, YENI)

    assert cli.main(["user", "add", "admin", "--role", "admin"]) == 2

    assert "Parolalar eşleşmiyor." in capsys.readouterr().out
    assert asked == ["Parola: ", "Parola (tekrar): "]
    assert users(db) == {}


def test_a_short_password_gives_its_own_sentence(db, monkeypatch, capsys):
    type_passwords(monkeypatch, KISA, KISA)

    assert cli.main(["user", "add", "admin", "--role", "admin"]) == 2

    assert "Parola en az 10 karakter olmalı." in capsys.readouterr().out
    assert users(db) == {}


def test_a_duplicate_name_is_refused(db, monkeypatch, capsys):
    type_passwords(monkeypatch, PAROLA, PAROLA, PAROLA, PAROLA)
    assert cli.main(["user", "add", "admin", "--role", "admin"]) == 0
    capsys.readouterr()

    assert cli.main(["user", "add", "admin"]) == 2

    assert DUPLICATE_MESSAGE in capsys.readouterr().out
    assert list(users(db)) == ["admin"]


# ------------------------------------------------------------------ passwd


def test_passwd_changes_the_hash(db, monkeypatch, capsys):
    type_passwords(monkeypatch, PAROLA, PAROLA, YENI, YENI)
    assert cli.main(["user", "add", "eren"]) == 0
    before = stored_hashes(db)["eren"]
    capsys.readouterr()

    assert cli.main(["user", "passwd", "eren"]) == 0

    assert "✓ eren parolası değişti." in capsys.readouterr().out
    after = stored_hashes(db)["eren"]
    assert after != before
    assert verify_password(YENI, after) and not verify_password(PAROLA, after)


def test_passwd_an_unknown_user_is_refused_before_asking(db, monkeypatch, capsys):
    asked = type_passwords(monkeypatch)

    assert cli.main(["user", "passwd", "yok"]) == 2

    assert NOT_FOUND_MESSAGE in capsys.readouterr().out
    assert asked == [], "olmayan kullanıcı için parola sorulmaz"


# ------------------------------------------------------------------ set


def test_set_cannot_deactivate_the_only_admin(db, monkeypatch, capsys):
    type_passwords(monkeypatch, PAROLA, PAROLA)
    assert cli.main(["user", "add", "admin", "--role", "admin"]) == 0
    capsys.readouterr()

    assert cli.main(["user", "set", "admin", "--deactivate"]) == 2

    assert LAST_ADMIN_MESSAGE in capsys.readouterr().out
    assert users(db)["admin"]["active"] is True


def test_set_demotes_one_of_two_admins(db, monkeypatch, capsys):
    type_passwords(monkeypatch, PAROLA, PAROLA, PAROLA, PAROLA)
    assert cli.main(["user", "add", "admin", "--role", "admin"]) == 0
    assert cli.main(["user", "add", "muhasebe", "--role", "admin"]) == 0
    capsys.readouterr()

    assert cli.main(["user", "set", "admin", "--role", "user"]) == 0

    assert "✓ admin: rol user, etkin." in capsys.readouterr().out
    assert users(db)["admin"]["role"] == "user"


def test_set_deactivates_and_activates_a_plain_user(db, monkeypatch, capsys):
    type_passwords(monkeypatch, PAROLA, PAROLA)
    assert cli.main(["user", "add", "muhasebe"]) == 0
    capsys.readouterr()

    assert cli.main(["user", "set", "muhasebe", "--deactivate"]) == 0
    assert "✓ muhasebe: rol user, pasif." in capsys.readouterr().out
    assert users(db)["muhasebe"]["active"] is False

    assert cli.main(["user", "set", "muhasebe", "--activate"]) == 0
    assert "✓ muhasebe: rol user, etkin." in capsys.readouterr().out
    assert users(db)["muhasebe"]["active"] is True

    assert cli.main(["user", "list"]) == 0
    assert "pasif" not in capsys.readouterr().out


def test_set_an_unknown_user_is_refused(db, capsys):
    assert cli.main(["user", "set", "yok", "--role", "user"]) == 2

    assert NOT_FOUND_MESSAGE in capsys.readouterr().out


# ------------------------------------------------------------------ boş liste


def test_an_empty_list_says_what_to_do_next(db, capsys):
    assert cli.main(["user", "list"]) == 0

    out = capsys.readouterr().out
    assert "Henüz kullanıcı yok" in out
    assert "user add" in out and "admin" in out
