"""Konuşmalar API'si: liste, tek konuşma, silme (PLAN R7-8).

Üç yol da oturum ister (R6-5) ve yalnız oturum sahibinin konuşmalarını görür: başkasının
konuşması bu kapıdan hiç yoktur, yani yanıt 403 değil 404'tür - ``ask``ın
``ConversationNotFound``ı ile birebir aynı cümle. Konuşmayı açmak yalnız depoda yazılı olanı
okur: hiçbir SQL koşmaz, yürütücünün denetim günlüğü büyümez.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from nl2sql import config
from nl2sql.app.conversations import ALL as CONVERSATIONS_ALL
from nl2sql.web.authz import current_user, require

# Sözleşme cümlesi: olmayanla başkasınınki aynı şeyi söyler (ConversationNotFound'un kendi cümlesi).
NO_CONVERSATION = "Konuşma bulunamadı."


def create_router() -> APIRouter:
    """Konuşmaların üç yolu: liste, turlarıyla tek konuşma, silme (R7-8)."""
    router = APIRouter()
    user = [Depends(require("user"))]

    @router.get("/api/conversations", dependencies=user)
    def conversations_list(request: Request) -> dict:
        """Kendi konuşmalarım, en son güncellenen önce, her biri tur sayısıyla (Contracts)."""
        store = request.app.state.conversations
        return {"conversations": store.list(username=_owner(request), dataset=_dataset(request))}

    @router.get("/api/conversations/{id}", dependencies=user)
    def conversation_get(id: str, request: Request) -> dict:
        """Konuşmanın kayıtlı turları (Contracts "StoredTurn"): okunan hiçbir şey SQL koşmaz."""
        thread = request.app.state.conversations.get(id, username=_owner(request))
        if thread is None:
            raise HTTPException(status_code=404, detail=NO_CONVERSATION)
        return thread

    @router.delete("/api/conversations/{id}", dependencies=user)
    def conversation_delete(id: str, request: Request) -> dict:
        """Konuşmayı ve turlarını siler; olmayan ya da başkasınınkinde silinecek bir şey yok (404)."""
        if not request.app.state.conversations.delete(id, username=_owner(request)):
            raise HTTPException(status_code=404, detail=NO_CONVERSATION)
        return {"deleted": True}

    return router


def _owner(request: Request):
    """Konuşmaların süzgeci: oturumdaki kullanıcının adı.

    Tek kullanıcılı modda (``users`` yok) ad yoktur ve konuşmanın sahibi NULLdur; ``username = ?``
    NULL'ı hiçbir şeyle eşitlemediği için süzgeç o modda kapatılır - ``ask``ın sahibi elle
    karşılaştırması da aynı gerçeğin öbür yüzüydü (R7-7).
    """
    user = current_user(request)
    return CONVERSATIONS_ALL if user is None else user["username"]


def _dataset(request: Request) -> str:
    """Listenin kümesi: oturumun o anki kümesinin adı - bir geçiş listeyle birlikte değişir."""
    ds = request.app.state.session.dataset
    return ds.name if ds else config.DEFAULT_DATASET
