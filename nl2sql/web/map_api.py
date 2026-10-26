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
from nl2sql.web.authz import current_user, require

# Sözleşme "preview response": ekrana dönen alanlar, diske yazılan kaydın bir alt kümesidir.
PREVIEW_FIELDS = ("dataset", "counts", "errors", "warnings", "db_check")
# Sözleşme "template info": ``{"db_connection": bool}`` - düğme yalnız canlı bağlantı varsa görünür.
# Sözleşme "template info"nun öteki yüzü: arayüzün indirdiği dolu örnek hangi adla doğar.
SAMPLE_DATASET = "ornek_fatura"
# R6-16: red cümleleri; .xlsx kararı ada değil içeriğe bakarak verilir.
NOT_XLSX = "Yalnız .xlsx dosyası yüklenebilir."
UNREADABLE = "Dosya okunamadı; Excel'in .xlsx biçiminde olduğundan emin olun."
TOO_LARGE = (
    f"Dosya çok büyük; en fazla {config.MAP_MAX_BYTES // (1024 * 1024)} MB yüklenebilir."
)
NO_PREVIEW = "Önizleme bulunamadı ya da süresi doldu."
STILL_BROKEN = "Önizlemede düzeltilmemiş hata var; şablonu düzeltip yeniden yükleyin."
NAME_TAKEN = "Bu ad zaten bir veri kümesi: {name}."
# R6-17: yoklama başarısız olsa da boş şablon verilir; başlık percent-kodludur, çünkü HTTP başlığı
# Türkçe metin taşımaz. Aynı cümlenin tekrarı yoklama yapılmaz - ikinci bir giriş yok.
NOTE_HEADER = "X-Bilgin-Note"
DB_NOTE = "Salt okunur giriş tablo bilgisini okuyamadı (VIEW DEFINITION); boş şablon verildi."


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
    def download_template(from_db: bool = False) -> Response:
        """Boş şablon; ``?from_db=1`` canlı iskeletle doldurulur, okunamazsa boş olan notla verilir."""
        if not (from_db and _db_connection()):
            return _xlsx(template.build_template(), config.TEMPLATE_FILENAME)
        try:
            return _xlsx(template.build_template(introspect.mssql_skeleton()), config.TEMPLATE_FILENAME)
        except introspect.IntrospectError:
            return _xlsx(template.build_template(), config.TEMPLATE_FILENAME, note=DB_NOTE)

    @router.get("/api/schema-map/sample.xlsx", dependencies=admin)
    def download_sample() -> Response:
        """Dolu örnek: tek bir tablonun eksiksiz doldurulmuş hâli, yani yükleme akışının denemesi."""
        return _xlsx(
            template.filled_example_workbook(SAMPLE_DATASET), f"{SAMPLE_DATASET}.xlsx"
        )

    @router.post("/api/schema-map/preview", dependencies=admin)
    def preview(body: PreviewBody, request: Request) -> dict:
        """Yüklenen dosyanın kontrol raporu: tek yazdığı bekletilen önizleme kaydının kendisidir."""
        data = _decode(body.content_b64)
        if len(data) > config.MAP_MAX_BYTES:
            raise HTTPException(status_code=413, detail=TOO_LARGE)
        if not _is_xlsx(data):
            raise HTTPException(status_code=422, detail=NOT_XLSX)
        read = _read_upload(data, request)
        skeleton, note = _live_skeleton(read)
        errors, warnings, db_check = template_import.validate(read, skeleton)
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
        preview = onboard.load_preview(body.preview_id)
        if preview is None:
            raise HTTPException(status_code=404, detail=NO_PREVIEW)
        if preview.get("errors"):
            raise HTTPException(status_code=409, detail=STILL_BROKEN)
        name = preview["dataset"]["name"]
        if datasets.name_taken(name):
            raise HTTPException(status_code=409, detail=NAME_TAKEN.format(name=name))
        try:
            onboard.apply_preview(preview, _username(request))
        except FileExistsError:
            # Rapor okunduğu anda ad boştu; arada biri aynı kümeyi kurmuşsa var olana dokunulmaz.
            raise HTTPException(status_code=409, detail=NAME_TAKEN.format(name=name)) from None
        jobs.start(body.preview_id, name, _embed(request))
        return jobs.status(body.preview_id)

    @router.get("/api/schema-map/status/{preview_id}", dependencies=admin)
    def status(preview_id: str) -> dict:
        """Sözleşme "apply / status": hiç başlamamış bir işin aşaması yoktur, o yüzden 404."""
        job = jobs.status(preview_id)
        if job is None:
            raise HTTPException(status_code=404, detail=NO_PREVIEW)
        return job

    return router


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


def _decode(content_b64: str) -> bytes:
    """Gövdenin base64'ü; çözülemeyen bir metin zaten bir çalışma kitabı değildir."""
    try:
        return base64.b64decode(content_b64)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=422, detail=NOT_XLSX) from None


def _is_xlsx(data: bytes) -> bool:
    """İçeriğin kendisi: zip taşıyıcısı ve içindeki ``[Content_Types].xml`` (R6-16, dosya adına değil)."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as book:
            return "[Content_Types].xml" in book.namelist()
    except (zipfile.BadZipFile, OSError):
        return False


def _read_upload(data: bytes, request: Request) -> dict:
    """Baytlar geçici bir dosyada okunur: okuyucu bir yol ister, yüklemenin diske düşmesi gerekmez."""
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "yukleme.xlsx"
        path.write_bytes(data)
        # ASSUMPTION: model yalnız şablon olmayan çalışma kitabının başlıklarını sorar; şablonun
        # kendi okuması LLM'sizdir, yani kapalı bir uç nokta şablon yüklemeyi durdurmaz.
        llm = None if template_import.is_bilgin_template(path) else _llm(request)
        try:
            return template_import.read_template(path, llm=llm)
        except template_import.TemplateError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from None
        except (InvalidFileException, zipfile.BadZipFile, OSError, ValueError, KeyError):
            raise HTTPException(status_code=422, detail=UNREADABLE) from None


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
