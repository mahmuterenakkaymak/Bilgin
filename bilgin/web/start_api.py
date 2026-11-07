# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Başlangıç ekranı ve hazır sorular API'si (PLAN R7-17, R7-18).

Kart onaylanmış bir hazır sorudur, yani bir daha modele sorulmayan bir cümledir: kullanıcının
yolları onu yalnız *yüküyle* gösterir - sayı, grafik ya da tablo - ve kayıtlı SQL hiçbir yanıtta
geri dönmez. Kartı açmak ``/api/replay``in biçimidir: SQL aynı politika ve salt okunur
yürütücüden bir daha geçer, cümleyi anlatıcı kurar ve tur yeni bir konuşmanın 1. turu olarak
yazılır - kart tıklanınca açılan şey sonraki soruyu da taşıyan sohbettir.

Görünmezlik red değil yokluktur (R6-9): onaysız, başka kümeye ya da başka bir iş rolüne ait bir
satır kullanıcının listesinde hiç yoktur; açması da yenilemesi de 404'tür. Yöneticinin hazır soru
yolları ``ROUTE_ROLES``ta admin'dir ve SQL'i her zaman bir soru kaydından alır - istemci SQL
göndermez, gönderse de okunmaz.

Cevabın biçimi ``app/ask``ın kendi parçalarıdır: payload, yürüyüş, tur ve günlük satırı oradan
okunur, burada yeniden kurulmaz.
"""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from bilgin import config
from bilgin.app import ask, asklog
from bilgin.engine.result import Budget
from bilgin.i18n import t
from bilgin.start.cards import RefreshTooSoon
from bilgin.start.ready import ReadyError, approve_from_audit, personal_from_audit
from bilgin.web.authz import current_user, require
from bilgin.web.lang import request_lang


class PersonalBody(BaseModel):
    """``POST /api/start/cards`` gövdesi (R7-17): ``sql`` yoktur, kişinin kendi kaydından gelir."""

    audit_id: str = ""
    title: str = ""
    display: str | None = None


class ReadyCreateBody(BaseModel):
    """Sözleşme "ready create body": ``question`` söylenmezse kaydın sorusudur, ``display`` yürüyen
    sonucun biçimidir; ``business_role`` ``*`` ise her rol görür, ``None`` kişisel karttır."""

    audit_id: str = ""
    title: str = ""
    question: str | None = None
    display: str | None = None
    business_role: str | None = None
    position: int = 0


class SuggestBody(BaseModel):
    """``POST /api/ready-questions/suggest`` gövdesi (R7-20): küme söylenmezse sunucunun o anki kümesidir."""

    dataset: str = ""


class SessionExecutor:
    """O anki oturumun yürütücüsüne bakan kabuk (R6-10).

    Kart önbelleği uygulamanın üstünde yaşıyor, oturum ise küme geçişinde değişiyor: yürütücünün
    kendisini saklamak kartları geçişten sonra eski kümenin veritabanına bağlardı. Kabuk her
    yürüyüşte oturumu yeniden okur, böylece kart hep sunucunun o an baktığı yerde koşar.
    """

    def __init__(self, app) -> None:
        self._app = app

    def execute(self, sql, budget=None, source: str = ""):
        return self._app.state.session.executor.execute(sql, budget, source)

    @property
    def _pii_schema(self):
        return self._app.state.session.executor._pii_schema


def create_router() -> APIRouter:
    """Kartların beş kullanıcı yolu ve hazır soruların altı yönetici yolu (R7-17, R7-18, R7-20)."""
    router = APIRouter()
    user = [Depends(require("user"))]
    admin = [Depends(require("admin"))]

    # ------------------------------------------------------------------ başlangıç ekranı

    @router.get("/api/start", dependencies=user)
    def start(request: Request) -> dict:
        """Ekranın kartları: görünen onaylı satırların yükleri, ``position`` sırasıyla (R7-18).

        Kartların SQL'i önbellekten gelir ya da bir kez yürür - model hiçbir koşulda koşmaz.
        """
        cards = _store(request).list_for(_dataset(request), _role(request), _name(request))
        cache, lang = request.app.state.start_cache, _lang(request)
        return {
            "cards": [cache.get(card, _source(request), lang) for card in cards],
            "business_role": _role(request),
        }

    @router.post("/api/start/cards/{id}/refresh", dependencies=user)
    def card_refresh(id: int, request: Request) -> dict:
        """Kartı bir daha koşar: TTL'i aşar, ama kart başına ``CARD_REFRESH_MIN_S``te birden fazlası
        429 - kaç saniye sonra yeniden denenacağı cümlede yazar."""
        lang = _lang(request)
        card = _visible_card(request, id, lang)
        try:
            payload = request.app.state.start_cache.refresh(card, _source(request), lang)
        except RefreshTooSoon as exc:
            # Reddin cümlesini kartın kendisi kurar ve diliyle birlikte doğar: yol onu yazmaz.
            raise HTTPException(status_code=429, detail=str(exc)) from None
        return {"card": payload}

    @router.post("/api/start/cards/{id}/open", dependencies=user)
    def card_open(id: int, request: Request) -> dict:
        """Kartı konuşma olarak açar: kayıtlı SQL modelsiz yürür, tur yeni konuşmanın 1. turudur."""
        lang = _lang(request)
        return _open(request, _visible_card(request, id, lang), lang)

    @router.post("/api/start/cards", dependencies=user)
    def card_pin(body: PersonalBody, request: Request) -> dict:
        """Kişisel kart: kişinin kendi cevaplanmış sorusundan, iş rolü olmadan (R7-17).

        Süzgeç arayanın adının kendisidir, yani başkasının kaydı onunki değildir (404); kotanın
        reddi de kartın yürüyüş hatası da ``ReadyError``ın durum ve cümlesidir.
        """
        lang = _lang(request)
        username = _name(request)
        if username is None:
            # ASSUMPTION: kişisel kart bir kimlik ister - users kurulmadıysa kartın sahibi olmaz.
            raise HTTPException(status_code=409, detail=t("auth.off", lang))
        with _rejected(lang):
            card = personal_from_audit(
                _session(request), _store(request), body.audit_id, username,
                {"title": body.title, "display": body.display},
            )
        return {"card": request.app.state.start_cache.get(card, _source(request), lang)}

    @router.delete("/api/start/cards/{id}", dependencies=user)
    def card_unpin(id: int, request: Request) -> dict:
        """Kişisel kartı panodan çıkarır; rol kartı kişinin değildir, başkasınınki de yoktur (404)."""
        lang = _lang(request)
        if _visible_card(request, id, lang)["business_role"] is not None:
            raise HTTPException(status_code=404, detail=t("start.not_found", lang))
        with _rejected(lang):
            _store(request).delete(id, username=_name(request))
        return {"deleted": id}

    # ------------------------------------------------------------------- yönetici yolu

    @router.get("/api/ready-questions", dependencies=admin)
    def ready_list(request: Request, dataset: str | None = None, pending: bool | None = None) -> dict:
        """Kümenin bütün satırları (R7-17): ``pending`` true onay bekleyenler, false onaylılar."""
        name = dataset or _dataset(request)
        return {"ready_questions": _store(request).list_all(name, pending=pending)}

    @router.post("/api/ready-questions", dependencies=admin)
    def ready_add(body: ReadyCreateBody, request: Request) -> dict:
        """Onay: SQL soru kaydından gelir ve yürütülür - yürümezse 422, satır yazılmaz (R7-17)."""
        with _rejected(_lang(request)):
            card = approve_from_audit(
                _session(request), _store(request), body.audit_id, _name(request), asklog._ALL,
                {
                    "title": body.title,
                    "question": body.question,
                    "display": body.display,
                    "business_role": body.business_role,
                    "position": body.position,
                },
            )
        return {"ready_question": card}

    @router.put("/api/ready-questions/{id}", dependencies=admin)
    def ready_update(id: int, body: dict, request: Request) -> dict:
        """Sözleşmenin alanlarını değiştirir; ``audit_id`` "SQL'i yeniden onayla"dır (R7-17).

        Gövde ``ReadyStore``un bildiği alanlardan oluşur - ``sql`` bunların arasında değildir,
        yani istemcinin gönderdiği SQL 422dir, yeni bir onayın kaydı ise yürütülüp yazılır.
        """
        lang = _lang(request)
        fields = dict(body)
        audit_id = fields.pop("audit_id", None)
        with _rejected(lang):
            if audit_id:
                fields["sql"] = _reapproved_sql(request, audit_id, lang)
                fields["audit_id"] = audit_id
            card = _store(request).update(id, **fields)
        return {"ready_question": card}

    @router.delete("/api/ready-questions/{id}", dependencies=admin)
    def ready_delete(id: int, request: Request) -> dict:
        """Satırı siler; olmayan kimlik 404 (R7-17)."""
        with _rejected(_lang(request)):
            _store(request).delete(id)
        return {"deleted": id}

    @router.post("/api/ready-questions/suggest", dependencies=admin)
    def ready_suggest(body: SuggestBody, request: Request) -> dict:
        """Öneri işini başlatır ve iş kaydını döndürür (R7-20): koşumlar iş parçacığındadır.

        Yalnız cevaplanan sorular satır olur, hepsi onaysızdır - yani hiçbirinin kartı ekranlarda
        görünmez, ta ki bir yönetici onu onaylayana kadar.
        """
        return request.app.state.suggest.start(
            body.dataset.strip() or _dataset(request), _name(request), _lang(request)
        )

    @router.get("/api/ready-questions/suggest/{job_id}", dependencies=admin)
    def ready_suggest_status(job_id: str, request: Request) -> dict:
        """Sözleşme "suggest job": hiç başlamamış bir işin aşaması yoktur, o yüzden 404."""
        job = request.app.state.suggest.status(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail=t("start.no_job", _lang(request)))
        return job

    return router


# ------------------------------------------------------------------------------- internals


def _lang(request: Request) -> str:
    """Yolun arayüz dili: kişinin tercihi, yoksa tarayıcının başlığı, o da yoksa programın dili (R8-5)."""
    return request_lang(request, current_user(request))


@contextlib.contextmanager
def _rejected(lang: str):
    """Deponun reddi HTTPye: durumu yol olduğu gibi taşır, cümleyi isteğin dilinden kurar (R8-5).

    Kataloğu olmayan red - yürütücünün kendi cümlesi - anahtarsız doğar; onun cümlesi zaten dildir.
    """
    try:
        yield
    except ReadyError as exc:
        detail = t(exc.key, lang, **exc.params) if exc.key else exc.message
        raise HTTPException(status_code=exc.status, detail=detail) from None


def _open(request: Request, card: dict, lang: str) -> dict:
    """Kartın konuşması: ``replay_payload``ın biçimi, kaynağı kartın kendi SQL'i (R7-18).

    Ajan hiç koşmaz; anlatıcının çağrısı sayı bekçisinden aynı şekilde geçer. Tur konuşmaya
    yazıldıktan sonra günlük satırı da turu taşır, yani geçmişin satırı karttan açılan cevabı
    konuşmanın 1. turu olarak gösterir.

    Cevabın dili sorudan çözülür, soru bir dil söylemiyorsa isteğin dili düşer (R8-6); not ve adım
    cevabın diliyle kurulur - ``replay_payload``ın yaptığı gibi.
    """
    session = _session(request)
    username = _name(request)
    audit_id = asklog.new_audit_id()
    answer_lang = ask.payload_lang(card["question"], lang)
    payload = ask._skeleton(
        card["question"], None, "auto", session, audit_id, [t("start.open_note", answer_lang)],
        answer_lang,
    )
    payload["steps"] = [
        {"tool": "replay", "ok": True, "summary": t("start.open_step", answer_lang, id=card["id"])}
    ]
    ask._answer(session, card["question"], card["sql"], ask._audit_source("web", username, audit_id), payload)
    conversations = request.app.state.conversations
    conversation_id = conversations.create(
        username=username, dataset=payload["dataset"], title=card["question"]
    )
    payload.update(conversation_id=conversation_id, turn=None, context=None)
    payload["turn"] = ask._store(conversations, payload, conversation_id, None)
    asklog.record_ask(ask._record(payload, "web", username), session.ask_log)
    return payload


def _reapproved_sql(request: Request, audit_id: str, lang: str) -> str:
    """Yeni onayın SQLi: yürütülür, hatası 422, yürüyen cümle satıra yazılır (R7-17)."""
    session = _session(request)
    record = asklog.find_ask(audit_id, session.ask_log, username=asklog._ALL)
    if record is None or not record.get("sql"):
        raise HTTPException(status_code=404, detail=t("start.no_ask", lang))
    result = session.executor.execute(
        record["sql"], Budget(max_rows=config.UI_MAX_ROWS), f"ready:{audit_id}"
    )
    if result.error is not None:
        raise HTTPException(status_code=422, detail=result.error.message)
    return record["sql"]


def _visible_card(request: Request, id: int, lang: str) -> dict:
    """Kullanıcının kartı: onaylı, bu kümenin ve onun gördüğü satır - ötekiler onun için yoktur."""
    for card in _store(request).list_for(_dataset(request), _role(request), _name(request)):
        if card["id"] == id:
            return card
    raise HTTPException(status_code=404, detail=t("start.not_found", lang))


def _session(request: Request):
    return request.app.state.session


def _store(request: Request):
    return request.app.state.ready


def _dataset(request: Request) -> str:
    ds = _session(request).dataset
    return ds.name if ds else config.DEFAULT_DATASET


def _name(request: Request) -> str | None:
    """Kartın sahibi: kapının çözdüğü kullanıcı; tek kullanıcılı modda ad yoktur (R6-9)."""
    user = current_user(request)
    return user["username"] if user else None


def _role(request: Request) -> str:
    """Kartların süzgeci olan iş rolü; kimlik yoksa varsayılan rolün kartları ve ``*`` kalır."""
    user = current_user(request)
    return user["business_role"] if user else config.DEFAULT_BUSINESS_ROLE


def _source(request: Request) -> str:
    """Denetim satırının başı: kartı kimin yüklediği (Contracts "audit source (ext.)")."""
    name = _name(request)
    return f"start:{name}" if name else "start"
