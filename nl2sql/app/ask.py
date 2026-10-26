"""Bir sorunun cevabı: ``ask_payload`` tek kapı (PLAN R5-1, R5-2, Contracts AskPayload).

``ask --json`` da ``POST /api/ask`` da bunu çağırır; ekranın gördüğü anahtarların tamamı burada
kurulur, her durumda aynı kümeyle, böylece hiçbir alan ekranda ``undefined`` olmaz. Cevabın
kendisi SQL ve satırlardır; olgular, grafik ve cümle onların üstüne kurulur (R5-6, R5-7, R5-9),
netleştirme ise cevabın yerini alan sorudur (R5-2, R5-11).
"""

from __future__ import annotations

import time

from nl2sql import config
from nl2sql.agent.clarify import follow_up_text
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


def ask_payload(
    session, question: str, mode: str | None = None, choice=None, source: str = "web", username: str | None = None
) -> dict:
    """Bir soruyu AskPayload'a çeviren tek fonksiyon (R5-1): modu çözer, ajanı koşurur, yürütür.

    ``mode`` verilmezse ``auto``dur ve oturumun ``resolve_mode``u onu düşürdüğü notu ``notes``a
    yazar; ``source`` hem soru günlüğünün hem o koşumun denetim satırlarının başıdır
    (``<web|cli>:<audit_id>``, R5-4). Her çağrı soru günlüğüne tek satır bırakır.

    ``username`` soruyu soran kişinin adıdır (R6-9): günlüğün satırına ve denetim satırlarının
    başına (``<web|cli>:<kullanıcı>:<audit_id>``) karışır; söylenmediğinde her şey Run 5'in halidir.

    İlk soru netleştirme sorabilir (R5-10); ``choice`` verilmişse soru seçilen anlamla koşar ve o
    tur soramaz, yani açıklama döngüsü kurulmaz (R5-11). Günlük soruyu ve seçimi ayrı taşır.
    """
    audit_id = asklog.new_audit_id()
    notes: list[str] = []
    started = time.perf_counter()
    payload = _skeleton(question, choice, mode or "auto", session, audit_id, notes)
    asked = follow_up_text(question, choice) if choice else question
    try:
        resolved, _ = session.resolve_mode(payload["mode"], notes)
        payload["mode"] = resolved
        _run(session, asked, resolved, _audit_source(source, username, audit_id), payload, clarify=not choice)
    except INDEX_ERRORS as exc:
        _fail(payload, "index", str(exc))
    payload["timings"]["total_s"] = round(time.perf_counter() - started, 3)
    asklog.record_ask(_record(payload, source, username), session.ask_log)
    return payload


def _audit_source(source: str, username: str | None, audit_id: str) -> str:
    """Denetim satırının başı: kullanıcısı olan koşum adı da taşır (R6-9, Contracts "audit source (ext.)")."""
    return f"{source}:{username}:{audit_id}" if username else f"{source}:{audit_id}"


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


def _run(session, question: str, mode: str, source: str, payload: dict, clarify: bool = True) -> None:
    """Ajanın koşusu, gönderilen SQL'in arayüz bütçesiyle ikinci yürüyüşü ve cevabın doldurulması."""
    run = run_agent(
        question,
        session.agent_llm(mode),
        session.executor,
        session.schema,
        source,
        mode=mode,
        context=session.context(mode, clarify),
        budget=session.budget,
    )
    payload["steps"] = [
        {"tool": step.tool, "ok": step.ok, "summary": step.summary[:STEP_CHARS]}
        for step in run.steps
    ]
    payload["timings"]["agent_s"] = run.elapsed_s
    if run.status == "needs_clarification":
        _clarify(payload, run.clarification)
        return
    if run.status != "submitted":
        # Durumun adı hatanın adıdır: modelin hiç göndermemesi de bir cevap hatasıdır (R5-2).
        _fail(payload, run.status, run.stop_reason)
        return

    _answer(session, question, run.submitted_sql or "", source, payload)


def replay_payload(
    session, audit_id: str, source: str = "web", username: str | None = None, scope=None
) -> dict:
    """Geçmişteki bir soruyu modelsiz açar (2026-10-25, Eren: "her soruyu baştan sorup cevap oluşturuyor").

    Soru günlüğünde kayıtlı SQL aynı politika ve salt-okunur yürütücüden yeniden geçer; tablo, grafik ve
    olgular güncel veriden gelir, cümleyi yine anlatıcı kurar (tek kısa çağrı, sayı bekçisiyle). Cevabı
    olmayan bir kayıt (hata, netleştirme) ya da başka kümenin kaydı yeniden sorulmaz: o zaman soru
    baştan sorulur, kümesi tutmuyorsa hata döner.

    ``username`` soruyu yeniden soran kişinin adıdır: yeni satır ve denetim satırları onu taşır.
    ``scope`` arayanın hangi kayıtları gördüğünün süzgecidir (``asklog._ALL`` herkese açıktır);
    söylenmediğinde adın kendisidir, yani tek başına ``username`` hem arar hem yazar (R6-9).
    """
    # ASSUMPTION: süzgeç söylenmediğinde adın kendisi süzgeç olur; adı olmayan bir çağrı ise
    # "kullanıcısız kaydı ara" demez, aramayı _ALL ile yapar (R6-9).
    who = username if scope is None else scope
    record = asklog.find_ask(audit_id, session.ask_log, username=asklog._ALL if who is None else who)
    if record is None or not record.get("question"):
        payload = _skeleton("", None, "auto", session, asklog.new_audit_id(), [])
        _fail(payload, "not_found", "Bu soru geçmişte bulunamadı.")
        return payload
    if (record.get("dataset") or None) != (session.dataset.name if session.dataset else None):
        payload = _skeleton(record["question"], None, "auto", session, asklog.new_audit_id(), [])
        _fail(payload, "dataset", "Bu soru başka bir veri kümesinde sorulmuş; o kümeyle açın.")
        return payload
    if record.get("status") != "answered" or not record.get("sql"):
        return ask_payload(session, record["question"], choice=record.get("choice"), source=source,
                           username=username)

    new_id = asklog.new_audit_id()
    started = time.perf_counter()
    payload = _skeleton(record["question"], record.get("choice"), record.get("mode") or "auto", session, new_id,
                        ["Geçmişten açıldı: kayıtlı SQL yeniden çalıştırıldı, model SQL yazmadı."])
    payload["steps"] = [{"tool": "replay", "ok": True, "summary": f"Geçmişteki soru ({audit_id}) yeniden çalıştırıldı."}]
    _answer(session, record["question"], record["sql"], _audit_source(source, username, new_id), payload)
    payload["timings"]["total_s"] = round(time.perf_counter() - started, 3)
    asklog.record_ask(_record(payload, source, username), session.ask_log)
    return payload


def _answer(session, question: str, sql: str, source: str, payload: dict) -> None:
    """Gönderilen SQL'in arayüz bütçesiyle yürüyüşü ve cevabın doldurulması (ajan da geçmiş de buradan)."""
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


def _clarify(payload: dict, clarification: dict) -> None:
    """Netleştirme: soru ve şıkları cevabın yerini alır (R5-2) — koşulmamış bir SQL yoktur."""
    payload["status"] = "needs_clarification"
    payload["clarification"] = clarification


def _fail(payload: dict, kind: str, message: str) -> None:
    """Başarısız cevap: hatanın adı ve Türkçe cümlesi, ekranda cevabın yerine okunur."""
    payload["status"] = "failed"
    payload["error"] = {"kind": kind, "message": message}
    payload["answer_text"] = message


def _record(payload: dict, source: str, username: str | None = None) -> dict:
    """Soru günlüğünün satırı: sözleşme alanları, satırlar asla (R5-4); adı olmayan satıra girmez (R6-9)."""
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
        "username": username,
    }
