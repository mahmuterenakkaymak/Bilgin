"""T317: ``user`` komutunda iş rolü (PLAN R7-16).

Dünya ``tests/test_cli_user.py`` ile aynı - kopya, import değil: ``NL2SQL_APP_DB`` testin kendi
tmp dosyasına çevrilir ve parola hâlâ ``getpass``ten iki kez sorulur. İş rolü koda yazılır
(``satis``), ekrana config'in Türkçe adıyla çıkar (``Satış``): komut satırı bir ERP kullanıcısının
bildiği şeyi gösterir, deposunun anahtarını değil.
"""

import getpass

import pytest

from nl2sql import config
from nl2sql.auth.store import NOT_FOUND_MESSAGE, UserStore
from nl2sql.cli import main as cli

PAROLA = "Parola2026!"


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Kullanıcı dosyası: komut yolu kendisi çağıran ``config.app_db_path``den okur."""
    path = tmp_path / "app.db"
    monkeypatch.setenv("NL2SQL_APP_DB", str(path))
    return path


def type_passwords(monkeypatch, *values) -> None:
    """``getpass.getpass``in yerinde sıradaki parolayı döndüren sahte girdi.

    Boş çağrılırsa parola sorulmuş olur ve test patlar: yani "hiç sorulmadı"nın ölçtüğü şey budur.
    """
    remaining = list(values)

    def fake(prompt=""):
        return remaining.pop(0)

    monkeypatch.setattr(getpass, "getpass", fake)


def users(path) -> dict:
    """Ada göre public kullanıcılar; ``user list``in okuduğu aynı kaynaktır."""
    return {user["username"]: user for user in UserStore(path).list_users()}


# ------------------------------------------------------------------------------ add


def test_add_takes_the_business_role_and_shows_its_turkish_name(db, monkeypatch, capsys):
    type_passwords(monkeypatch, PAROLA, PAROLA)

    assert cli.main(["user", "add", "ayse", "--role", "admin", "--business-role", "satis"]) == 0

    out = capsys.readouterr().out
    assert "✓ ayse eklendi (rol admin)." in out
    assert "İş rolü: Satış." in out
    assert users(db)["ayse"]["business_role"] == "satis"
    assert users(db)["ayse"]["role"] == "admin", "iş rolü yetki rolünün yerine geçmez"


def test_a_user_added_without_the_option_reads_genel(db, monkeypatch, capsys):
    type_passwords(monkeypatch, PAROLA, PAROLA)

    assert cli.main(["user", "add", "muhasebeci"]) == 0

    out = capsys.readouterr().out
    assert f"İş rolü: {config.BUSINESS_ROLES[config.DEFAULT_BUSINESS_ROLE]}." in out
    assert users(db)["muhasebeci"]["business_role"] == config.DEFAULT_BUSINESS_ROLE


def test_an_unknown_business_role_is_refused_before_the_password(db, monkeypatch, capsys):
    type_passwords(monkeypatch)

    with pytest.raises(SystemExit) as refused:
        cli.main(["user", "add", "ayse", "--business-role", "Satis"])

    assert refused.value.code == 2
    assert users(db) == {}


# ------------------------------------------------------------------------------ set


def test_set_moves_a_user_to_another_business_role(db, monkeypatch, capsys):
    type_passwords(monkeypatch, PAROLA, PAROLA)
    assert cli.main(["user", "add", "ayse", "--role", "admin", "--business-role", "satis"]) == 0
    before = users(db)["ayse"]
    capsys.readouterr()

    assert cli.main(["user", "set", "ayse", "--business-role", "yonetim"]) == 0

    assert "✓ ayse: iş rolü Yönetim." in capsys.readouterr().out
    after = users(db)["ayse"]
    assert after["business_role"] == "yonetim"
    assert after["role"] == before["role"] and after["active"] is True


def test_set_an_unknown_user_is_refused(db, capsys):
    assert cli.main(["user", "set", "yok", "--business-role", "satis"]) == 2

    assert NOT_FOUND_MESSAGE in capsys.readouterr().out


# ------------------------------------------------------------------------------ list


def test_the_list_shows_the_business_role_by_its_turkish_name(db, monkeypatch, capsys):
    type_passwords(monkeypatch, PAROLA, PAROLA, PAROLA, PAROLA)
    assert cli.main(["user", "add", "ayse", "--business-role", "satin_alma"]) == 0
    assert cli.main(["user", "add", "mehmet", "--business-role", "muhasebe"]) == 0
    capsys.readouterr()

    assert cli.main(["user", "list"]) == 0

    out = capsys.readouterr().out
    assert "İş rolü" in out
    assert "Satın alma" in out and "Muhasebe" in out
    assert "satin_alma" not in out, "ekranda kod değil adı görünür"
