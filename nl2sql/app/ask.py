"""Bir sorunun cevabı: ``ask_payload`` tek kapı (PLAN R5-1, R5-2, Contracts AskPayload).

``ask --json`` da ``POST /api/ask`` da bunu çağırır; ekranın gördüğü anahtarların tamamı burada
kurulur, her durumda aynı kümeyle, böylece hiçbir alan ekranda ``undefined`` olmaz. Cevabın
kendisi SQL ve satırlardır; olgular, grafik ve cümle onların üstüne kurulur (R5-6, R5-7, R5-9),
netleştirme ise cevabın yerini alan sorudur (R5-2, R5-11).

``conversations`` verildiği her çağrı bir konuşmanın turudur (R7-7): soru önceki turlarla koşar,
tur özet olarak konuşmaya yazılır, payload ve günlük satırı tur numarasını taşır. Depo
verilmeyen çağrı Run 6'dır - ne payload ne günlük bir konuşma alanı görür.
"""

from __future__ import annotations

import time

from nl2sql import config
from nl2sql.agent import refine
from nl2sql.agent.clarify import follow_up_text
from nl2sql.agent.context import evidence_line, turn_summary, validate_note
from nl2sql.agent.loop import run_agent
from nl2sql.app import asklog
from nl2sql.app.conversations import ConversationNotFound
from nl2sql.engine import checks
from nl2sql.engine.result import Budget
from nl2sql.index.store import ForeignIndexError, MissingIndexError, StaleIndexError
from nl2sql.report.chart import chart_spec
from nl2sql.report.facts import compute_facts
from nl2sql.report.narrate import narrate
from nl2sql.schema_map.rules import matching_rules

# Adım özeti ekranda okunur; uzun bir araç cevabı payload'ı şişirmesin.
STEP_CHARS = 300

# R7-10: modelsiz sunum değişikliğinin cümlesi türü kullanıcının diliyle söylenir.
_CHART_WORDS = {"line": "çizgi", "bar": "çubuk", "pie": "pasta", "table": "tablo"}

# R5-2: indeksteki bir sorun koşumu düşürmez, cevabın hatası olur.
INDEX_ERRORS = (MissingIndexError, StaleIndexError, ForeignIndexError)


def ask_payload(
    session,
    question: str,
    mode: str | None = None,
    choice=None,
    source: str = "web",
    username: str | None = None,
    conversations=None,
    conversation_id: str | None = None,
) -> dict:
    """Bir soruyu AskPayload'a çeviren tek fonksiyon (R5-1): modu çözer, ajanı koşurur, yürütür.

    ``mode`` verilmezse ``auto``dur ve oturumun ``resolve_mode``u onu düşürdüğü notu ``notes``a
    yazar; ``source`` hem soru günlüğünün hem o koşumun denetim satırlarının başıdır
    (``<web|cli>:<audit_id>``, R5-4). Her çağrı soru günlüğüne tek satır bırakır.

    ``username`` soruyu soran kişinin adıdır (R6-9): günlüğün satırına ve denetim satırlarının
    başına (``<web|cli>:<kullanıcı>:<audit_id>``) karışır; söylenmediğinde her şey Run 5'in halidir.

    İlk soru netleştirme sorabilir (R5-10); ``choice`` verilmişse soru seçilen anlamla koşar ve o
    tur soramaz, yani açıklama döngüsü kurulmaz (R5-11). Günlük soruyu ve seçimi ayrı taşır.

    ``conversations`` verildiyse çağrı bir konuşmanın turudur (R7-7): ``conversation_id``
    söylenmemişse konuşma yeni açılır, söylenmiş ve bulunamamışsa ``ConversationNotFound``dır -
    yolun 404'ü oradan okunur. Soru son ``CONV_TURNS`` turla koşar, tur özetini konuşmaya
    bırakır, payload ve günlük satırı ``conversation_id`` ile ``turn``i taşır; bekleyen bir
    netleştirmenin aynı sorusuna verilen ``choice`` o turu tamamlar, üstüne yeni tur açmaz.
    Yalnızca sunumu değiştiren bir soru (``refine.chart_only``, R7-10) modeli hiç koşurmaz: son
    yanıtlanmış turun SQL'i aynıyla yeniden yürür, cümlesi koddan kurulur. Tekil bir işaretle
    birden çok değerli bir kolona işaret eden soru (``refine.ambiguous_entity``, R7-12) da modeli
    beklemez: şıkları konuşmanın kendi satırlarından kurulur ve bekleyen tur olarak yazılır;
    seçilen şık o turun cevabını tamamlar ve bağlam notunun varlığı olur.
    """
    audit_id = asklog.new_audit_id()
    notes: list[str] = []
    started = time.perf_counter()
    payload = _skeleton(question, choice, mode or "auto", session, audit_id, notes)
    asked = follow_up_text(question, choice) if choice else question
    conversation_id, pending, turns, clarification = _thread(
        conversations, conversation_id, username, question, choice, payload["dataset"]
    )
    if conversation_id is not None:
        # Contracts "AskPayload (ext.)": üç anahtar yalnız konuşmayla koşan payloadda vardır.
        payload.update(conversation_id=conversation_id, turn=None, context=None)
    dropped = None
    wish = refine.chart_only(asked, turns)
    entity = _chosen(clarification, choice)
    ambiguous = None if choice or wish is not None else refine.ambiguous_entity(asked, turns, session.schema)
    try:
        resolved, _ = session.resolve_mode(payload["mode"], notes)
        payload["mode"] = resolved
        if wish is not None:
            # R7-10: soru yalnızca sunumu değiştiriyor - model hiç koşmaz, sayı riski doğmaz.
            _chart_only(session, asked, wish, turns, _audit_source(source, username, audit_id), payload)
        elif ambiguous is not None:
            # R7-12: hangisini kastettiğini yalnız kullanıcı bilir - uydurmayı model değil soru çözer.
            _clarify(payload, ambiguous)
        else:
            dropped = _run(
                session, asked, resolved, _audit_source(source, username, audit_id), payload,
                clarify=not choice, history=turns, entity=entity,
            )
    except INDEX_ERRORS as exc:
        _fail(payload, "index", str(exc))
    if conversation_id is not None:
        payload["turn"] = _store(conversations, payload, conversation_id, pending)
    payload["timings"]["total_s"] = round(time.perf_counter() - started, 3)
    asklog.record_ask(_record(payload, source, username, dropped), session.ask_log)
    return payload


def _thread(conversations, conversation_id, username, question, choice, dataset) -> tuple:
    """Konuşmanın hali: (kimlik, tamamlanacak bekleyen turun numarası, miras alınan turlar, bekleyen şıklar).

    Depo yoksa dördü de None'dır ve koşum Run 6'dır. Sahiplik elle karşılaştırılır: tek
    kullanıcılı modda konuşmanın sahibi NULL, ``get``in ``username`` süzgeci ise ``username = ?``
    demek - NULL hiçbir şeyle eşitleşmediği için o süzgeç tek kullanıcılı modu hiç bulamazdı.
    Bekleyen şıklar R7-12de kurulan netleştirmenin kolonunu da taşır; seçimin hangi varlık olduğunu
    oradan okumak için tur olduğu gibi geri verilir.
    """
    if conversations is None:
        return None, None, None, None
    if conversation_id is None:
        created = conversations.create(username=username, dataset=dataset, title=question)
        return created, None, [], None
    found = conversations.get(conversation_id, dataset=dataset)
    if found is None or found["conversation"]["username"] != username:
        raise ConversationNotFound()
    last = found["turns"][-1] if found["turns"] else None
    waiting = bool(
        choice and last and last["status"] == "needs_clarification" and last["question"] == question
    )
    return (
        conversation_id,
        last["n"] if waiting else None,
        conversations.last_turns(conversation_id, config.CONV_TURNS),
        (last.get("summary") or {}).get("clarification") if waiting else None,
    )


def _chosen(clarification: dict | None, choice) -> dict | None:
    """Seçilen şıkkın varlığı (R7-12): bekleyen netleştirme bir varlık sorusuyduysa kolon ve değer geri okunur.

    Modelin kendi netleştirmesinin (R5-10) kolonu yoktur, o yüzden oradan hiçbir şey çıkmaz.
    Şıkkın biçimi R7-12de sabittir - ``"<değer> (ad)"`` - yani değer ilk " ("e kadardır; yanlış
    okunan bir değer zaten ``validate_note``ın kanıt kapısından geçemez, ekrana kanıt olamaz.
    """
    if not clarification or not clarification.get("column"):
        return None
    if choice not in (clarification.get("options") or []):
        return None
    return {"column": clarification["column"], "value": str(choice).split(" (", 1)[0]}


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


def _run(
    session, question: str, mode: str, source: str, payload: dict, clarify: bool = True,
    history=None, entity: dict | None = None,
) -> str | None:
    """Ajanın koşusu, gönderilen SQL'in arayüz bütçesiyle ikinci yürüyüşü ve cevabın doldurulması.

    ``history`` konuşmanın miras alınan turlarıdır (R7-4); None Run 6'dır. Dönüş değeri düşürülen
    bağlam notunun gerekçesidir (R7-5), not düştüyse günlük satırı onu taşır. ``entity`` kullanıcının
    şıkkıyla seçtiği varlıktır (R7-12): notu modelin değil kodun kurduğu nottur, aynı konudaki
    model notu fazlalık kalır.
    """
    run = run_agent(
        question,
        session.agent_llm(mode),
        session.executor,
        session.schema,
        source,
        mode=mode,
        context=session.context(mode, clarify),
        budget=session.budget,
        history=history,
    )
    payload["steps"] = [
        {"tool": step.tool, "ok": step.ok, "summary": step.summary[:STEP_CHARS]}
        for step in run.steps
    ]
    payload["timings"]["agent_s"] = run.elapsed_s
    if run.status == "needs_clarification":
        _clarify(payload, run.clarification)
        return None
    if run.status != "submitted":
        # Durumun adı hatanın adıdır: modelin hiç göndermemesi de bir cevap hatasıdır (R5-2).
        _fail(payload, run.status, run.stop_reason)
        return None

    note = _entity_note(history, entity) if entity is not None else run.context_note
    dropped = _note(session, payload, note, history)
    _answer(session, question, run.submitted_sql or "", source, payload)
    return dropped


def _entity_note(turns, entity: dict) -> dict:
    """Seçilen varlığın bağlam notu: işaret edilen son yanıtlanmış turun üstüne kurulur (R7-12).

    Not ``validate_note``ın kanıt kapısından da geçer, yani şıkkın değeri o turun satırlarında
    gerçekten duruyorsa ekrana kanıt olur; şık sonradan anlamsızlaştıysa not düşer, cevap durur.
    """
    turn = _refined(turns) if turns else None
    return {
        "uses_turns": [turn["n"]] if turn else [],
        "entities": [entity],
        "refines_sql_of": None,
    }


def _chart_only(session, question: str, wish: str, turns, source: str, payload: dict) -> None:
    """Sunum değişikliğinin cevabı: önceki turun SQL'i aynen yeniden, grafik istenen türde (R7-10).

    Ne ajan ne anlatıcı koşar: cümle koddan kurulur, sayılar yürütücünün döndürdüğü satırlardır.
    Biçim isteği kaldırmıyorsa ``chart_spec``ın eklediği gerekçe konuşur, kendi grafik kalır.
    """
    turn = _refined(turns)
    if not _execute(session, turn["sql"], source, payload):
        return
    payload["facts"] = [fact.to_dict() for fact in compute_facts(payload["columns"], payload["rows"])]
    payload["chart"] = chart_spec(payload["columns"], payload["rows"], question, kind=wish)
    payload["answer_text"] = _chart_text(wish, payload["chart"])
    payload["narration_source"] = "template"
    payload["steps"] = [
        {"tool": "chart", "ok": True,
         "summary": f"Tur {turn['n']} sorgusu yeniden çalıştırıldı, model SQL yazmadı."}
    ]
    note = {"uses_turns": [turn["n"]], "entities": [], "refines_sql_of": turn["n"]}
    payload["context"] = {**note, "line": evidence_line(note, turns, session.schema)}


def _refined(turns) -> dict:
    """Son yanıtlanmış tur: sunumu değiştirilen (R7-10) ya da varlığı seçilen (R7-12) tur."""
    return next(turn for turn in reversed(turns) if turn.get("sql"))


def _chart_text(wish: str, chart) -> str:
    """Koddan kurulan cümle: uyan tür söylenir, uymayanın gerekçesi grafikten olduğu gibi okunur."""
    if chart and chart.get("reason"):
        return chart["reason"]
    if wish == "table":
        return "Sonuç tablo olarak gösteriliyor."
    return f"Grafik {_CHART_WORDS[wish]} olarak gösteriliyor."


def _note(session, payload: dict, note, turns) -> str | None:
    """Modelin bağlam notu: doğrulanırsa kanıt satarıyla payload'a girer, doğrulanmazsa düşer (R7-5).

    ``turns`` None konuşma deposu yok demektir - o zaman ne not ne kanıt satarı vardır. Boş not bir
    başarısızlık değil, kendi başına duran bir sorunun halidir: payload'a hiçbir şey yazılmaz.
    Düşen not cevaba dokunmaz; gerekçesi yalnız günlük satırına düşer.
    """
    if turns is None:
        return None
    valid, reason = validate_note(note, turns)
    if reason:
        return reason
    if not (valid["uses_turns"] or valid["entities"] or valid["refines_sql_of"]):
        return None
    payload["context"] = {**valid, "line": evidence_line(valid, turns, session.schema)}
    return None


def _store(conversations, payload: dict, conversation_id: str, pending: int | None) -> int:
    """Turun konuşmaya yazılışı: sonraki tura miras kalan kadarı özet, numara 1'den başlar (R7-3).

    ``pending`` bekleyen bir netleştirmenin numarasıysa tur onun üstüne yazılır - seçim yeni tur
    açmaz (R7-7); tamamlanacak bir şey kalmamışsa sıradaki tura geçilir.
    """
    turn = {
        "question": payload["question"],
        "choice": payload["choice"],
        "status": payload["status"],
        "sql": payload["sql"] or None,
        "columns": payload["columns"],
        "summary": turn_summary(payload),
        "answer_text": payload["answer_text"],
        "audit_id": payload["audit_id"],
    }
    n = conversations.complete_turn(conversation_id, pending, turn) if pending is not None else None
    return n if n is not None else conversations.add_turn(conversation_id, turn)


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
    if _execute(session, sql, source, payload):
        _report(session, question, payload)


def _execute(session, sql: str, source: str, payload: dict) -> bool:
    """SQL'in arayüz bütçesiyle yürüyüşü ve cevabın satırları: yürümediyse False (R5-2)."""
    payload["sql"] = sql
    # Döngü satırları metin olarak görür; tablo için SQL bir kez daha, arayüz bütçesiyle koşar.
    result = session.executor.execute(sql, Budget(max_rows=config.UI_MAX_ROWS), source)
    payload["timings"]["execute_ms"] = round(result.elapsed_ms, 1)
    if result.error is not None:
        _fail(payload, f"exec:{result.error.kind}", result.error.message)
        return False

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
    return True


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


def _record(
    payload: dict, source: str, username: str | None = None, context_dropped: str | None = None
) -> dict:
    """Soru günlüğünün satırı: sözleşme alanları, satırlar asla (R5-4); adı olmayan satıra girmez (R6-9)."""
    record = {
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
    # Contracts "ask record (ext.)": konuşmayla koşan satır turunu, düşen notu gerekçesini taşır
    # (R7-7); konuşmasız çağrı Run 6'nın satırıyla aynı anahtarlarla döner.
    if payload.get("conversation_id") is not None:
        record["conversation_id"] = payload["conversation_id"]
        record["turn"] = payload["turn"]
    if context_dropped:
        record["context_dropped"] = context_dropped
    return record
