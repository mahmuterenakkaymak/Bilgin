"""Bir sorunun cevabı: ``ask_payload`` tek kapı (PLAN R5-1, R5-2, Contracts AskPayload).

``ask --json`` da ``POST /api/ask`` da bunu çağırır; ekranın gördüğü anahtarların tamamı burada
kurulur, her durumda aynı kümeyle, böylece hiçbir alan ekranda ``undefined`` olmaz. Cevabın
kendisi SQL ve satırlardır; olgular, grafik ve cümle onların üstüne kurulur (R5-6, R5-7, R5-9),
netleştirme ise M16'ya kadar boş kalan alandır.
"""

from __future__ import annotations

import time

from nl2sql import config
from nl2sql.agent.loop import run_agent
from nl2sql.app import asklog
from nl2sql.engine import checks
from nl2sql.engine.result import Budget
from nl2sql.index.store import ForeignIndexError, MissingIndexError, StaleIndexError
from nl2sql.report.chart import chart_spec
from nl2sql.report.facts import compute_facts
from nl2sql.report.narrate import narrate
from nl2sql.schema_map.rules import matching_rules

# Adım özeti ekranda okunur; uzun bir araç cevabı payload'ı şişirmesin.
STEP_CHARS = 300

# R5-2: indeksteki bir sorun koşumu düşürmez, cevabın hatası olur.
INDEX_ERRORS = (MissingIndexError, StaleIndexError, ForeignIndexError)


def ask_payload(session, question: str, mode: str | None = None, choice=None, source: str = "web") -> dict:
    """Bir soruyu AskPayload'a çeviren tek fonksiyon (R5-1): modu çözer, ajanı koşurur, yürütür.

    ``mode`` verilmezse ``auto``dur ve oturumun ``resolve_mode``u onu düşürdüğü notu ``notes``a
    yazar; ``source`` hem soru günlüğünün hem o koşumun denetim satırlarının başıdır
    (``<web|cli>:<audit_id>``, R5-4). Her çağrı soru günlüğüne tek satır bırakır.
    """
    audit_id = asklog.new_audit_id()
    notes: list[str] = []
    started = time.perf_counter()
    payload = _skeleton(question, choice, mode or "auto", session, audit_id, notes)
    try:
        resolved, _ = session.resolve_mode(payload["mode"], notes)
        payload["mode"] = resolved
        _run(session, question, resolved, f"{source}:{audit_id}", payload)
    except INDEX_ERRORS as exc:
        _fail(payload, "index", str(exc))
    payload["timings"]["total_s"] = round(time.perf_counter() - started, 3)
    asklog.record_ask(_record(payload, source), session.ask_log)
    return payload


def _skeleton(question: str, choice, mode: str, session, audit_id: str, notes: list) -> dict:
    """Sözleşmenin her durumda taşıdığı anahtarlar; boşmayan tek yer burası."""
    return {
        "status": "failed",
        "question": question,
        "choice": choice,
        "answer_text": "",
        "narration_source": None,
        "chart": None,
        "facts": [],
        "columns": [],
        "rows": [],
        "row_count": 0,
        "truncated": False,
        "sql": "",
        "tables_used": [],
        "rules_used": [],
        "masked_columns": [],
        "warnings": [],
        "notes": notes,
        "mode": mode,
        "dataset": session.dataset.name if session.dataset else None,
        "model": session.profile.name if session.profile else session.llm_kind,
        "timings": {"agent_s": 0.0, "execute_ms": 0.0, "narrate_s": 0.0, "total_s": 0.0},
        "audit_id": audit_id,
        "clarification": None,
        "error": None,
        "steps": [],
    }


def _run(session, question: str, mode: str, source: str, payload: dict) -> None:
    """Ajanın koşusu, gönderilen SQL'in arayüz bütçesiyle ikinci yürüyüşü ve cevabın doldurulması."""
    run = run_agent(
        question,
        session.agent_llm(mode),
        session.executor,
        session.schema,
        source,
        mode=mode,
        context=session.context(mode),
        budget=session.budget,
    )
    payload["steps"] = [
        {"tool": step.tool, "ok": step.ok, "summary": step.summary[:STEP_CHARS]}
        for step in run.steps
    ]
    payload["timings"]["agent_s"] = run.elapsed_s
    if run.status != "submitted":
        # Durumun adı hatanın adıdır: modelin hiç göndermemesi de bir cevap hatasıdır (R5-2).
        _fail(payload, run.status, run.stop_reason)
        return

    sql = run.submitted_sql or ""
    payload["sql"] = sql
    # Döngü satırları metin olarak görür; tablo için SQL bir kez daha, arayüz bütçesiyle koşar.
    result = session.executor.execute(sql, Budget(max_rows=config.UI_MAX_ROWS), source)
    payload["timings"]["execute_ms"] = round(result.elapsed_ms, 1)
    if result.error is not None:
        _fail(payload, f"exec:{result.error.kind}", result.error.message)
        return

    payload["status"] = "answered"
    payload["columns"] = list(result.columns)
    payload["rows"] = [list(row) for row in result.rows]
    payload["row_count"] = result.row_count
    payload["truncated"] = result.truncated
    payload["tables_used"] = list(result.tables)
    payload["masked_columns"] = list(result.masked_columns)
    payload["rules_used"] = matching_rules(session.rules, sql)
    payload["warnings"] = [
        warning.to_dict() for warning in checks.post_checks(sql, result, session.executor)
    ]
    _report(session, question, payload)


def _report(session, question: str, payload: dict) -> None:
    """Cevabın raporu: olgular ve grafik dönen satırlardan koddan, cümle anlatıcıdan (R5-6, R5-7, R5-9)."""
    payload["facts"] = [
        fact.to_dict() for fact in compute_facts(payload["columns"], payload["rows"])
    ]
    payload["chart"] = chart_spec(payload["columns"], payload["rows"], question)
    started = time.perf_counter()
    narration = narrate(
        question, payload["columns"], payload["rows"], payload["facts"], session.narrator()
    )
    payload["answer_text"] = narration.text
    payload["narration_source"] = narration.source
    payload["timings"]["narrate_s"] = round(time.perf_counter() - started, 3)


def _fail(payload: dict, kind: str, message: str) -> None:
    """Başarısız cevap: hatanın adı ve Türkçe cümlesi, ekranda cevabın yerine okunur."""
    payload["status"] = "failed"
    payload["error"] = {"kind": kind, "message": message}
    payload["answer_text"] = message


def _record(payload: dict, source: str) -> dict:
    """Soru günlüğünün satırı: sözleşme alanları, satırlar asla (R5-4)."""
    return {
        "audit_id": payload["audit_id"],
        "source": source,
        "dataset": payload["dataset"],
        "mode": payload["mode"],
        "question": payload["question"],
        "choice": payload["choice"],
        "status": payload["status"],
        "sql": payload["sql"],
        "row_count": payload["row_count"],
        "error": payload["error"]["kind"] if payload["error"] else None,
    }
