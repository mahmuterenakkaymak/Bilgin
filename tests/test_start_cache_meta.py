# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T383: önbellek anahtarı kartın görünenünü de kapsar (PLAN R7-18).

Kart yükü başlığı, soruyu ve görünümü de taşır; ``PUT /api/ready-questions/{id}`` bunları SQL'e
dokunmadan değiştirir. Özet yalnız SQL'i hash'lerse düzenlenen kart ``START_CACHE_S`` boyunca
eski başlığı ve eski number/chart/table biçimiyle çizilmeye devam eder. Anahtar artık
sql + title + question + display özetidir; "Yenile"nin kart başına limiti (küme, kart)
üzerinde durur, yani yeni anahtar eski limitin yerini almaz.
"""

import pytest

from nl2sql import config
from nl2sql.engine.executor import LocalExecutor
from nl2sql.schema_map import build, doc
from nl2sql.start.cards import RefreshTooSoon, StartCache

DATASET = "synthetic_erp"

TOTAL_SQL = "SELECT SUM(STHAR_GCMIK * STHAR_NF) AS NET_CIRO FROM TBLSTHAR WHERE STHAR_HTUR = 'S'"


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    """Kurulmuş sentetik ERP bir kez: yürütücü salt okunur, veriler testler arasında değişmez."""
    path = tmp_path_factory.mktemp("cards-meta") / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


class _Counting:
    """Gerçek yürütücünün etrafında sayaç: kaç ``execute`` geldiğinin ölçümü."""

    def __init__(self, inner) -> None:
        self._inner = inner
        self._pii_schema = inner._pii_schema
        self.calls = 0

    def execute(self, sql, budget=None, source=""):
        self.calls += 1
        return self._inner.execute(sql, budget, source)


def _cache(db, tmp_path):
    schema = doc.load_schema()
    inner = LocalExecutor(
        db_path=db,
        allowlist=doc.allowlist(schema),
        audit_path=tmp_path / "audit.jsonl",
        pii_schema=schema,
    )
    counting = _Counting(inner)
    return StartCache(counting), counting


def _card(id, sql, display, title=None, question="Ne kadar?"):
    return {
        "id": id,
        "dataset": DATASET,
        "business_role": "satis",
        "title": title or f"Kart {id}",
        "question": question,
        "sql": sql,
        "display": display,
        "position": 0,
        "created_by": None,
        "approved": True,
        "audit_id": None,
        "created_at": "2026-10-26T00:00:00+00:00",
    }


# ------------------------------------------------------------------------ düzenlenen kart


def test_an_edited_title_and_display_reach_the_board_inside_the_ttl(db, tmp_path):
    cache, counting = _cache(db, tmp_path)
    before = _card(1, TOTAL_SQL, "number")

    first = cache.get(before, "satis:ayse")
    edited = _card(
        1, TOTAL_SQL, "table", title="Net ciro tablosu", question="Aylık net ciro ne kadar?"
    )
    second = cache.get(edited, "satis:mehmet")

    assert first["title"] == "Kart 1" and first["display"] == "number"
    assert second["title"] == "Net ciro tablosu" and second["display"] == "table"
    assert second["question"] == "Aylık net ciro ne kadar?"
    assert "columns" in second and "value" not in second, "kart yeni görünümünü taşır"
    assert counting.calls == 2, "düzenlenen kart yeni anahtardır, eski yükü dönmez"


def test_an_unchanged_card_inside_the_ttl_still_runs_once(db, tmp_path):
    cache, counting = _cache(db, tmp_path)
    card = _card(1, TOTAL_SQL, "number")

    first = cache.get(card, "satis:ayse")
    second = cache.get(card, "satis:mehmet")

    assert counting.calls == 1, "görüneni değişmeyen kart TTL içinde bir daha koşmaz"
    assert second == first


def test_the_refresh_limit_follows_the_card_not_its_new_key(db, tmp_path):
    cache, counting = _cache(db, tmp_path)

    cache.refresh(_card(1, TOTAL_SQL, "number"), "admin")
    with pytest.raises(RefreshTooSoon) as info:
        cache.refresh(_card(1, TOTAL_SQL, "number", title="Yeni başlık"), "admin")

    assert info.value.seconds_left == config.CARD_REFRESH_MIN_S
    assert counting.calls == 1, "yeni anahtar kartın yenileme limitini sıfırlamaz"
