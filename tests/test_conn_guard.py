"""T336: bağlantının salt okunur giriş olup olmadığı denetimi (PLAN R7-24, Contracts "guard report").

Denetim sunucuya sorularak yapılır: giriş sysadmin ya da db_owner mı, veritabanı düzeyindeki beş
yetkisi var mı, haritanın kendi tabloları bu girişle gerçekten okunabiliyor mu. Gerçek bir SQL
Server çağrılmaz: ``readonly_guard`` bağdacı dışarıdan aldığı için test, her sorguyu kendi metnine
göre yanıtlayan sahte bir bağdaç kullanır.
"""

from __future__ import annotations

import json

import pytest

from nl2sql import config
from nl2sql.engine import guard
from nl2sql.engine.guard import POWER_MESSAGE, readonly_guard

PAROLA = "Gizli2026!parola"
BAGLANTI = (
    "DRIVER={ODBC Driver 18 for SQL Server};SERVER=10.0.0.5;DATABASE=WWI;"
    f"UID=bilgin_ro;PWD={PAROLA};"
)
TABLOLAR = ["TBLSTSABIT", "TBLCAHAR", "TBLFATUIRS", "Sales.Customers"]
BETIK = "/api/datasets/wwi_real/login-script.sql"

# Güç denetimlerinin adları; tablo satırları bunlara eklenir.
GUCLER = ("sysadmin", "db_owner", "insert", "update", "delete", "alter", "execute")


class SahteSunucu:
    """Her sorguyu kendi metnine göre yanıtlayan sahte bağlantı.

    Eşleşmeyen sorgular sağlıklı cevabını alır: güç sorguları 0 (yetki yok), tablo sorgusu 1
    (okunabilir). ``yanitlar`` bir alt dize eşleşmesidir: ``{"IS_SRVROLEMEMBER": 1}`` girişi
    sysadmin yapar, ``{"TBLCAHAR": 0}`` o tabloyu görünmez kılar; sunucunun NULL dediği ``None``dır.
    """

    def __init__(self, yanitlar: dict | None = None) -> None:
        self.yanitlar = yanitlar or {}
        self.sorgular: list[str] = []
        self.kapandi = False
        self._satir: tuple = ()

    def execute(self, sql: str) -> "SahteSunucu":
        self.sorgular.append(sql)
        cevap = next((v for anahtar, v in self.yanitlar.items() if anahtar in sql), _saglikli_cevap(sql))
        self._satir = (cevap,)
        return self

    def fetchone(self) -> tuple:
        return self._satir

    def close(self) -> None:
        self.kapandi = True


def _saglikli_cevap(sql: str):
    """Salt okunur bir girişin sağlıklı cevabı: güç sorgusu 0, tablo sorgusu 1."""
    return 1 if "'OBJECT', 'SELECT'" in sql else 0


def denetle(yanitlar=None, tablolar=TABLOLAR, betik=BETIK):
    """Koruyucuyu sahte bağdaçla çalıştırır: raporu ve hangi sorguların sorulduğunu döndürür."""
    sunucu = SahteSunucu(yanitlar)
    rapor = readonly_guard(BAGLANTI, tablolar, connect=lambda _dize: sunucu, login_script_url=betik)
    return rapor, sunucu


def satir(rapor: dict, denetim: str) -> dict:
    return next(line for line in rapor["lines"] if line["check"] == denetim)


def tablolarin_satirlari(rapor: dict) -> list[dict]:
    return [line for line in rapor["lines"] if line["check"] == "table"]


# ------------------------------------------------------------------------------ salt okunur giriş


def test_a_read_only_login_passes_every_check():
    rapor, sunucu = denetle()

    assert rapor["ok"] is True
    assert rapor["missing_tables"] == []
    assert all(line["ok"] for line in rapor["lines"])
    assert all(line["message"] for line in rapor["lines"])
    assert {line["check"] for line in rapor["lines"]} >= set(GUCLER)
    assert len(tablolarin_satirlari(rapor)) == len(TABLOLAR)
    assert "sysadmin" in satir(rapor, "sysadmin")["message"]
    assert sunucu.kapandi is True


def test_every_power_is_asked_of_the_server():
    _, sunucu = denetle()

    assert "SELECT IS_SRVROLEMEMBER('sysadmin')" in sunucu.sorgular
    assert "SELECT IS_MEMBER('db_owner')" in sunucu.sorgular
    for yetki in ("INSERT", "UPDATE", "DELETE", "ALTER", "EXECUTE"):
        assert f"SELECT HAS_PERMS_BY_NAME(DB_NAME(), 'DATABASE', '{yetki}')" in sunucu.sorgular


def test_a_bare_table_is_asked_about_in_dbo_and_a_qualified_one_in_its_own_schema():
    _, sunucu = denetle()

    assert "SELECT HAS_PERMS_BY_NAME('dbo.TBLSTSABIT', 'OBJECT', 'SELECT')" in sunucu.sorgular
    assert "SELECT HAS_PERMS_BY_NAME('Sales.Customers', 'OBJECT', 'SELECT')" in sunucu.sorgular


# --------------------------------------------------------------------------------- güçlü girişler


@pytest.mark.parametrize(
    "anahtar, denetim",
    [
        ("IS_SRVROLEMEMBER", "sysadmin"),
        ("IS_MEMBER", "db_owner"),
        ("'INSERT'", "insert"),
        ("'EXECUTE'", "execute"),
    ],
)
def test_a_login_that_writes_or_manages_is_refused_with_the_explanation(anahtar, denetim):
    rapor, _ = denetle({anahtar: 1})

    assert rapor["ok"] is False
    assert satir(rapor, denetim) == {"check": denetim, "ok": False, "message": POWER_MESSAGE}
    assert all(line["ok"] for line in rapor["lines"] if line["check"] != denetim)
    # refusal points at the read-only login script that has to be run instead
    assert rapor["login_script_url"] == BETIK


# --------------------------------------------------------------------------------- tablo örnekleri


def test_the_tables_the_login_cannot_see_are_listed():
    # TBLCAHAR için sunucu 0 (yetki yok) diyor, TBLFATUIRS için NULL (tablo yok).
    rapor, _ = denetle({"TBLCAHAR": 0, "TBLFATUIRS": None})

    assert rapor["missing_tables"] == ["TBLCAHAR", "TBLFATUIRS"]
    assert [line["message"] for line in tablolarin_satirlari(rapor) if not line["ok"]] == [
        "TBLCAHAR bu girişle okunamıyor: tablo yok ya da SELECT yetkisi yok.",
        "TBLFATUIRS bu girişle okunamıyor: tablo yok ya da SELECT yetkisi yok.",
    ]
    # eksik tablo bir yazma yetkisi değildir: bildirilir, kaydı engellemez
    assert rapor["ok"] is True


def test_only_a_sample_of_the_tables_is_asked_about():
    yirmi = [f"TBL{i:02d}" for i in range(1, 26)]

    rapor, sunucu = denetle(tablolar=yirmi)

    assert len(tablolarin_satirlari(rapor)) == config.CONN_TABLE_SAMPLE
    assert rapor["missing_tables"] == []
    assert len(sunucu.sorgular) == len(GUCLER) + config.CONN_TABLE_SAMPLE


# --------------------------------------------------------------------------------- bağlanamama


def test_a_connect_error_carrying_the_password_is_one_scrubbed_line():
    def baglan(_dize):
        raise RuntimeError(f"[28000] Login failed for user 'bilgin_ro'; PWD={PAROLA}; tekrar deneyin.")

    rapor = readonly_guard(BAGLANTI, TABLOLAR, connect=baglan, login_script_url=BETIK)

    assert rapor["ok"] is False
    assert [line["check"] for line in rapor["lines"]] == ["connect"]
    assert rapor["lines"][0]["ok"] is False
    assert rapor["missing_tables"] == []
    assert "Login failed" in rapor["lines"][0]["message"]
    assert "PWD=***" in rapor["lines"][0]["message"]
    assert PAROLA not in json.dumps(rapor, ensure_ascii=False)


# ------------------------------------------------------------------------------- beklemeyen bağdaç


def test_the_connect_call_receives_the_bounded_login_timeout(monkeypatch):
    """Ölü bir sunucu raporu hiç döndürmesin: bağdaç login zaman aşımıyla çağrılır (T466)."""
    import pyodbc

    cagrilan: list[dict] = []

    def baglan(_dize, **secenek):
        cagrilan.append(secenek)
        return SahteSunucu()

    monkeypatch.setattr(pyodbc, "connect", baglan)

    assert readonly_guard(BAGLANTI, TABLOLAR, login_script_url=BETIK)["ok"] is True
    assert cagrilan == [{"timeout": guard.LOGIN_TIMEOUT_S}]

    # yavaş bir hat için tek başına genişletilir; sayı olmayan değer bağı geri verir
    monkeypatch.setenv(guard.LOGIN_TIMEOUT_ENV, "12")
    readonly_guard(BAGLANTI, TABLOLAR, login_script_url=BETIK)
    assert cagrilan[-1] == {"timeout": 12}

    monkeypatch.setenv(guard.LOGIN_TIMEOUT_ENV, "yavaş")
    readonly_guard(BAGLANTI, TABLOLAR, login_script_url=BETIK)
    assert cagrilan[-1] == {"timeout": guard.LOGIN_TIMEOUT_S}
