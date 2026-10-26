"""Veri kümeleri API'si: liste, etkin kümeyi değiştirme, salt okunur giriş betiği (PLAN R6-18).

Üç yol da yönetici ister (R6-5): etkin kümeyi değiştirmek sunucunun hangi veritabanına baktığını
değiştirmektir. Değişim tek bir atamadır (R6-10) - yollar oturumu her istekte ``app.state``ten
okur, yani bir sonraki istek yeni dünyayı görür. Yeni oturum ancak kurulduktan sonra yerinden
edilir: kurulamayan bir geçiş eski dünyayı olduğu gibi bırakır.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

from nl2sql import config, datasets
from nl2sql.app.session import SessionError, open_session
from nl2sql.engine.login_script import DEFAULT_LOGIN, readonly_login_sql
from nl2sql.index.search import load_search
from nl2sql.index.store import META_FILE, MissingIndexError, StaleIndexError
from nl2sql.start.seed import ensure_seeded
from nl2sql.web.authz import require

# Sözleşme "settings": etkin kümenin adı kullanıcı deposunun ayarlarındadır, ``serve`` oradan okur.
ACTIVE_SETTING = "active_dataset"
# Sözleşme "switch": SQL Server kümesine geçişin duyurusu bu adresi ve bu ortam değişkenini taşır.
LOGIN_SCRIPT_ENV = "NL2SQL_MSSQL_CONN"
LOGIN_NOTICE = "Bu küme SQL Server'a bağlı: salt okunur girişi kurun ve sunucuyu {env} ile başlatın."
# R6-16: haritadan kurulan küme betiği klasöründe taşır; eski kümelerde o dosya yoktur, üretilir.
LOGIN_SCRIPT_FILE = "readonly_login.sql"
# Bozuk bir klasör (yarıda kesilmiş bir apply, elle düzenlenmiş bir dosya) ekranı düşürmez: liste
# o satırı okunamayan bir cümleyle, tek tek yollar ise 404/409 cümlesiyle söyler.
INDEX_UNREADABLE = "Kümenin şeması okunamadığı için indeksi denetlenemedi."
BROKEN_DATASET = "Veri kümesi okunamıyor: {name}. Klasördeki bir dosya eksik ya da bozuk."


class ActiveBody(BaseModel):
    """``POST /api/datasets/active`` gövdesi (Contracts "switch"): yalnız kümenin adı."""

    name: str = ""


def create_router() -> APIRouter:
    """Kümelerin üç yönetici yolu; oturumun değişimi ``app.state`` üzerinden olur."""
    router = APIRouter()
    admin = [Depends(require("admin"))]

    @router.get("/api/datasets", dependencies=admin)
    def datasets_list(request: Request) -> dict:
        """Kümeler ve hangisinin etkin olduğu; her satır indeksinin durumunu da taşır (R6-18)."""
        active = _active_name(request)
        items = []
        for item in datasets.all_datasets():
            ds = _load(item["name"])
            items.append({
                **item,
                "active": item["name"] == active,
                "index": _index_state(ds),
            })
        return {"active": active, "datasets": items}

    @router.post("/api/datasets/active", dependencies=admin)
    def activate(body: ActiveBody, request: Request) -> dict:
        """Etkin kümeyi değiştirir: yeni oturum kurulur, sonra tek atamayla yerine geçer.

        Model, model dosyası, llm kaynağı ve günlük yolları bugünkü oturumdan alınır - ekran
        yalnız dünyayı değiştirir, sunduğu modeli değiştirmez. Veritabanı olmayan bir küme
        ``open_session``ın kendi cümlesiyle 409 alır ve eski oturum yerinde kalır.
        """
        name = body.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="Veri kümesi adı boş.")
        current = request.app.state.session
        ds = _load(name)
        try:
            new = open_session(
                dataset=name,
                model=current.profile.name if current.profile else None,
                llm=current.llm_kind,
                models_file=current.models_file,
                audit_path=current.audit_path,
                ask_log=current.ask_log,
            )
        except SessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from None
        except (OSError, json.JSONDecodeError):
            # Klasördeki bir dosya eksik ya da bozuk: oturum kurulamaz, eski dünya yerinde kalır.
            raise HTTPException(status_code=409, detail=BROKEN_DATASET.format(name=name)) from None
        with request.app.state.session_lock:
            request.app.state.session = new
        users = request.app.state.users
        if users is not None:
            users.set_setting(ACTIVE_SETTING, ds.name)
            # R7-19: geçilen kümenin tohum hazır soruları da ilk geçişte bir kez yazılır -
            # başlangıç ekranı yeni dünyada boş doğmaz.
            ensure_seeded(request.app.state.ready, users, ds, new.executor)
        return {
            "active": ds.name,
            "dataset": {
                "name": ds.name,
                "display_name": ds.display_name,
                "connection": ds.connection,
            },
            "notice": _notice(ds),
        }

    @router.get("/api/datasets/{name}/login-script.sql", dependencies=admin)
    def login_script(name: str) -> Response:
        """Kümenin salt okunur giriş betiği: klasördeki varsa o, yoksa şemasından kurulur (R3-8)."""
        ds = _load(name)
        stored = ds.root / LOGIN_SCRIPT_FILE
        try:
            sql = (
                stored.read_text(encoding="utf-8")
                if stored.is_file()
                else readonly_login_sql(ds.schema(), DEFAULT_LOGIN)
            )
        except (OSError, json.JSONDecodeError):
            raise HTTPException(status_code=409, detail=BROKEN_DATASET.format(name=name)) from None
        return Response(content=sql, media_type="text/plain; charset=utf-8")

    return router


def _load(name: str) -> datasets.Dataset:
    """Kümenin tanımı; yoksa ekranın okuyacağı 404 (cümle hangi adın bilindiğini de sayar)."""
    try:
        return datasets.load_dataset(name)
    except datasets.DatasetError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from None


def _active_name(request: Request) -> str:
    """Oturumun şu anki kümesinin adı; küme söylenmemişse ölçülen zaten config'in kümesidir."""
    ds = request.app.state.session.dataset
    return ds.name if ds else config.DEFAULT_DATASET


def _index_state(ds: datasets.Dataset) -> dict:
    """Kümenin indeksi bu şema ve kurallarla yüklenebiliyor mu: ``_index_block``un küme okuyan hali."""
    try:
        load_search(ds.index_dir, ds.schema(), ds.rules(), ds.name)
    except (MissingIndexError, StaleIndexError) as exc:
        return {
            "exists": (ds.index_dir / META_FILE).is_file(),
            "fresh": False,
            "reason": str(exc),
        }
    except (OSError, json.JSONDecodeError):
        # Şeması okunamayan bir küme (R6-16'nın yarım kalan koşumu) listeyi düşürmez: satır
        # "İndeks yok" olarak çıkar, sebebi ekranın göstereceği cümledir.
        return {"exists": False, "fresh": False, "reason": INDEX_UNREADABLE}
    return {"exists": True, "fresh": True, "reason": None}


def _notice(ds: datasets.Dataset) -> dict | None:
    """Geçişin duyurusu: yalnız SQL Server kümesi bir sonraki adımı gerektirir (R6-18)."""
    if ds.connection != "mssql":
        return None
    return {
        "login_script_url": f"/api/datasets/{ds.name}/login-script.sql",
        "env": LOGIN_SCRIPT_ENV,
        "message": LOGIN_NOTICE.format(env=LOGIN_SCRIPT_ENV),
    }
