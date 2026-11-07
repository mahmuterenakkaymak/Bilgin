# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Konuşmalar: uygulamanın kendi SQLite dosyasında conversations ve turns (PLAN R7-2).

Bir konuşma tek bir kullanıcıya ve tek bir kümeye aittir; başkasının konuşması bu kapıdan hiç
görünmez - ``get`` None döner, 404'ü çağıran kendi verir (R6-9'un yolu gibi). ``turns`` bir turun
sonraki tura miras bırakacağı kadarını taşır: kolon adları, satır sayısı, maskelenmiş en fazla
``CONV_KEEP_ROWS`` satır ve olgular, yani sonucun tamamı değil. Kayıtlı sorular ve kullanıcılarla
aynı dosya, aynı kısa ömürlü bağlantı biçimi: FastAPI yol koşucuları iş parçacıkları arasında
dolaştığı için tek bağlantıyı paylaşmak güvenli olmaz.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

from bilgin import config

# Contracts "conversation item", "StoredTurn", "history turn": alan adları ve sırası burada,
# değerler çağırandan gelir. summary_json okunurken her zaman "summary" olur.
_CONVERSATION_ROW = ("id", "username", "dataset", "created_at", "updated_at", "title")
_ITEM_ROW = ("id", "title", "dataset", "created_at", "updated_at")
_ITEM_FIELDS = _ITEM_ROW + ("turns",)
_TURN_WRITE = ("question", "choice", "status", "sql", "columns_json", "summary_json", "answer_text", "audit_id")
_TURN_READ = ("n", "question", "choice", "status", "sql", "answer_text", "audit_id", "created_at", "summary_json")
_HISTORY_READ = ("n", "question", "choice", "sql", "summary_json")

# Kullanıcısı söylenmemiş okuma = herkesin konuşması: yöneticinin görünümü (SavedStore ile aynı).
ALL = object()

_ANSWERED = "answered"
_CLARIFICATION = "needs_clarification"

_CREATE = (
    """
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY,
  username TEXT,
  dataset TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  title TEXT NOT NULL
)
""",
    """
CREATE TABLE IF NOT EXISTS turns (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  conversation_id TEXT NOT NULL,
  n INTEGER NOT NULL,
  question TEXT NOT NULL,
  choice TEXT,
  status TEXT NOT NULL,
  sql TEXT,
  columns_json TEXT,
  summary_json TEXT,
  answer_text TEXT,
  audit_id TEXT,
  created_at TEXT NOT NULL
)
""",
)


class ConversationNotFound(Exception):
    """Konuşma yok, başkasına ait ya da başka bir kümede (PLAN R7-2, R7-7).

    Cümleyi istisnanın kendisi söyler ki API'nin ``detail``ı ile CLI'nin satırı aynı olsun.
    """

    def __init__(self) -> None:
        super().__init__("Konuşma bulunamadı.")


class ConversationStore:
    """``conversations`` ve ``turns`` tablolarının tek kapısı: aç, tur ekle, oku, sil."""

    def __init__(self, path: str | Path | None = None, clock: Callable[[], float] = time.time) -> None:
        # Yolu çağıran söylemezse R6-1'in okuyucusu: testler atık dosyada koşar, data/bilgin.db'ye dokunulmaz.
        self.path = Path(config.app_db_path() if path is None else path)
        self.clock = clock
        with _connect(self.path) as conn:
            for ddl in _CREATE:
                conn.execute(ddl)

    def create(self, username: str | None = None, dataset: str | None = None, title: str = "") -> str:
        """Konuşmayı açar ve kimliğini döndürür.

        Kimlik ``uuid4().hex``: ``#/c/<id>`` adresi tahmin edilemez. ``username`` tek kullanıcılı
        kipte NULL kalır, ``title`` ilk sorunun ``CONV_TITLE_CHARS`` kadarıdır.
        """
        conversation_id = uuid.uuid4().hex
        now = self._now_iso()
        with _connect(self.path) as conn:
            conn.execute(
                "INSERT INTO conversations (id, username, dataset, created_at, updated_at, title)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (conversation_id, username, dataset, now, now, str(title)[: config.CONV_TITLE_CHARS]),
            )
        return conversation_id

    def add_turn(self, id: str, turn: dict) -> int:
        """Turu konuşmanın sonuna ekler ve numarasını (1, 2, ...) döndürür; güncellenme saati tazelenir."""
        now = self._now_iso()
        with _connect(self.path) as conn:
            n = conn.execute(
                "SELECT COALESCE(MAX(n), 0) + 1 FROM turns WHERE conversation_id = ?", (id,)
            ).fetchone()[0]
            conn.execute(
                f"INSERT INTO turns (conversation_id, n, created_at, {', '.join(_TURN_WRITE)})"
                f" VALUES (?, ?, ?, {', '.join('?' for _ in _TURN_WRITE)})",
                (id, n, now, *_turn_row(turn)),
            )
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, id))
        return n

    def complete_turn(self, id: str, n: int, turn: dict) -> int | None:
        """Bekleyen bir netleştirme turunu seçiminle tamamlar: yeni tur açmaz, aynı ``n``in üstüne yazar.

        Tur bekleyen bir netleştirme değilse None döner ve satıra dokunulmaz - çağıran o zaman
        ``add_turn``e geçer (R7-7: seçim aynı sorunun turunu tamamlar, üstüne eklemez).
        """
        with _connect(self.path) as conn:
            row = conn.execute(
                "SELECT status FROM turns WHERE conversation_id = ? AND n = ?", (id, n)
            ).fetchone()
            if row is None or row[0] != _CLARIFICATION:
                return None
            conn.execute(
                f"UPDATE turns SET {', '.join(f'{column} = ?' for column in _TURN_WRITE)}"
                " WHERE conversation_id = ? AND n = ?",
                (*_turn_row(turn), id, n),
            )
            conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (self._now_iso(), id))
        return n

    def get(self, id: str, username=ALL, dataset: str | None = None) -> dict | None:
        """Konuşmayı turlarıyla döndürür; yoksa, başkasınınsa ya da oturumun kümesinden değilse None.

        ``username`` söylenmemişse herkesin konuşması okunur (yönetici görünümü), ``dataset``
        söylenmemişse küme sorulmaz. Başkasının konuşması bulunamadığı için yol 403 değil 404 verir.
        """
        clauses, args = ["id = ?"], [id]
        if username is not ALL:
            clauses.append("username = ?")
            args.append(username)
        if dataset is not None:
            clauses.append("dataset = ?")
            args.append(dataset)
        with _connect(self.path) as conn:
            row = conn.execute(
                f"SELECT {', '.join(_CONVERSATION_ROW)} FROM conversations WHERE {' AND '.join(clauses)}",
                args,
            ).fetchone()
            if row is None:
                return None
            turns = conn.execute(
                f"SELECT {', '.join(_TURN_READ)} FROM turns WHERE conversation_id = ? ORDER BY n", (id,)
            ).fetchall()
        return {
            "conversation": dict(zip(_CONVERSATION_ROW, row)),
            "turns": [_turn_dict(_TURN_READ, item) for item in turns],
        }

    def list(self, username=ALL, dataset: str | None = None) -> list[dict]:
        """Konuşmalar, en son güncellenen önce, her biri tur sayısıyla (Contracts "conversation item")."""
        clauses, args = [], []
        if username is not ALL:
            clauses.append("username = ?")
            args.append(username)
        if dataset is not None:
            clauses.append("dataset = ?")
            args.append(dataset)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with _connect(self.path) as conn:
            rows = conn.execute(
                f"SELECT {', '.join(_ITEM_ROW)},"
                " (SELECT COUNT(*) FROM turns WHERE conversation_id = conversations.id) AS turns"
                f" FROM conversations{where} ORDER BY updated_at DESC, id DESC",
                args,
            ).fetchall()
        return [dict(zip(_ITEM_FIELDS, row)) for row in rows]

    def delete(self, id: str, username=ALL) -> bool:
        """Konuşmayı ve turlarını siler; böyle bir konuşma yoksa ya da ``username`` söylenmiş ve ona ait
        değilse False döner (yolun 404'ü buradan okunur)."""
        clause, args = ("", (id,)) if username is ALL else (" AND username = ?", (id, username))
        with _connect(self.path) as conn:
            if not conn.execute(f"DELETE FROM conversations WHERE id = ?{clause}", args).rowcount:
                return False
            conn.execute("DELETE FROM turns WHERE conversation_id = ?", (id,))
        return True

    def last_turns(self, id: str, k: int) -> list[dict]:
        """Son k yanıtlanmış tur, eskiden yeniye (Contracts "history turn").

        Yalnız ``answered`` turlar girer: bir hata ya da bekleyen netleştirme sonraki tura miras
        kalmaz (R7-3)."""
        with _connect(self.path) as conn:
            rows = conn.execute(
                f"SELECT {', '.join(_HISTORY_READ)} FROM turns"
                " WHERE conversation_id = ? AND status = ? ORDER BY n DESC LIMIT ?",
                (id, _ANSWERED, k),
            ).fetchall()
        return [_turn_dict(_HISTORY_READ, row) for row in reversed(rows)]

    def _now_iso(self) -> str:
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat(timespec="seconds")


def _turn_row(turn: dict) -> tuple:
    """Sözleşmenin sözlüğünden satır: kolonlar ve özet JSON olarak durur, fazlası diske gitmez."""
    return (
        turn.get("question", ""),
        turn.get("choice"),
        turn.get("status", ""),
        turn.get("sql"),
        _dumps(turn.get("columns")),
        _dumps(turn.get("summary")),
        turn.get("answer_text"),
        turn.get("audit_id"),
    )


def _turn_dict(columns: tuple, row: tuple) -> dict:
    turn = dict(zip(columns, row))
    turn["summary"] = _loads(turn.pop("summary_json"))
    return turn


def _dumps(value) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False)


def _loads(text: str | None):
    return json.loads(text) if text else None


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
