"""Hazır sorular: uygulamanın kendi SQLite dosyasında ``ready_questions`` (PLAN R7-17, R7-18).

Bir hazır soru tek bir kümeye ve tek bir iş rolüne aittir; ``business_role`` ``*`` ise her rol
görür, NULL ise soru kişiseldir - yalnız ``created_by`` olan kullanıcı görür ve küme başına en
fazla ``PERSONAL_CARDS`` tanesi birikir. SQL satıra onaylayanın sorusundan yazılır: istemci hiç
SQL göndermez (R7-17), kart da yalnız kayıtlı SQL'i politika ve salt okunur yürütücü üzerinden
koşar, yani model o soruya bir daha bakmaz. Kullanıcılar ve konuşmalarla aynı dosya, aynı kısa
ömürlü bağlantı biçimi: yol koşucuları iş parçacıkları arasında dolaştığı için tek bağlantı
paylaşılmaz.
"""

from __future__ import annotations

import contextlib
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from nl2sql import config

# Contracts "ready question": alan adları ve sırası burada; ``approved`` dışarı bool çıkar.
_ROW = (
    "id",
    "dataset",
    "business_role",
    "title",
    "question",
    "sql",
    "display",
    "position",
    "created_by",
    "approved",
    "audit_id",
    "created_at",
)
_SELECT = ", ".join(_ROW)

# PUT'un götürebileceği alanlar (R7-17): ``sql`` yalnız yeni bir onayın (audit_id) SQL'idir.
_UPDATABLE = ("title", "question", "sql", "display", "business_role", "position", "approved", "audit_id")

EVERY_ROLE = "*"
DISPLAYS = ("number", "chart", "table")

NOT_FOUND_MESSAGE = "Hazır soru bulunamadı."
BAD_ROLE_MESSAGE = "Geçersiz iş rolü."
BAD_DISPLAY_MESSAGE = "Geçersiz görünüm: number, chart ya da table olmalı."
CAP_MESSAGE = f"En fazla {config.PERSONAL_CARDS} kişisel kart ekleyebilirsiniz."

_CREATE = """
CREATE TABLE IF NOT EXISTS ready_questions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dataset TEXT NOT NULL,
  business_role TEXT,
  title TEXT NOT NULL,
  question TEXT NOT NULL,
  sql TEXT NOT NULL,
  display TEXT NOT NULL CHECK (display IN ('number', 'chart', 'table')),
  position INTEGER NOT NULL DEFAULT 0,
  created_by TEXT,
  approved INTEGER NOT NULL DEFAULT 0,
  audit_id TEXT,
  created_at TEXT NOT NULL
)
"""


class ReadyError(Exception):
    """Hazır soru işleminin reddi: mesajı ve HTTP durumuyla birlikte taşınır (R6-3'ün biçimi)."""

    def __init__(self, message: str, status: int) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


class ReadyStore:
    """``ready_questions`` tablosunun tek kapısı: ekle, değiştir, sil, oku, listele."""

    def __init__(
        self, path: str | Path | None = None, clock: Callable[[], float] = time.time
    ) -> None:
        # Yolu çağıran söylemezse R6-1'in okuyucusu: testler atık dosyada koşar, data/bilgin.db'ye dokunulmaz.
        self.path = Path(config.app_db_path() if path is None else path)
        self.clock = clock
        with _connect(self.path) as conn:
            conn.execute(_CREATE)

    def add(
        self,
        dataset: str,
        business_role: str | None,
        title: str,
        question: str,
        sql: str,
        display: str,
        position: int = 0,
        created_by: str | None = None,
        approved: bool = False,
        audit_id: str | None = None,
    ) -> dict:
        """Satırı açar ve public sözlüğünü döndürür.

        ``business_role`` None ise kart kişiseldir ve ``created_by`` kimin kartı olduğunu söyler;
        kişisel kartlarda ``PERSONAL_CARDS`` sınırı burada kurulur (R7-17).
        """
        _check_role(business_role)
        _check_display(display)
        if business_role is None:
            self._check_cap(dataset, created_by)
        with _connect(self.path) as conn:
            id = conn.execute(
                "INSERT INTO ready_questions (dataset, business_role, title, question, sql, display,"
                " position, created_by, approved, audit_id, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    dataset,
                    business_role,
                    title,
                    question,
                    sql,
                    display,
                    int(position),
                    created_by,
                    1 if approved else 0,
                    audit_id,
                    self._now_iso(),
                ),
            ).lastrowid
        return self.get(id)

    def get(self, id: int) -> dict | None:
        """Kimliğe göre satır; yoksa None (404'ü çağıran kendi verir)."""
        with _connect(self.path) as conn:
            row = conn.execute(
                f"SELECT {_SELECT} FROM ready_questions WHERE id = ?", (id,)
            ).fetchone()
        return _card(row) if row else None

    def update(self, id: int, **fields) -> dict:
        """Sözleşmenin alanlarını değiştirir; söylenmeyen alan olduğu gibi kalır (R7-17 PUT).

        ``business_role=None`` kartı kişiselleştirir, ``audit_id`` ile birlikte verildiğinde
        ``sql`` yeni onayın SQL'idir - ikisini de çağıran birlikte söyler.
        """
        unknown = sorted(set(fields) - set(_UPDATABLE))
        if unknown:
            raise ReadyError(f"Tanınmayan hazır soru alanı: {', '.join(unknown)}", 422)
        if "business_role" in fields:
            _check_role(fields["business_role"])
        if "display" in fields:
            _check_display(fields["display"])
        if self.get(id) is None:
            raise ReadyError(NOT_FOUND_MESSAGE, 404)
        if fields:
            sets = ", ".join(
                f"{column} = ?" for column in _UPDATABLE if column in fields
            )
            with _connect(self.path) as conn:
                conn.execute(
                    f"UPDATE ready_questions SET {sets} WHERE id = ?",
                    (*(_value(fields[column]) for column in _UPDATABLE if column in fields), id),
                )
        return self.get(id)

    def delete(self, id: int, username: str | None = None) -> None:
        """Satırı siler; yoksa ya da ``username`` söylenmiş ve satır onunki olmayan bir kişisel kart ise 404.

        ``username`` söylenmemişse yöneticinin silmesidir (yolun yetkisi ROUTE_ROLES'te): kişisel
        kart dahil her satır silinir. Başkasının kişisel kartı bulunamadığı için 403 değil 404
        çıkar - R7-17'nin satırı; kart kimin olduğu bilgisini sızdırmaz.
        """
        clauses, args = ["id = ?"], [id]
        if username is not None:
            clauses.append("(business_role IS NOT NULL OR created_by = ?)")
            args.append(username)
        with _connect(self.path) as conn:
            if not conn.execute(
                f"DELETE FROM ready_questions WHERE {' AND '.join(clauses)}", args
            ).rowcount:
                raise ReadyError(NOT_FOUND_MESSAGE, 404)

    def list_all(self, dataset: str, pending: bool | None = None) -> list[dict]:
        """Kümenin bütün satırları (yönetici ekranı): ``pending`` True onay bekleyenler, False onaylılar, None hepsi."""
        clauses, args = ["dataset = ?"], [dataset]
        if pending is not None:
            clauses.append("approved = ?")
            args.append(0 if pending else 1)
        with _connect(self.path) as conn:
            rows = conn.execute(
                f"SELECT {_SELECT} FROM ready_questions WHERE {' AND '.join(clauses)}"
                " ORDER BY position, id",
                args,
            ).fetchall()
        return [_card(row) for row in rows]

    def list_for(
        self, dataset: str, business_role: str | None, username: str | None = None
    ) -> list[dict]:
        """Başlangıç ekranının kartları: onaylı rol kartları (kendi rolü ve ``*``) + kişinin kendi kişisel kartları.

        Onaylanmamış satır burada hiç yoktur (R7-18); ``business_role`` None ise ``*`` ve
        kişisel kartlar kalır. Sıra ``position``, sonra kimlik.
        """
        visible = "business_role IN (?, ?)"
        args = [dataset, business_role, EVERY_ROLE]
        if username is not None:
            visible = f"({visible} OR (business_role IS NULL AND created_by = ?))"
            args.append(username)
        with _connect(self.path) as conn:
            rows = conn.execute(
                f"SELECT {_SELECT} FROM ready_questions"
                f" WHERE dataset = ? AND approved = 1 AND ({visible}) ORDER BY position, id",
                args,
            ).fetchall()
        return [_card(row) for row in rows]

    # ------------------------------------------------------------------ internals

    def _check_cap(self, dataset: str, created_by: str | None) -> None:
        """Kişisel kart sayısı küme başına ``PERSONAL_CARDS``ı geçemez (R7-17).

        ASSUMPTION: sınır küme başınadır - kişi kartı yalnız o kümenin başlangıç ekranında görür,
        öteki kümenin kartları onun kotasını yemez.
        """
        with _connect(self.path) as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM ready_questions"
                " WHERE dataset = ? AND business_role IS NULL AND created_by = ?",
                (dataset, created_by),
            ).fetchone()[0]
        if n >= config.PERSONAL_CARDS:
            raise ReadyError(CAP_MESSAGE, 409)

    def _now_iso(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(timespec="seconds")


def _check_role(business_role: str | None) -> None:
    if business_role is None or business_role == EVERY_ROLE:
        return
    if business_role not in config.BUSINESS_ROLES:
        raise ReadyError(BAD_ROLE_MESSAGE, 422)


def _check_display(display: str) -> None:
    if display not in DISPLAYS:
        raise ReadyError(BAD_DISPLAY_MESSAGE, 422)


def _value(value):
    """Bool satıra 0/1 olarak yazılır (SQLite'ta bool kolonu yok)."""
    return int(value) if isinstance(value, bool) else value


def _card(row: tuple) -> dict:
    card = dict(zip(_ROW, row))
    card["approved"] = bool(card["approved"])
    return card


@contextlib.contextmanager
def _connect(path: Path):
    """Kısa ömürlü bağlantı: gereken klasör açılır, başarılı işlem yerine konur."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()
