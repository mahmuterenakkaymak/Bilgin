"""Kayıtlı sorular: uygulamanın kendi SQLite dosyasında tek tablo (PLAN R5-16).

Kenar çubuğunun yükü bu kadar: sorunun metni ve SQL'i. ``data/bilgin.db`` analiz edilen
veritabanından ayrı bir dosyadır, yani bir kayıt hiçbir zaman ölçülen kümenin dosyasına
dokunmaz. Bağlantı her işlemde açılır: FastAPI yol koşucuları iş parçacıkları arasında
dolaştığı için tek bağlantıyı paylaşmak güvenli olmaz.
"""

from __future__ import annotations

import contextlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from nl2sql import config

# Contracts "saved question": id ve created_at burada üretilir, geri kalanı çağırandan gelir.
# Contracts "saved row (ext.)": username kapılarda sorulur, kaydın içinde dönmez.
_FIELDS = ("id", "question", "mode", "sql", "dataset", "created_at")

# Kullanıcısı söylenmemiş çağrı = herkesin kaydı: yöneticinin görünümü, Run 5'in davranışı.
ALL = object()

_CREATE = """
CREATE TABLE IF NOT EXISTS saved (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  question TEXT NOT NULL,
  mode TEXT,
  sql TEXT,
  dataset TEXT,
  created_at TEXT NOT NULL,
  username TEXT
)
"""


class SavedStore:
    """``saved`` tablosunun tek kapısı: ekle, en yeni önce listele, sil."""

    def __init__(self, path: str | Path = config.APP_DB_PATH) -> None:
        self.path = Path(path)
        with _connect(self.path) as conn:
            conn.execute(_CREATE)
            _add_username_column(conn)

    def add(
        self,
        question: str,
        mode: str | None = None,
        sql: str | None = None,
        # ASSUMPTION: dataset varsayılanlı, çünkü Python'da varsayılanlı parametreden sonra gelir;
        # yolu çağıran oturumun kümesini zaten kendisi biliyor (R5-16).
        dataset: str | None = None,
        username: str | None = None,
    ) -> dict:
        """Bir soruyu saklar ve sözleşmenin kaydını döndürür: soru metni ve SQL'den fazlası yok."""
        created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with _connect(self.path) as conn:
            cursor = conn.execute(
                "INSERT INTO saved (question, mode, sql, dataset, created_at, username)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (question, mode, sql, dataset, created_at, username),
            )
            values = (cursor.lastrowid, question, mode, sql, dataset, created_at)
        return dict(zip(_FIELDS, values))

    def list(self, dataset: str | None = None, username=ALL) -> list[dict]:
        """Kayıtlar, en yeni önce; ``dataset`` söylenmişse yalnız o kümenin, ``username`` söylenmişse
        yalnız o kullanıcının kayıtları (``ALL`` = herkesin kaydı, eski NULL satırlar da dahil)."""
        clauses, args = [], []
        if dataset is not None:
            clauses.append("dataset = ?")
            args.append(dataset)
        if username is not ALL:
            clauses.append("username = ?")
            args.append(username)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with _connect(self.path) as conn:
            rows = conn.execute(
                f"SELECT {', '.join(_FIELDS)} FROM saved{where} ORDER BY id DESC", args
            ).fetchall()
        return [dict(zip(_FIELDS, row)) for row in rows]

    def delete(self, id: int, username=ALL) -> bool:
        """Kaydı siler; böyle bir kayıt yoksa ya da ``username`` söylenmiş ve kayıt ona ait değilse
        False döner (yolun 404'ü buradan okunur)."""
        clause, args = ("", (id,)) if username is ALL else (" AND username = ?", (id, username))
        with _connect(self.path) as conn:
            return conn.execute(f"DELETE FROM saved WHERE id = ?{clause}", args).rowcount > 0


def _add_username_column(conn) -> None:
    """Run 5'in dosyasında bu kolon yok: dosya yerinde büyür, eski satır NULL kalır (R6-9)."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(saved)")}
    if "username" not in columns:
        conn.execute("ALTER TABLE saved ADD COLUMN username TEXT")


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
