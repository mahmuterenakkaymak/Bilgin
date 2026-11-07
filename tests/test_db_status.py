# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T337: veritabanı durum denetleyicisi (PLAN R7-25, Contracts "health db").

Hiçbir istek denetim için beklemez: bir iş parçacığı ``DB_CHECK_S`` aralığıyla SELECT 1 atar,
``state`` yalnızca son cevabı okur; bağlantı değiştiğinde ya da sorgu bağlantı hatasıyla
düştüğünde ``kick`` turu bekletmez. Gerçek SQL Server çağrılmaz: ping dışarıdan alınır, sürücü
cümlesindeki parola ``connections.scrub`` ile silinir.
"""

from __future__ import annotations

import contextlib
import json
import sys
import time

import pytest

from bilgin import config
from bilgin.engine import dbstatus
from bilgin.engine.dbstatus import DOWN_MESSAGE, DbStatus, looks_like_connection_error

PAROLA = "Gizli2026!parola"
BAGLANTI = (
    "DRIVER={ODBC Driver 18 for SQL Server};SERVER=10.0.0.5;DATABASE=WWI;"
    f"UID=bilgin_ro;PWD={PAROLA};"
)
# Sürücünün bağlanamama cümlesi: hem parolayı hem de hata kodunu taşır.
HATA = (
    "[08001] [Microsoft][ODBC Driver 18 for SQL Server]TCP Provider: "
    f"Login failed for user 'bilgin_ro'; PWD={PAROLA};"
)
SAAT = 1_800_000_000.0  # sabit saat: checked_at 2027-01-15T08:00:00+00:00 olur


class SahtePing:
    """SELECT 1'in yerine geçen sayaç; ``bozuk`` olduğu anda sürücü cümlesiyle düşer."""

    def __init__(self, bozuk: bool = False, yavas: float = 0.0) -> None:
        self.bozuk = bozuk
        self.yavas = yavas
        self.sayi = 0

    def __call__(self, conn_str: str, timeout: float) -> None:
        self.sayi += 1
        if self.yavas:
            time.sleep(self.yavas)
        if self.bozuk:
            raise RuntimeError(HATA)


class SahteBaglanti:
    """pyodbc bağlantısı gibi davranan kayıtçı: çalıştırılan sorguları ve kapanmayı yazar."""

    def __init__(self, hata: Exception | None = None) -> None:
        self.hata = hata
        self.sorgular: list[str] = []
        self.kapandi = False

    def cursor(self) -> "SahteBaglanti":
        return self

    def execute(self, sql: str) -> "SahteBaglanti":
        self.sorgular.append(sql)
        if self.hata:
            raise self.hata
        return self

    def fetchone(self) -> tuple:
        return (1,)

    def close(self) -> None:
        self.kapandi = True


class SahteSurucu:
    """sys.modules'a konan sahte pyodbc: connect'in argümanlarını ve açtığı bağlantıyı tutar."""

    def __init__(self, hata: Exception | None = None) -> None:
        self.hata = hata
        self.baglanti: SahteBaglanti | None = None
        self.connect_kwargs: dict = {}

    def connect(self, conn_str: str, **kwargs) -> SahteBaglanti:
        self.connect_kwargs = kwargs
        self.baglanti = SahteBaglanti(hata=self.hata)
        return self.baglanti


def durum(pinger, resolve=None):
    """Çözücüsü tek bir mssql bağlantısı olan bir veri kümesini gösteren durum."""
    return DbStatus(
        resolve or (lambda _veri_kumesi: {"source": "stored", "conn_str": BAGLANTI}),
        ping=pinger,
        clock=lambda: SAAT,
    )


@contextlib.contextmanager
def calisan(pinger, resolve=None, interval: float = 600.0):
    """İş parçacığını çalıştıran durum; aralık bilinçli olarak uzun, test bitince durur."""
    status = durum(pinger, resolve)
    status.start(interval)
    try:
        yield status
    finally:
        status.stop()


def bekle(kosul, sure: float = 2.0) -> bool:
    """Koşul sağlanana kadar kısa aralıklarla dener; arka plan iş parçacığı için bekleyiş."""
    son = time.perf_counter() + sure
    while time.perf_counter() < son:
        if kosul():
            return True
        time.sleep(0.01)
    return False


# ------------------------------------------------------------------------------ bağlantısı olmayan

def test_a_dataset_without_a_connection_is_none_and_never_pinged():
    pinger = SahtePing()
    status = durum(pinger, resolve=lambda _veri_kumesi: {"source": "none"})

    assert status.state("synthetic_erp") == {
        "state": "none",
        "checked_at": None,
        "message": None,
        "message_admin": None,
    }
    assert status.check_now("synthetic_erp")["state"] == "none"
    assert pinger.sayi == 0


def test_a_resolve_answer_that_carries_no_conn_str_key_is_none_too():
    status = durum(SahtePing(), resolve=lambda _veri_kumesi: {"source": "none"})

    assert status.check_now("wwi_real")["state"] == "none"


# ------------------------------------------------------------------------------ ok -> down -> ok


def test_the_first_read_answers_unknown_and_the_check_follows_it():
    with calisan(SahtePing()) as status:
        assert status.state("wwi_real") == {
            "state": "unknown",
            "checked_at": None,
            "message": None,
            "message_admin": None,
        }
        assert bekle(lambda: status.state("wwi_real")["state"] == "ok")


def test_a_failure_turns_the_state_down_and_a_recovery_back_to_ok():
    pinger = SahtePing()
    status = durum(pinger)

    assert status.check_now("wwi_real")["state"] == "ok"

    pinger.bozuk = True
    down = status.check_now("wwi_real")
    assert down["state"] == "down"
    assert down["message"] == DOWN_MESSAGE
    assert "08001" in down["message_admin"]

    pinger.bozuk = False
    assert status.check_now("wwi_real")["state"] == "ok"
    assert status.state("wwi_real")["message"] is None
    assert status.state("wwi_real")["message_admin"] is None


def test_a_read_never_pings_again():
    pinger = SahtePing()
    status = durum(pinger)
    status.check_now("wwi_real")

    sayi = pinger.sayi
    for _ in range(5):
        status.state("wwi_real")

    assert pinger.sayi == sayi


def test_the_checked_at_comes_from_the_injected_clock():
    assert durum(SahtePing()).check_now("wwi_real")["checked_at"].startswith("2027-01-15T08:00:00")


# --------------------------------------------------------------------------------- scrub


def test_the_admin_message_keeps_the_driver_sentence_and_loses_the_password():
    cevap = durum(SahtePing(bozuk=True)).check_now("wwi_real")

    assert cevap["message"] == DOWN_MESSAGE
    assert "PWD=***" in cevap["message_admin"]
    assert "Login failed" in cevap["message_admin"]
    assert PAROLA not in json.dumps(cevap, ensure_ascii=False)
    # yönetici satırı bir bağlantı hatası olarak tanınır: sorgu bunu görince kick eder
    assert looks_like_connection_error(cevap["message_admin"])


# --------------------------------------------------------------------------------- kick / tur


def test_kick_runs_a_check_without_waiting_for_the_interval():
    pinger = SahtePing()
    with calisan(pinger) as status:
        status.check_now("wwi_real")
        assert pinger.sayi == 1

        pinger.bozuk = True
        status.kick()

        assert bekle(lambda: status.state("wwi_real")["state"] == "down")
        assert pinger.sayi == 2


def test_the_loop_checks_again_on_its_own():
    pinger = SahtePing()
    with calisan(pinger, interval=0.05) as status:
        status.check_now("wwi_real")

        pinger.bozuk = True

        assert bekle(lambda: status.state("wwi_real")["state"] == "down")


def test_a_slow_ping_never_blocks_a_read():
    pinger = SahtePing(yavas=0.25)
    with calisan(pinger) as status:
        bas = time.perf_counter()
        assert status.state("wwi_real")["state"] == "unknown"
        assert time.perf_counter() - bas < 0.1

        assert bekle(lambda: status.state("wwi_real")["state"] == "ok")

        status.kick()  # yeni deneme sürerken bile okuma beklemiyor
        bas = time.perf_counter()
        assert status.state("wwi_real")["state"] == "ok"
        assert time.perf_counter() - bas < 0.1


# --------------------------------------------------------------------------------- ping


def test_the_ping_is_a_select_one_within_the_check_timeout(monkeypatch):
    surucu = SahteSurucu()
    monkeypatch.setitem(sys.modules, "pyodbc", surucu)

    dbstatus.ping(BAGLANTI)

    assert surucu.baglanti.sorgular == ["SELECT 1"]
    assert surucu.connect_kwargs["timeout"] == config.DB_CHECK_TIMEOUT_S
    assert surucu.baglanti.kapandi is True


def test_a_ping_that_fails_still_closes_and_raises(monkeypatch):
    surucu = SahteSurucu(hata=RuntimeError(HATA))
    monkeypatch.setitem(sys.modules, "pyodbc", surucu)

    with pytest.raises(RuntimeError, match="08001"):
        dbstatus.ping(BAGLANTI, timeout=1)

    assert surucu.connect_kwargs["timeout"] == 1
    assert surucu.baglanti.kapandi is True


# ------------------------------------------------------------------ bağlantı hatası mı, sorgu mu


@pytest.mark.parametrize(
    "cumle",
    [
        "[08001] Bağlantı kurulamadı.",
        "[08S01] Connection is busy.",
        "Login failed for user 'bilgin_ro'.",
        "[TCP Provider]: Hedef makine etkin olarak reddetti.",
    ],
)
def test_a_connection_failure_looks_like_one(cumle):
    assert looks_like_connection_error(cumle) is True


@pytest.mark.parametrize(
    "cumle",
    ["Incorrect syntax near 'FROM'.", "Sorgu zaman sınırını aştı.", "Satır sayısı 50 ile sınırlı.", "", None],
)
def test_any_other_error_does_not(cumle):
    assert looks_like_connection_error(cumle) is False
