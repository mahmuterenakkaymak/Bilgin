"""Giriş, çıkış ve "kimim" uçları (PLAN R6-5).

Gövde sözleşme "me / login 200"dir: ``{username, role}``. Parola ve ham oturum anahtarı yalnız
bu işlevlerin içinde ve çerezde dolaşır - ne bir gövdeye ne bir günlüğe düşürülürler.
``users`` kurulmamış uygulama Run 5'tir: yolların açacağı bir oturum olmadığı için 404.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from nl2sql import config
from nl2sql.auth.store import LoginError
from nl2sql.web.authz import AUTH_OFF, require


class LoginBody(BaseModel):
    """``POST /api/auth/login`` gövdesi (Contracts "me / login 200")."""

    username: str = ""
    password: str = ""


def create_router() -> APIRouter:
    """Kimlik doğrulama yolları; deposuz uygulamada hepsi 404 "Kimlik doğrulama kapalı."."""
    router = APIRouter(prefix="/api/auth")

    @router.post("/login")
    def login(body: LoginBody, request: Request, response: Response) -> dict:
        """Oturumu açar: anahtar yalnız çerezle gider, gövde kullanıcının adı ve rolüdür."""
        users = _store(request)
        try:
            user = users.authenticate(body.username, body.password)
        except LoginError as exc:
            # Reddin cümlesi ve durumu store'un: bilinmeyen ad ile yanlış parola aynı satır.
            raise HTTPException(status_code=exc.status, detail=exc.message) from None
        response.set_cookie(
            config.SESSION_COOKIE,
            users.create_session(user),
            max_age=config.SESSION_HOURS * 3600,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return _who(user)

    @router.post("/logout")
    def logout(request: Request, response: Response) -> dict:
        """Oturumu ve çerezi siler; oturum olmadan da 200 - çıkış zaten istenen hâldir."""
        users = _store(request)
        users.delete_session(request.cookies.get(config.SESSION_COOKIE, ""))
        response.delete_cookie(config.SESSION_COOKIE, path="/")
        return {"ok": True}

    @router.get("/me")
    def me(request: Request, user: dict | None = Depends(require("user"))) -> dict:
        """Arayüzün ilk çağrısı: oturum varsa kim olduğu, yoksa 401 (R6-5)."""
        _store(request)
        return _who(user)

    return router


def _store(request: Request):
    """Uygulamanın kullanıcı deposu; kurulmadıysa kimlik doğrulama kapalıdır (Run 5)."""
    users = request.app.state.users
    if users is None:
        raise HTTPException(status_code=404, detail=AUTH_OFF)
    return users


def _who(user: dict) -> dict:
    """Sözleşme "me / login 200": arayüzün ihtiyaç duyduğu iki alan, fazlası değil."""
    return {"username": user["username"], "role": user["role"]}
