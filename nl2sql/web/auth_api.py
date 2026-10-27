"""Giriş, çıkış, "kimim" uçları ve yöneticinin kullanıcı defteri (PLAN R6-3, R6-5).

Gövde sözleşme "me / login 200"dir: ``{username, role, business_role}``. Parola ve ham oturum
anahtarı yalnız bu işlevlerin içinde ve çerezde dolaşır - ne bir gövdeye ne bir günlüğe
düşürülürler. ``users`` kurulmamış uygulama Run 5'tir: yolların açacağı bir oturum olmadığı için 404.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from nl2sql import config
from nl2sql.auth.store import LoginError, UserError
from nl2sql.web.authz import AUTH_OFF, require

# R7-16: iş rolü başlangıç ekranını belirler, o yüzden kimseye kendi üstünde bırakılmaz.
OWN_BUSINESS_ROLE = "Kendi iş rolünüzü değiştiremezsiniz."


class LoginBody(BaseModel):
    """``POST /api/auth/login`` gövdesi (Contracts "me / login 200")."""

    username: str = ""
    password: str = ""


class MeLangBody(BaseModel):
    """``PUT /api/auth/me`` gövdesi (Contracts "me PUT"): kişinin kendi arayüz dili."""

    lang: str = ""


class UserCreateBody(BaseModel):
    """``POST /api/users`` gövdesi (Contracts "users API"); rolün varsayılanı CLI ile aynı."""

    username: str = ""
    password: str = ""
    role: str = "user"
    business_role: str = config.DEFAULT_BUSINESS_ROLE


class UserUpdateBody(BaseModel):
    """``PUT /api/users/{id}`` gövdesi (Contracts "users API"): söylenmeyen alan olduğu gibi kalır."""

    role: str | None = None
    active: bool | None = None
    password: str | None = None
    business_role: str | None = None


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

    @router.put("/me")
    def me_update(
        body: MeLangBody, request: Request, user: dict | None = Depends(require("user"))
    ) -> dict:
        """Kendi dil tercihini yazar (R8-5): herkes kendi üstünde, reddi 422, cevabı "me" gövdesi.

        Oturum düşmez - tercih bir kimlik bilgisi değil, sunumun ayarıdır. Dil ``LANGUAGES``
        dışındaysa store reddeder; hiçbir şey yazılmaz, ekran da eski tercihini okumaya devam eder.
        """
        try:
            updated = _store(request).set_lang(user["id"], body.lang)
        except UserError as exc:
            raise _refused(exc) from None
        return _who(updated)

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
            user = _store(request).add_user(
                body.username, body.password, body.role, business_role=body.business_role
            )
        except UserError as exc:
            raise _refused(exc) from None
        return {"user": user}

    @router.put("/users/{id}", dependencies=admin)
    def users_update(
        id: int,
        body: UserUpdateBody,
        request: Request,
        current: dict | None = Depends(require("admin")),
    ) -> dict:
        """Rol, etkinlik, parola ve iş rolü; son etkin yöneticiyi store'un kendisi korur (409).

        Parola değişimi ve pasifleştirme store'da oturumları da siler, yani kullanıcının çerezi o
        anda geçersizdir: bir sonraki çağrısı 401. İş rolü kendi üstüne değişilemez (R7-16) -
        reddedilen istek hiç işlenmez, yani aynı gövdedeki öteki alanlar da uygulanmaz.
        """
        if body.business_role is not None and current and id == current["id"]:
            raise HTTPException(status_code=403, detail=OWN_BUSINESS_ROLE)
        try:
            user = _store(request).update_user(
                id,
                role=body.role,
                active=body.active,
                password=body.password,
                business_role=body.business_role,
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
    """Sözleşme "me / login 200": arayüzün ihtiyaç duyduğu alanlar, fazlası değil (R7-16, R8-5).

    ``lang`` kişinin kendi arayüz tercihidir ve yalnız bir tercih yaptıysa gövdededir; tercihsiz
    kişi ``request_lang``a düşer (başlık ya da program dili), yani ekranda eksik alan olmaz.
    """
    who = {
        "username": user["username"],
        "role": user["role"],
        "business_role": user["business_role"],
    }
    # ASSUMPTION: Run 6/7 gövdelerini birebir ölçen testler var, o yüzden tercih NULL olan kişiye
    # ``lang`` hiç yazılmaz - "tercihim yok" ile "tercihim tr" arayüz için aynı anlama gelir.
    if user.get("lang"):
        who["lang"] = user["lang"]
    return who
