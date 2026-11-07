# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T388: bekçinin her yoklaması bağlantı satırına işlenir (PLAN R7-22, Contracts "connection (public)").

``mark_ok``/``mark_error``, ``last_ok_at``/``last_error``ın tek yazarlarıdır; bekçi cevabı yalnız
kendi belleğinde tuttuğu için ``GET /api/connections``ın "Son başarılı"/"Son hata" sütunları hiç
dolmazdı. Artık ``DbStatus`` gerçek her yoklamanın ardından ``record``a haber verir: sürücü
cümlesi satıra inmeden ``scrub``tan geçer, bağlantısı olmayan küme hiç yazılmaz, yazamayan bir
defter turu düşürmez.
"""

from __future__ import annotations

import json
import sys
import time
from types import SimpleNamespace

import pytest

from bilgin.cli import main as cli
from bilgin.engine.connections import ConnectionStore
from bilgin.engine.dbstatus import DbStatus

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI yalnız Windows'ta vardır")

PAROLA = "Gizli2026!parola"
BAGLANTI = (
    "DRIVER={ODBC Driver 18 for SQL Server};SERVER=10.0.0.5;DATABASE=WWI;"
    f"UID=bilgin_ro;PWD={PAROLA};"
)
# Sürücünün bağlanamama cümlesi: parolayı taşır, satıra olduğu gibi inemez.
HATA = (
    "[08001] [Microsoft][ODBC Driver 18 for SQL Server]TCP Provider: "
    f"Login failed for user 'bilgin_ro'; PWD={PAROLA};"
)
FIELDS = {"server": "10.0.0.5", "database": "WWI", "auth": "sql", "username": "bilgin_ro"}


class Ping:
    """SELECT 1'in yerine geçer; ``bozuk`` olduğu anda sürücü cümlesiyle düşer."""

    def __init__(self, bozuk: bool = False) -> None:
        self.bozuk = bozuk
        self.sayi = 0

    def __call__(self, conn_str: str, timeout: float) -> None:
        self.sayi += 1
        if self.bozuk:
            raise RuntimeError(HATA)


def cozum(**baglantilar):
    """Küme adı -> bağlantı dizesi çözücüsü; listelenmemiş küme bağlantısızdır."""

    def resolve(dataset: str) -> dict:
        conn_str = baglantilar.get(dataset)
        return {"source": "stored", "conn_str": conn_str} if conn_str else {"source": "none"}

    return resolve


def defter(store):
    """``serve``in bekçiye verdiği kayıtçının karşılığı: ok -> ``mark_ok``, değilse ``mark_error``."""

    def record(dataset: str, ok: bool, error: str | None) -> None:
        if ok:
            store.mark_ok(dataset)
        else:
            store.mark_error(dataset, error)

    return record


def bekle(kosul, sure: float = 2.0) -> bool:
    """Koşul sağlanana kadar kısa aralıklarla dener; arka plan iş parçacığı için bekleyiş."""
    son = time.perf_counter() + sure
    while time.perf_counter() < son:
        if kosul():
            return True
        time.sleep(0.01)
    return False


@pytest.fixture
def store(tmp_path):
    return ConnectionStore(tmp_path / "app.db")


# ------------------------------------------------------------------------------ yeşil satır


def test_a_ping_that_answers_writes_the_success_line(store):
    store.save("wwi_real", FIELDS, PAROLA, "eren")
    bekci = DbStatus(cozum(wwi_real=BAGLANTI), ping=Ping(), record=defter(store))

    assert bekci.check_now("wwi_real")["state"] == "ok"

    row = store.public("wwi_real")
    assert row["last_ok_at"]
    assert row["last_error"] is None
    assert row["state"] == "ok"


# ------------------------------------------------------------------------------ kırmızı satır


def test_a_failure_writes_the_scrubbed_sentence_and_keeps_the_old_success(store):
    store.save("wwi_real", FIELDS, PAROLA, "eren")
    pinger = Ping()
    bekci = DbStatus(cozum(wwi_real=BAGLANTI), ping=pinger, record=defter(store))
    bekci.check_now("wwi_real")
    onceki = store.public("wwi_real")["last_ok_at"]

    pinger.bozuk = True
    assert bekci.check_now("wwi_real")["state"] == "down"

    row = store.public("wwi_real")
    assert row["state"] == "down"
    assert PAROLA not in row["last_error"]
    assert "08001" in row["last_error"]
    assert row["last_ok_at"] == onceki


# ------------------------------------------------------------------------ bağlantısı olmayan küme


def test_a_dataset_with_no_connection_writes_nothing(store):
    store.save("wwi_real", FIELDS, PAROLA, "eren")
    pinger = Ping()
    bekci = DbStatus(cozum(), ping=pinger, record=defter(store))

    assert bekci.check_now("wwi_real")["state"] == "none"
    assert pinger.sayi == 0  # yoklama hiç koşulmadı

    assert store.public("wwi_real")["last_ok_at"] is None
    assert store.public("wwi_real")["state"] == "unknown"


# ---------------------------------------------------------------------------- bozuk defter


def test_a_recorder_that_raises_leaves_the_checker_asking():
    def bozuk(dataset: str, ok: bool, error: str | None) -> None:
        raise RuntimeError("defter yazılamıyor")

    bekci = DbStatus(cozum(wwi_real=BAGLANTI), ping=Ping(), record=bozuk)
    bekci.start(0.05)
    try:
        assert bekci.state("wwi_real")["state"] == "unknown"  # ilk okuma turu başlatır
        assert bekle(lambda: bekci.state("wwi_real")["state"] == "ok")
    finally:
        bekci.stop()


# --------------------------------------------------------------------------- serve'in kurulumu


def test_serve_hands_its_checker_the_same_ledger(tmp_path, store):
    """``--db-probe-file`` yoklamayı dosyadan alır: defter yine bağlantı satırıdır, sunucu değil."""
    probe = tmp_path / "probe.json"
    probe.write_text(json.dumps({"status": {"wwi_real": "ok"}}), encoding="utf-8")
    store.save("wwi_real", FIELDS, PAROLA, "eren")

    bekci = cli._db_status(store, SimpleNamespace(name="wwi_real"), probe)

    assert bekci.check_now("wwi_real")["state"] == "ok"
    assert store.public("wwi_real")["last_ok_at"]
