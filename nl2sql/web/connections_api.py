"""Veritabanı bağlantıları API'si: ekrandan doldurulan, sırrı çıkmayan yollar (PLAN R7-22..R7-24).

Dördü de yönetici ister (R6-5): bir sunucunun kapısını yazmak, o kümenin hangi veritabanına
baktığını yazmaktır. Sır bu API'den yalnız içeri girer - ``PUT`` parolayı ``ConnectionStore``a
DPAPI blobu olarak bırakır, hiçbir cevap ne parolayı ne bağlantı dizesini taşır (brief §4).

Kaydetmeden önce sunucuya kendisi sorar: ``guard.readonly_guard`` yazabilen bir girişi reddeder
ve o zaman hiçbir satır yazılmaz; ``POST .../test`` aynı raporu yalnız gösterir, hiçbir şey
kaydetmez. Testin canlı SQL Server yerine koyabildiği iki yer ``app.state``tedir: ``conn_connect``
(bağdaç) ve ``dbstatus`` (kendi ``ping``iyle birlikte); ikisi de yoksa gerçek olanı kullanılır.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from nl2sql import datasets
from nl2sql.app.session import SessionError, open_session
from nl2sql.engine import connections, dpapi, guard
from nl2sql.engine.connections import ConnError
from nl2sql.schema_map import doc
from nl2sql.web.authz import current_user, require

# Red cümleleri (PLAN R7-22, R7-23): ekranın gösterdikleri, sözleşmenin kendileri.
ENV_SOURCE = "Bu bağlantı ortam değişkeninden geliyor; ekrandan değiştirilemez."
DPAPI_OFF = "Bu sunucuda parola saklanamaz; ortam değişkenini kullanın."
GUARD_REFUSED = "Bu giriş salt okunur değil; bağlantı kaydedilmedi."
NOT_MSSQL = "Bu veri kümesi SQL Server'a bağlı değil; girilecek bir bağlantısı yok."
# R7-24: reddin gösterdiği yer kümenin kendi üretilmiş salt okunur giriş betiğidir (R6-18 yolu).
LOGIN_SCRIPT_URL = "/api/datasets/{name}/login-script.sql"

# Ortam değişkeni kazanmışsa form okunur; ekrandan yazılacak bir şey yoktur (R7-23).
ENV_SOURCES = ("env_dataset", "env")
# Yoklanacak adayın alanları: gövdede olmayan, kayıtlı satırdan gelir (boş parola "koru"dur).
FIELDS = ("server", "database", "auth", "username", "options")


def create_router() -> APIRouter:
    """Bağlantıların dört yönetici yolu; depo ve oturum ``app.state`` üzerinden okunur."""
    router = APIRouter()
    admin = [Depends(require("admin"))]

    @router.get("/api/connections", dependencies=admin)
    def connections_list(request: Request) -> dict:
        """Bir satır SQL Server kümesi başına (R7-27): durum noktası da satırın içinde."""
        active = _active_name(request)
        return {
            "connections": [
                _row(request, item["name"], active)
                for item in datasets.all_datasets()
                if item["connection"] == "mssql"
            ]
        }

    @router.get("/api/connections/{dataset}", dependencies=admin)
    def connection_get(dataset: str, request: Request) -> dict:
        """Formun açılacağı satır: Contracts "connection (public)"."""
        ds = _mssql_dataset(dataset)
        return _row(request, ds.name, _active_name(request))

    @router.put("/api/connections/{dataset}", dependencies=admin)
    def connection_put(dataset: str, request: Request, body: dict | None = None) -> dict:
        """Yokla, sonra kaydet: yazabilen bir giriş 409 döner ve hiçbir satır yazılmaz (R7-24).

        Etkin kümenin oturumu yeniden kurulur - bağlantıyı yürütücü taşıyor, yani tek atama
        (R6-10) - ve durum yoklaması bekletilmez: nokta bir sonraki turda yeniden sorulur.
        """
        ds = _mssql_dataset(dataset)
        active = _active_name(request)
        data = body or {}
        # Boş bir sunucuya bağlanmayı denemenin anlamı yok; cümleler de deponun kendi cümleleri.
        if not str(data.get("server") or "").strip():
            raise HTTPException(status_code=422, detail=connections.NO_SERVER_MESSAGE)
        if not str(data.get("database") or "").strip():
            raise HTTPException(status_code=422, detail=connections.NO_DATABASE_MESSAGE)
        _refuse_env(request, ds.name, active)
        if str(data.get("password") or "") and not dpapi.available():
            raise HTTPException(status_code=409, detail=DPAPI_OFF)
        report = _report(request, ds, data)
        if not report["ok"]:
            return JSONResponse(status_code=409, content={"detail": GUARD_REFUSED, "guard": report})
        store = request.app.state.connections
        try:
            store.save(ds.name, data, str(data.get("password") or ""), _saver(request))
        except ConnError as exc:
            raise HTTPException(status_code=exc.status, detail=exc.message) from None
        if ds.name == active:
            # ASSUMPTION: satır bu anda kayıtlıdır; oturum kurulamazsa reddeden oturumdur - ekran
            # bağlantıyı bir sonraki küme geçişinde ya da sunucu yeniden başladığında alır.
            _rebuild(request, ds.name)
        status = getattr(request.app.state, "dbstatus", None)
        if status is not None:
            status.kick()
        return {"connection": _row(request, ds.name, active), "guard": report}

    @router.post("/api/connections/{dataset}/test", dependencies=admin)
    def connection_test(dataset: str, request: Request, body: dict | None = None) -> dict:
        """Contracts "guard report": denemenin cevabı yalnız raporun kendisidir (R7-24).

        Gövde formun o anki değerleridir; boş alanlar kayıtlı satırdan gelir, yani kaydedilmiş
        bir bağlantı da olduğu gibi sınanabilir. Hiçbir şey kaydedilmez, hiçbir oturum değişmez.
        """
        ds = _mssql_dataset(dataset)
        return _report(request, ds, body or {})

    return router


def _row(request: Request, name: str, active: str | None) -> dict:
    """Depodaki satıra eklenen iki alan: bağlantının kaynağı ve formun okunup okunamadığı."""
    store = request.app.state.connections
    row = store.public(name)
    row["source"] = connections.resolve(name, store, active)["source"]
    row["read_only_form"] = row["source"] in ENV_SOURCES
    status = getattr(request.app.state, "dbstatus", None)
    if status is not None:
        # Durum noktası arka plan yoklamasının cevabıdır; istek hiçbir zaman bekler (R7-25).
        row["state"] = status.state(name)["state"]
    return row


def _report(request: Request, ds: datasets.Dataset, body: dict) -> dict:
    """Aday değerlerin yoklaması: gövde ne kadar dolduysa onunla, kalanı kayıtlı satırla."""
    store = request.app.state.connections
    saved = store.public(ds.name)
    row = {key: body.get(key, saved[key]) for key in FIELDS}
    password = str(body.get("password") or "")
    if not password and row["auth"] == "sql":
        password = store.secret(ds.name) or ""
    try:
        conn_str = connections.build_conn_str(row, password)
    except ConnError as exc:
        # Alanın kendisi bozuk: sunucuya sorulacak bir şey yok, cümle de deponun cümlesi (R7-22).
        raise HTTPException(status_code=exc.status, detail=exc.message) from None
    return guard.readonly_guard(
        conn_str,
        _tables(ds),
        connect=getattr(request.app.state, "conn_connect", None),
        login_script_url=LOGIN_SCRIPT_URL.format(name=ds.name),
    )


def _mssql_dataset(name: str) -> datasets.Dataset:
    """Kümenin kendisi: tanınmayan ad 404, SQL Server olmayan küme 409 (listede de olmaz)."""
    try:
        ds = datasets.load_dataset(name)
    except datasets.DatasetError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None
    if ds.connection != "mssql":
        raise HTTPException(status_code=409, detail=NOT_MSSQL)
    return ds


def _refuse_env(request: Request, name: str, active: str | None) -> None:
    """Ortam değişkeninin kazandığı bir satıra ekrandan yazılmaz (R7-23)."""
    where = connections.resolve(name, request.app.state.connections, active)
    if where["source"] in ENV_SOURCES:
        raise HTTPException(status_code=409, detail=ENV_SOURCE)


def _rebuild(request: Request, name: str) -> None:
    """Etkin kümenin oturumu yeniden kurulur: bağlantıyı yürütücü taşıyor (R6-10)."""
    current = request.app.state.session
    try:
        new = open_session(
            dataset=name,
            model=current.profile.name if current.profile else None,
            llm=current.llm_kind,
            models_file=current.models_file,
            audit_path=current.audit_path,
            ask_log=current.ask_log,
            connections=request.app.state.connections,
        )
    except SessionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from None
    with request.app.state.session_lock:
        request.app.state.session = new


def _tables(ds: datasets.Dataset) -> list[str]:
    """Yoklamanın örnekleyeceği adlar: haritanın kendi allowlisti.

    Yarım kalmış bir harita (R6-16) yoklamayı düşürmez: örnek boş kalır, güç denetimleri yine
    sorulur, eksik zaten raporun kendi satırıdır.
    """
    try:
        return sorted(doc.allowlist(ds.schema()))
    except (OSError, json.JSONDecodeError):
        return []


def _saver(request: Request) -> str | None:
    """Satırı kimin yazdığı: kapının çözdüğü yönetici; tek kullanıcılı modda ad yoktur (R6-9)."""
    user = current_user(request)
    return user["username"] if user else None


def _active_name(request: Request) -> str | None:
    """Oturumun şu anki kümesinin adı; genel ortam değişkeni yalnız ona aittir (R7-23)."""
    ds = request.app.state.session.dataset
    return ds.name if ds else None
