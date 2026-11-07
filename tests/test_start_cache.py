# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T320: kart sonuçları ve tek uçuş önbelleği (PLAN R7-18).

Kart onaylı bir hazır sorunun kayıtlı SQL'idir; başlangıç ekranı onu salt okunur yürütücüden
geçirir, modele bir daha sormaz. ``StartCache`` aynı kartı ``START_CACHE_S`` içinde bir daha
koşturmaz: iki kullanıcı (ya da iki iş parçacığı) aynı TTL'de tek yürütme görür, TTL dolunca bir
daha koşar. "Yenile" TTL'i aşar ama kart başına ``CARD_REFRESH_MIN_S``'te birden fazla değil -
ikincisi kaç saniye kaldığını söyleyerek reddedilir. Bozuk bir SQL kartın kendi cümlesini verir;
sonraki kart yine çizilir. Etiket, tek sayının kolonunun şema açıklamasının başıdır.
"""

import threading
import time

import pytest

from bilgin import config
from bilgin.engine.executor import LocalExecutor
from bilgin.schema_map import build, doc
from bilgin.start.cards import RefreshTooSoon, StartCache

DATASET = "synthetic_erp"

TOTAL_SQL = "SELECT SUM(STHAR_GCMIK * STHAR_NF) AS NET_CIRO FROM TBLSTHAR WHERE STHAR_HTUR = 'S'"
LIST_SQL = "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT WHERE IL = 'ANKARA' ORDER BY CARI_KOD"
KDV_SQL = (
    "SELECT KDV_ORANI FROM TBLSTSABIT WHERE STOK_KODU = (SELECT MIN(STOK_KODU) FROM TBLSTSABIT)"
)
BAD_SQL = "SELECT YOK_SUTUNU FROM TBLSTSABIT"

KDV_HEAD = "Satış KDV oranı, yüzde olarak (10,00 veya 20,00)"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    """Kurulmuş sentetik ERP bir kez: yürütücü salt okunur, veriler testler arasında değişmez."""
    path = tmp_path_factory.mktemp("cards") / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


class _Counting:
    """Gerçek yürütücünün etrafında sayaç: tek uçuşun ölçümü kaç ``execute`` geldiğidir."""

    def __init__(self, inner, delay: float = 0.0) -> None:
        self._inner = inner
        self._pii_schema = inner._pii_schema
        self._delay = delay
        self.gate = threading.Event()
        self.calls = 0

    def execute(self, sql, budget=None, source=""):
        self.calls += 1
        self.gate.set()
        if self._delay:
            time.sleep(self._delay)
        return self._inner.execute(sql, budget, source)


def _cache(db, tmp_path, clock=time.time, delay: float = 0.0):
    # Şemayı open_session gibi veriyoruz: kapalı kolon yok, ama etiket şema açıklamasından okunur.
    schema = doc.load_schema()
    inner = LocalExecutor(
        db_path=db,
        allowlist=doc.allowlist(schema),
        audit_path=tmp_path / "audit.jsonl",
        pii_schema=schema,
    )
    counting = _Counting(inner, delay)
    return StartCache(counting, clock=clock), counting


def _card(id, sql, display, business_role="satis"):
    return {
        "id": id,
        "dataset": DATASET,
        "business_role": business_role,
        "title": f"Kart {id}",
        "question": "Ne kadar?",
        "sql": sql,
        "display": display,
        "position": 0,
        "created_by": None,
        "approved": True,
        "audit_id": None,
        "created_at": "2026-10-26T00:00:00+00:00",
    }


# ------------------------------------------------------------------------- tek uçuş (TTL)


def test_two_users_of_one_role_execute_each_card_once_inside_the_ttl(db, tmp_path):
    cache, counting = _cache(db, tmp_path)
    number, table = _card(1, TOTAL_SQL, "number"), _card(2, LIST_SQL, "table")

    first = [cache.get(number, "satis:ayse"), cache.get(table, "satis:ayse")]
    second = [cache.get(number, "satis:mehmet"), cache.get(table, "satis:mehmet")]

    assert counting.calls == 2, "iki kullanıcı, iki kart: her kartın SQL'i bir kez koşar"
    assert [c["id"] for c in first] == [1, 2]
    assert second[0]["value"] == first[0]["value"]
    assert second[1]["rows"] == first[1]["rows"]


def test_the_card_runs_again_after_the_ttl(db, tmp_path):
    now = [1000.0]
    cache, counting = _cache(db, tmp_path, clock=lambda: now[0])
    card = _card(1, TOTAL_SQL, "number")

    cache.get(card, "u1")
    now[0] += config.START_CACHE_S
    cache.get(card, "u1")

    assert counting.calls == 2, "TTL dolunca kart bir daha koşar"


def test_two_threads_in_the_ttl_execute_the_card_once(db, tmp_path):
    cache, counting = _cache(db, tmp_path, delay=0.05)
    card = _card(1, TOTAL_SQL, "number")
    results = []

    def user(arrive_late):
        if arrive_late:
            counting.gate.wait(2)  # geç gelen, ilki yürütürken kilitte bekler
        results.append(cache.get(card, "u"))

    threads = [threading.Thread(target=user, args=(i == 1,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert counting.calls == 1, "tek uçuş: aynı TTL'de iki iş parçacığı tek yürütme görür"
    assert len(results) == 2 and results[0]["value"] == results[1]["value"]


# ------------------------------------------------------------------------------- yenileme


def test_refresh_twice_inside_the_window_raises_with_the_seconds_left(db, tmp_path):
    cache, counting = _cache(db, tmp_path)
    card = _card(1, TOTAL_SQL, "number")

    first = cache.refresh(card, "u1")
    assert counting.calls == 1 and first["refreshed_at"]

    with pytest.raises(RefreshTooSoon) as info:
        cache.refresh(card, "u2")

    assert info.value.seconds_left == config.CARD_REFRESH_MIN_S
    assert str(info.value) == (
        f"Bu kart az önce yenilendi; {config.CARD_REFRESH_MIN_S} sn sonra yeniden deneyin."
    )
    assert counting.calls == 1, "reddedilen yenileme SQL koşturmaz"


# --------------------------------------------------------------------------- hata ve etiket


def test_a_failing_card_gives_the_error_card_and_the_next_card_still_renders(db, tmp_path):
    cache, counting = _cache(db, tmp_path)
    bad, good = _card(1, BAD_SQL, "number"), _card(2, TOTAL_SQL, "number")

    failed = cache.get(bad, "u")
    assert "error" in failed and failed["error"] and "value" not in failed

    rendered = cache.get(good, "u")
    assert "error" not in rendered and rendered["value"] is not None
    assert counting.calls == 2, "bozuk kart sonrakini yürütmeden düşürmez"


def test_a_number_card_labels_its_value_with_the_column_description_head(db, tmp_path):
    cache, _ = _cache(db, tmp_path)

    payload = cache.get(_card(1, KDV_SQL, "number"), "u")

    assert payload["display"] == "number"
    assert payload["label"] == KDV_HEAD
    assert payload["value"] is not None
