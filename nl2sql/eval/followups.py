"""Ardışık soru zincirlerinin ölçümü: gerçek kapıdan, tur tur (PLAN R7-14, Contracts "followups report").

Bir zincir tek sorunun tekrarı değildir: ikinci tur birincinin cevabına bakar, üçüncü onu daraltır.
O yüzden ölçüm kopya bir döngüyle değil, konuşma deposuyla koşan gerçek ``ask_payload``ın içinden
yapılır. Bir turun doğruluğu runner'ın golden SQL karşısında verdiği karardır (yeniden verilmez);
zincirin doğruluğu tüm turların doğruluğu, bağlamın doğruluğu ise notun baktığı turlar kümesinin
golden ile birebir eşitliğidir. Sayılar ``followup_metrics``te toplanır.
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path

from nl2sql.app.ask import ask_payload
from nl2sql.app.conversations import ConversationStore
from nl2sql.eval import runner

DECIMALS = 4


def load_followups(dataset) -> list[dict]:
    """Kümenin ardışık soru zincirleri; ``Dataset.followups()``ın ölçüm tarafındaki adı."""
    return dataset.followups()


def run_followups(session, chains: Iterable[dict], out_dir: str | Path, mode: str = "full") -> list[dict]:
    """Her zinciri tur tur ``ask_payload``dan geçirir; satır başına bir karar döner (R7-14).

    Konuşma deposu ``out_dir/followups`` altında ve her koşumda sil-baştan kurulur, böylece iki
    koşumun turları birbirinin üstüne binmez. ``mode`` zincirin hangi modda koşacağını söyler
    (hedef: ``full_rules``); dönen satırlar Contracts "followups report"ın ``items``idir.
    """
    folder = Path(out_dir) / "followups"
    shutil.rmtree(folder, ignore_errors=True)
    store = ConversationStore(folder / "conversations.db")
    items = []
    for chain in chains:
        chain_id = str(chain.get("id") or "")
        conversation_id = None
        for n, turn in enumerate(chain.get("turns") or (), start=1):
            payload = ask_payload(
                session, str(turn.get("question") or ""), mode=mode, source="eval",
                conversations=store, conversation_id=conversation_id,
            )
            conversation_id = payload["conversation_id"]
            items.append({
                "id": chain_id,
                "turn": n,
                "outcome": _outcome(session.executor, chain_id, n, turn, payload),
                "context_ok": _context_ok(turn, payload),
            })
    return items


def followup_metrics(items: Iterable[dict]) -> dict:
    """Zincir satırlarının raporu (Contracts "followups report"): tur, zincir ve bağlam doğruluğu.

    Zincir sayısı ``items``daki farklı ``id`` sayısıdır; bir zincir yalnız tüm turları geçmişse
    geçmiş sayılır. Paydası olmayan oran 0.0 (ölçülecek tur yok), ``metrics._rate``ın kuralı.
    """
    rows = list(items)
    turns = len(rows)
    passed = sum(1 for row in rows if row["outcome"] == "pass")
    context = sum(1 for row in rows if row["context_ok"])
    chains: dict[str, list[bool]] = {}
    for row in rows:
        chains.setdefault(row["id"], []).append(row["outcome"] == "pass")
    return {
        "turns": turns,
        "turn_accuracy": _rate(passed, turns),
        "chains": len(chains),
        "chain_accuracy": _rate(sum(1 for ok in chains.values() if all(ok)), len(chains)),
        "context_accuracy": _rate(context, turns),
        "items": rows,
    }


def _outcome(executor, chain_id: str, n: int, turn: dict, payload: dict) -> str:
    """Turun kararı: golden SQL'in sonucuyla runner'ın karşılaştırması - ölçüm kapısı tek yerde."""
    line = {"id": f"{chain_id} t{n}", "question": str(turn.get("question") or ""), "sql": str(turn.get("sql") or "")}
    truth = runner._truth(line, executor)
    outcome, _reason, _sql = runner._verdict(line, str(payload.get("sql") or ""), executor, truth, line["id"])
    return outcome


def _context_ok(turn: dict, payload: dict) -> bool:
    """Bağlam doğruluğu: notun baktığı turlar kümesi golden ile aynı mı (boş küme = tek başına)."""
    note = payload.get("context") or {}
    return set(note.get("uses_turns") or []) == set(turn.get("uses_turns") or [])


def _rate(part: int, whole: int) -> float:
    return round(part / whole, DECIMALS) if whole else 0.0
