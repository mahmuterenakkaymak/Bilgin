# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Kart sonuçları ve kısa ömürlü önbellek: başlangıç ekranının kartları (PLAN R7-18).

Bir kart onaylı bir hazır sorunun kayıtlı SQL'idir; burada bir daha modele sorulmaz, yalnız salt
okunur yürütücüden geçer. ``card_result`` tek kartın yükünü üretir: tek sayı ``number`` (değer +
kolonun şema açıklamasının başı), grafiği olan sonuç ``chart``, ötekiler ``table``; yürütme hatası
kartın kendi cümlesidir ve öteki kartları etkilemez. ``StartCache`` aynı kartı ``START_CACHE_S``
içinde bir daha koşturmaz: anahtar (küme, kart, SQL ve görünen özeti), tek uçuş için anahtar
başına bir kilit - iki kullanıcı aynı TTL'de tek yürütme görür. "Yenile" TTL'i aşar ama kart başına
``CARD_REFRESH_MIN_S``'te birden fazla değil.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone
from decimal import Decimal

from bilgin import config
from bilgin.engine.result import Budget
from bilgin.i18n import t
from bilgin.report.chart import chart_spec
from bilgin.report.shape import NUMBER, column_kinds

# Kolonun şema açıklamasının başı: ilk cümle, yani ilk noktaya kadar; nokta yoksa tüm metin.
_SENTENCE = re.compile(r"^\s*[^.]*\.")


class RefreshTooSoon(Exception):
    """Kart ``CARD_REFRESH_MIN_S`` içinde yenilendi; ``seconds_left`` sn sonra yeniden denenmeli (R7-18)."""

    def __init__(self, seconds_left: int, lang: str | None = None) -> None:
        super().__init__(t("card.refresh_too_soon", lang, n=seconds_left))
        self.seconds_left = seconds_left


def card_result(executor, card: dict, source: str = "", lang: str | None = None) -> dict:
    """Kartın yükü: SQL'i yürütür, ``display``e göre number/chart/table ya da hata cümlesi üretir.

    Yürütücü hatasının cümlesi kataloğundur - kart, sohbetin aynı hatada söylediğini söyler (R8-5);
    öteki kartlar bundan etkilenmez. Etiket, tek sayının kolonunun şema açıklamasının başıdır -
    şemada karşılığı yoksa alias'ın okunuşu. Tablo kartı ~380px kartta sığmayan kolonları değil,
    ölçüyü gösterir: bkz. ``_table_columns``.
    """
    result = executor.execute(card["sql"], Budget(max_rows=config.UI_MAX_ROWS), source)
    payload = {
        "id": card["id"],
        "title": card["title"],
        "question": card["question"],
        "display": card["display"],
        "personal": card["business_role"] is None,
    }
    if result.error is not None:
        payload["error"] = t(f"ask.fail.exec:{result.error.kind}", lang)
        return payload
    columns, rows = result.columns, result.rows
    if card["display"] == "number":
        payload["value"] = _number(rows[0][0]) if rows and rows[0] else None
        payload["label"] = _column_label(executor, columns[0] if columns else "")
    elif card["display"] == "chart":
        payload["chart"] = chart_spec(columns, rows, card["question"])
    else:
        keep = _table_columns(columns, rows)
        payload["columns"] = [columns[i] for i in keep]
        payload["rows"] = [[row[i] for i in keep] for row in rows[: config.CARD_TABLE_ROWS]]
    return payload


class StartCache:
    """Kart yüklerinin kısa ömürlü önbelleği: anahtar (küme, kart, SQL ve görünen özeti, dil), tek uçuş kilidi.

    ``get`` TTL içindeki ikinci çağrıyı yürütmeden önbellekten döndürür; ``refresh`` TTL'i aşar ama
    kart başına ``CARD_REFRESH_MIN_S``'te birden fazlası ``RefreshTooSoon``dır. Yürütücü kurucuda bir
    kez verilir - başlangıç ekranının bütün kartları aynı oturumun yürütücüsünden koşar.
    """

    def __init__(
        self, executor, ttl: float | None = None, clock: Callable[[], float] = time.time
    ) -> None:
        self._executor = executor
        self._ttl = config.START_CACHE_S if ttl is None else ttl
        self._clock = clock
        self._guard = threading.Lock()
        self._locks: dict[tuple, threading.Lock] = {}
        self._entries: dict[tuple, tuple[float, dict]] = {}
        self._refreshed: dict[tuple, float] = {}

    def get(self, card: dict, source: str = "", lang: str | None = None) -> dict:
        """Kartın yükü: TTL içinde önbellekten, değilse tek uçuşla bir kez yürütülerek."""
        key = self._key(card, lang)
        with self._lock_for(key):
            entry = self._entries.get(key)
            if entry is not None and self._clock() - entry[0] < self._ttl:
                return entry[1]
            return self._store(key, card, source, self._clock(), lang)

    def refresh(self, card: dict, source: str = "", lang: str | None = None) -> dict:
        """TTL'i aşan yeniden yürütme; kart başına ``CARD_REFRESH_MIN_S``'te birden fazlası reddedilir."""
        key, card_key = self._key(card, lang), (card["dataset"], card["id"])
        with self._lock_for(key):
            now = self._clock()
            last = self._refreshed.get(card_key)
            if last is not None:
                left = config.CARD_REFRESH_MIN_S - (now - last)
                if left > 0:
                    raise RefreshTooSoon(math.ceil(left), lang)
            self._refreshed[card_key] = now
            return self._store(key, card, source, now, lang)

    # ------------------------------------------------------------------ internals

    def _store(self, key: tuple, card: dict, source: str, now: float, lang: str | None) -> dict:
        payload = dict(card_result(self._executor, card, source, lang), refreshed_at=_iso(now))
        self._entries[key] = (now, payload)
        return payload

    def _key(self, card: dict, lang: str | None = None) -> tuple:
        # Özet kartın görünenini de kapsar: PUT (audit_id) SQL'e dokunmadan başlığı ya da
        # görünümü değiştirirse kartın eski yükü TTL boyunca tahtada kalmasın. Dil de anahtardır:
        # hatanın cümlesi onunla kurulur, yani bir dilin yükü ötekine TTL boyunca miras olmaz.
        meta = "\x00".join((card["sql"], card["title"], card["question"], card["display"]))
        digest = hashlib.sha256(meta.encode("utf-8")).hexdigest()
        return (card["dataset"], card["id"], digest, lang)

    def _lock_for(self, key: tuple) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())


def _table_columns(columns: list[str], rows: list[tuple]) -> list[int]:
    """Kart tablosunun kolon indeksleri: her sayısal kolon ve en dar tek metin kolonu.

    Başlıklar ve hücreler ``nowrap``: ~380px kartta üçüncü kolon sağına sığmıyor ve kullanıcının
    sorusu ölçtüğü kolonu hiç görmüyor. Ölçü her zaman kalsın diye metin kolonlarından en uzunu
    düşer - tam tablo kart açılınca zaten görünüyor. Satır yoksa düşecek geniş hücre de yoktur.
    """
    if not rows:
        return list(range(len(columns)))
    kinds = column_kinds(columns, rows)
    numbers = [i for i, kind in enumerate(kinds) if kind == NUMBER]
    texts = [i for i, kind in enumerate(kinds) if kind != NUMBER]
    if len(texts) > 1:
        texts = [min(texts, key=lambda i: _column_width(i, columns, rows))]
    return sorted(numbers + texts)


def _column_width(index: int, columns: list[str], rows: list[tuple]) -> int:
    """Kolonun karttaki genişliği: en uzun hücre; başlık ondan kısaysa başlığın kendisi."""
    cells = [len(str(row[index])) for row in rows if row[index] is not None]
    return max([len(columns[index])] + cells)


def _number(value):
    """JSON'un taşıdığı sayı: Decimal ondalık olarak yazılamaz, float'a döner."""
    return float(value) if isinstance(value, Decimal) else value


def _column_label(executor, column: str) -> str:
    """Kolonun şema açıklamasının başı; şemada karşılığı ya da açıklaması yoksa alias'ın okunuşu.

    ASSUMPTION: imza yürütücüyü veriyor, şemayı ayrı söylemiyor - yürütücü kendi şemasını
    (``pii_schema``) taşıdığı için etiket oradan okunur.
    """
    schema = getattr(executor, "_pii_schema", None)
    for table in (schema or {}).get("tables", []):
        for field in table["columns"]:
            if field["name"].upper() == column.upper():
                head = _SENTENCE.match(field["description"])
                return (head.group(0) if head else field["description"]).strip().rstrip(".").strip()
    return _alias_label(column)


def _alias_label(column: str) -> str:
    """Alias'ın kart okunuşu: web kartının ``columnLabel``ı ile aynı kural (M26 inceleme 1).

    Büyük harfli ad kelimeye döner ("MUSTERI_KARTI" → "Musteri karti"); içinde küçük harf taşıyan
    ad elle yazılmış bir addır ve olduğundan farklı yazılmaz - thread'in kolon başlığı da böyledir.
    """
    if not column or any(ch.islower() for ch in column):
        return column
    text = " ".join(word for word in column.split("_") if word).lower()
    return text[:1].upper() + text[1:]


def _iso(timestamp: float) -> str:
    return datetime.fromtimestamp(timestamp, timezone.utc).isoformat(timespec="seconds")
