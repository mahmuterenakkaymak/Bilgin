"""Giriş, çıkış, "kimim" uçları ve yöneticinin kullanıcı defteri (PLAN R6-3, R6-5).

Gövde sözleşme "me / login 200"dir: ``{username, role}``. Parola ve ham oturum anahtarı yalnız
bu işlevlerin içinde ve çerezde dolaşır - ne bir gövdeye ne bir günlüğe düşürülürler.
``users`` kurulmamış uygulama Run 5'tir: yolların açacağı bir oturum olmadığı için 404.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from nl2sql import config
from nl2sql.auth.store import LoginError, UserError
from nl2sql.web.authz import AUTH_OFF, require


class LoginBody(BaseModel):
    """``POST /api/auth/login`` gövdesi (Contracts "me / login 200")."""

    username: str = ""
    password: str = ""


class UserCreateBody(BaseModel):
    """``POST /api/users`` gövdesi (Contracts "users API"); rolün varsayılanı CLI ile aynı."""

    username: str = ""
    password: str = ""
    role: str = "user"


class UserUpdateBody(BaseModel):
    """``PUT /api/users/{id}`` gövdesi (Contracts "users API"): söylenmeyen alan olduğu gibi kalır."""

    role: str | None = None
    active: bool | None = None
    password: str | None = None


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


def create_users_router() -> APIRouter:
    """Yöneticinin kullanıcı defteri: liste, ek, güncelle (PLAN R6-3, R6-5).

    Üç yol da yönetici ister; deposuz uygulamada kimlik doğrulama kapalıdır. Gövdeler sözleşme
    "User (public)"dır: store hash'i hiç seçmediği için buradan sızacak bir alan da yoktur.
    """
    router = APIRouter(prefix="/api")
    admin = [Depends(require("admin"))]

    @router.get("/users", dependencies=admin)
    def users_list(request: Request) -> dict:
        """Bütün hesaplar, ada göre: yönetici ekranının tablosu buradan okur."""
        return {"users": _store(request).list_users()}

    @router.post("/users", dependencies=admin)
    def users_add(body: UserCreateBody, request: Request) -> dict:
        """Yeni hesap: reddin cümlesi ve durumu store'undur (çakışan ad 409, kısa parola 422)."""
        try:
            user = _store(request).add_user(body.username, body.password, body.role)
        except UserError as exc:
            raise _refused(exc) from None
        return {"user": user}

    @router.put("/users/{id}", dependencies=admin)
    def users_update(id: int, body: UserUpdateBody, request: Request) -> dict:
        """Rol, etkinlik ve parola; son etkin yöneticiyi store'un kendisi korur (409).

        Parola değişimi ve pasifleştirme store'da oturumları da siler, yani kullanıcının çerezi o
        anda geçersizdir: bir sonraki çağrısı 401.
        """
        try:
            user = _store(request).update_user(
                id, role=body.role, active=body.active, password=body.password
            )
        except UserError as exc:
            raise _refused(exc) from None
        return {"user": user}

    return router


def _refused(exc: UserError) -> HTTPException:
    """Kullanıcı işleminin reddi HTTP'ye: durum ve cümle store'un, yol ikisini de değiştirmez."""
    return HTTPException(status_code=exc.status, detail=exc.message)


def _store(request: Request):
    """Uygulamanın kullanıcı deposu; kurulmadıysa kimlik doğrulama kapalıdır (Run 5)."""
    users = request.app.state.users
    if users is None:
        raise HTTPException(status_code=404, detail=AUTH_OFF)
    return users


def _who(user: dict) -> dict:
    """Sözleşme "me / login 200": arayüzün ihtiyaç duyduğu iki alan, fazlası değil."""
    return {"username": user["username"], "role": user["role"]}
