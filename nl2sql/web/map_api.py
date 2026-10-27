"""Şema haritası API'si: şablonun indirilmesi, yüklemenin önizlenmesi, küme yapılması (PLAN R6-16, R6-17).

Üç indirme, iki yazma: şablon ile dolu örnek diskte durmaz, her istekte kurulur; önizleme tek bir
JSON bırakır, uygulama ise o JSON'u okuyup sıfırdan bir küme klasörü kurar. Yolların hepsi yönetici
ister - biri sunucuya yeni bir veri kümesi ekliyor (R6-5).

Önizleme ile uygulamanın iki ayrı yol olmasının sebebi, kullanıcının kontrol raporunu arada
okumasıdır; o yüzden süresi dolan bir önizleme 404 alır ve hiçbir veri kümesine dokunmamış olması
gerekir. Uygulamanın açtığı indeks işi bu modülün kapanışında değil, ``onboard.IndexJobs``un
iş parçacığındadır - ekran ``status``u yoklayarak ilerler.
"""

from __future__ import annotations

import base64
import binascii
import io
import os
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from openpyxl.utils.exceptions import InvalidFileException
from pydantic import BaseModel

from nl2sql import config, datasets
from nl2sql.engine._mssql import CONN_ENV
from nl2sql.report.export import MEDIA_TYPES
from nl2sql.schema_map import introspect, onboard, template, template_import
from nl2sql.i18n import t
from nl2sql.web.authz import current_user, require
from nl2sql.web.lang import request_lang

# Sözleşme "preview response": ekrana dönen alanlar, diske yazılan kaydın bir alt kümesidir.
PREVIEW_FIELDS = ("dataset", "counts", "errors", "warnings", "db_check")
# Sözleşme "template info": ``{"db_connection": bool}`` - düğme yalnız canlı bağlantı varsa görünür.
# Sözleşme "template info"nun öteki yüzü: arayüzün indirdiği dolu örnek hangi adla doğar.
SAMPLE_DATASET = "ornek_fatura"
# R6-16: red cümleleri kataloğundur ve yollar onu isteğin diliyle okur; .xlsx kararı ada değil
# içeriğe bakarak verilir. Şu dört ad başka testlerin importıdır, o yüzden anahtarları değil
# program dilinin cümlesini taşırlar.
NOT_XLSX = t("map.not_xlsx")
NO_PREVIEW = t("map.no_preview")
STILL_BROKEN = t("map.still_broken")
# R6-17: yoklama başarısız olsa da boş şablon verilir; başlık percent-kodludur, çünkü HTTP başlığı
# Türkçe metin taşımaz. Aynı cümlenin tekrarı yoklama yapılmaz - ikinci bir giriş yok.
NOTE_HEADER = "X-Bilgin-Note"
DB_NOTE = t("map.db_note")


class PreviewBody(BaseModel):
    """``POST /api/schema-map/preview`` gövdesi (Contracts): ad kullanıcıdan, içerik base64'ten."""

    filename: str = ""
    content_b64: str = ""


class ApplyBody(BaseModel):
    """``POST /api/schema-map/apply`` gövdesi (Contracts): yalnız bekleyen önizlemenin kimliği."""

    preview_id: str = ""


def create_router() -> APIRouter:
    """Haritanın altı yönetici yolu; işlerin kaydı router ile birlikte doğar, uygulamayla ölür."""
    router = APIRouter()
    admin = [Depends(require("admin"))]
    jobs = onboard.IndexJobs()

    @router.get("/api/schema-map/info", dependencies=admin)
    def info() -> dict:
        """Arayüzün "veritabanından doldur" düğmesi: yalnız ölçülen SQL Server ve bir dize varsa."""
        return {"db_connection": _db_connection()}

    @router.get("/api/schema-map/template.xlsx", dependencies=admin)
    def download_template(request: Request, from_db: bool = False) -> Response:
        """Boş şablon; ``?from_db=1`` canlı iskeletle doldurulur, okunamazsa boş olan notla verilir."""
        if not (from_db and _db_connection()):
            return _xlsx(template.build_template(), config.TEMPLATE_FILENAME)
        try:
            return _xlsx(template.build_template(introspect.mssql_skeleton()), config.TEMPLATE_FILENAME)
        except introspect.IntrospectError:
            return _xlsx(
                template.build_template(),
                config.TEMPLATE_FILENAME,
                note=t("map.db_note", _lang(request)),
            )

    @router.get("/api/schema-map/sample.xlsx", dependencies=admin)
    def download_sample() -> Response:
        """Dolu örnek: tek bir tablonun eksiksiz doldurulmuş hâli, yani yükleme akışının denemesi."""
        return _xlsx(
            template.filled_example_workbook(SAMPLE_DATASET), f"{SAMPLE_DATASET}.xlsx"
        )

    @router.post("/api/schema-map/preview", dependencies=admin)
    def preview(body: PreviewBody, request: Request) -> dict:
        """Yüklenen dosyanın kontrol raporu: tek yazdığı bekletilen önizleme kaydının kendisidir."""
        lang = _lang(request)
        data = _decode(body.content_b64, lang)
        if len(data) > config.MAP_MAX_BYTES:
            raise HTTPException(
                status_code=413,
                detail=t("map.too_large", lang, mb=config.MAP_MAX_BYTES // (1024 * 1024)),
            )
        if not _is_xlsx(data):
            raise HTTPException(status_code=422, detail=t("map.not_xlsx", lang))
        read = _read_upload(data, request, lang)
        skeleton, note = _live_skeleton(read)
        errors, warnings, db_check = template_import.validate(read, skeleton, lang)
        if note:
            db_check = {**db_check, "message": note}
        result = {
            "dataset": read["dataset"],
            "counts": read["counts"],
            "errors": errors,
            "warnings": warnings,
            "db_check": db_check,
            "schema": read["schema"],
            "rules": read["rules"],
        }
        preview_id = onboard.save_preview(result, _username(request), body.filename)
        return {"preview_id": preview_id, **{key: result[key] for key in PREVIEW_FIELDS}}

    @router.post("/api/schema-map/apply", dependencies=admin)
    def apply(body: ApplyBody, request: Request) -> dict:
        """Bekleyen raporu küme klasörüne çevirir ve indeksi arka plana bırakır (R6-16)."""
        lang = _lang(request)
        preview = onboard.load_preview(body.preview_id)
        if preview is None:
            raise HTTPException(status_code=404, detail=t("map.no_preview", lang))
        if preview.get("errors"):
            raise HTTPException(status_code=409, detail=t("map.still_broken", lang))
        name = preview["dataset"]["name"]
        if datasets.name_taken(name):
            raise HTTPException(status_code=409, detail=t("map.name_taken", lang, name=name))
        try:
            onboard.apply_preview(preview, _username(request), lang)
        except FileExistsError:
            # Rapor okunduğu anda ad boştu; arada biri aynı kümeyi kurmuşsa var olana dokunulmaz.
            raise HTTPException(
                status_code=409, detail=t("map.name_taken", lang, name=name)
            ) from None
        # İş parçacığının kendi isteği yok: cümlesinin dili onu başlatan yolun dilidir (R8-5).
        jobs.start(
            body.preview_id, name, _embed(request), suggest=_suggest(request.app), lang=lang
        )
        return jobs.status(body.preview_id)

    @router.get("/api/schema-map/status/{preview_id}", dependencies=admin)
    def status(preview_id: str, request: Request) -> dict:
        """Sözleşme "apply / status": hiç başlamamış bir işin aşaması yoktur, o yüzden 404."""
        job = jobs.status(preview_id)
        if job is None:
            raise HTTPException(status_code=404, detail=t("map.no_preview", _lang(request)))
        return job

    return router


def _lang(request: Request) -> str:
    """Yolun arayüz dili: kişinin tercihi, yoksa tarayıcının başlığı, o da yoksa programın dili (R8-5)."""
    return request_lang(request, current_user(request))


def _suggest(app):
    """İndeks bittiğinde öneri işini başlatan kanca (R7-20): işlerin deposu uygulamada yaşar.

    Uygulama kancanın içine yol tarafından konur - kanca iş parçacığında koşar, onu kuran istek
    o zamana kadar çoktan kapanmış olur.
    """

    def start(name: str) -> None:
        app.state.suggest.start(name)

    return start


def _db_connection() -> bool:
    """Canlı bir SQL Server yoklanabilir mi: ölçülen sunucu o ve bir bağlantı dizesi var."""
    return config.backend() == "mssql" and bool(os.environ.get(CONN_ENV, "").strip())


def _live_skeleton(read: dict) -> tuple[dict | None, str | None]:
    """Canlı iskelet, ya da sorulmadıysa tek cümlesi (R6-15, R6-16).

    Yoklama yalnız sunucu yoklanabilir *ve* küme SQL Server diyorsa yapılır; tutmazsa
    karşılaştırma sorulmamış sayılır - cümle hataya dönüşmez ve sunucu bir daha yoklanmaz.
    """
    if not (_db_connection() and read["dataset"].get("connection") == "mssql"):
        return None, None
    try:
        return introspect.mssql_skeleton(), None
    except introspect.IntrospectError as exc:
        return None, str(exc)


def _decode(content_b64: str, lang: str) -> bytes:
    """Gövdenin base64'ü; çözülemeyen bir metin zaten bir çalışma kitabı değildir."""
    try:
        return base64.b64decode(content_b64)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail=t("map.not_xlsx", lang)) from None


def _is_xlsx(data: bytes) -> bool:
    """İçeriğin kendisi: zip taşıyıcısı ve içindeki ``[Content_Types].xml`` (R6-16, dosya adına değil)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as book:
            return "[Content_Types].xml" in book.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def _read_upload(data: bytes, request: Request, lang: str) -> dict:
    """Baytlar geçici bir dosyada okunur: okuyucu bir yol ister, yüklemenin diske düşmesi gerekmez."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "yukleme.xlsx"
        path.write_bytes(data)
        # ASSUMPTION: model yalnız şablon olmayan çalışma kitabının başlıklarını sorar; şablonun
        # kendi okuması LLM'sizdir, yani kapalı bir uç nokta şablon yüklemeyi durdurmaz.
        llm = None if template_import.is_bilgin_template(path) else _llm(request)
        try:
            return template_import.read_template(path, llm=llm, lang=lang)
        except template_import.TemplateError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except (InvalidFileException, zipfile.BadZipFile, OSError, ValueError, KeyError):
            raise HTTPException(status_code=422, detail=t("map.unreadable", lang)) from None


def _llm(request: Request):
    """Oturumun modeli: başlık önerisi bir kez ona sorulur, mod araç taşımadığı için söz sahibi değil."""
    return request.app.state.session.agent_llm("full")


def _embed(request: Request) -> str:
    """İndeksin vektör kaynağı: sahte modelin uç noktası yok, yani sahte uzay da sahte olmalı."""
    return "fake" if request.app.state.session.llm_kind == "fake" else "openai"


def _username(request: Request) -> str:
    """Değişim günlüğünün ve önizlemenin sahibi: kapının çözdüğü kullanıcının adı."""
    user = current_user(request)
    return user["username"] if user else ""


def _xlsx(content: bytes, filename: str, note: str | None = None) -> Response:
    """Excel indirimi: eklenti başlığı ve varsa yoklamanın notu (percent-kodlu, R6-17)."""
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if note:
        headers[NOTE_HEADER] = quote(note)
    return Response(content=content, media_type=MEDIA_TYPES["xlsx"], headers=headers)
