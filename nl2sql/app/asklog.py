"""Soru günlüğü: her ``ask_payload`` çağrısı ``logs/asks.jsonl`` dosyasına tek satır bırakır.

Satır hiçbir zaman veri taşımaz: alanlar tek tek, sözleşme sırasıyla yazılır, ``rows`` ve
sözleşmede olmayan her anahtar atılır. Geçmiş ve dışa aktarım aynı dosyadan okur; yürütücünün
denetim satırları ``<kaynak>:<audit_id>`` taşıdığı için iki günlük ``audit_id`` ile birleşir.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from nl2sql import config

# PLAN "ask record": alan adları ve varsayılanları burada, değerler çağırandan gelir.
_FIELDS = {
    "ts": "",
    "audit_id": "",
    "source": "",
    "dataset": "",
    "mode": "",
    "question": "",
    "choice": None,
    "status": "",
    "sql": "",
    "row_count": 0,
    "error": None,
}


def new_audit_id() -> str:
    """Bir sorunun kimliği: ``uuid4().hex`` ilk 12 karakteri (PLAN R5-4)."""
    return uuid.uuid4().hex[:12]


def record_ask(entry: dict, path: str | Path = config.ASK_LOG) -> None:
    """Sözleşme alanlarını tek UTF-8 satırı olarak ekler; ``rows`` ve fazlası diske gitmez."""
    record = {key: entry.get(key, default) for key, default in _FIELDS.items()}
    # ASSUMPTION: AskPayload'da ts yok, o yüzden boş ts burada üretilir (denetim günlüğüyle aynı biçim).
    if not record["ts"]:
        record["ts"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def history(path: str | Path = config.ASK_LOG, n: int = config.HISTORY_N) -> list[dict]:
    """Son n kayıt, en yeni önce, ``source`` alanı olmadan; dosya yoksa boş liste."""
    items = []
    for record in _records(path):
        items.append({key: value for key, value in record.items() if key != "source"})
        if len(items) >= n:
            break
    return items


def find_ask(audit_id: str, path: str | Path = config.ASK_LOG) -> dict | None:
    """``audit_id``li kaydı en yeniden eskiye arar; yoksa None (dışa aktarım SQLi buradan alır)."""
    return next((record for record in _records(path) if record.get("audit_id") == audit_id), None)


def _records(path: str | Path) -> Iterator[dict]:
    """Diskteki kayıtlar, en yeni önce; boş ve bozuk satırlar atlanır, dosya yoksa hiçbir şey."""
    path = Path(path)
    if not path.is_file():
        return
    for line in reversed(path.read_text(encoding="utf-8").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            yield record
