# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Web API'si: tek kullanıcılık FastAPI uygulaması (PLAN R5-15).

Yolların ardında ikinci bir hesap kitap yok: ``/api/ask`` ``ask_payload``ı çağırır, yani ekran ile
``ask --json`` aynı cevabı görür. Uygulama kimlik doğrulaması olmadığı için yalnız 127.0.0.1'e
bağlanır (``serve`` söyler), arayüz derlenmemişse API yine çalışır - ``/`` o zaman neyin eksik
olduğunu kendi cümlesiyle söyler, node'a muhtaç kalmaz.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nl2sql import config
from nl2sql.agent import prompt
from nl2sql.app import asklog
from nl2sql.app.ask import ask_payload
from nl2sql.cli import main as cli
from nl2sql.engine.result import Budget
from nl2sql.eval import runner
from nl2sql.index.search import load_search
from nl2sql.index.store import META_FILE, MissingIndexError, StaleIndexError, content_hash
from nl2sql.report.export import MEDIA_TYPES, to_csv_bytes, to_xlsx_bytes
from nl2sql.schema_map import doc
from nl2sql.schema_map.rules_edit import normalize_rule, save_rules, validate_rule
from nl2sql.web.saved import SavedStore

# R5-15: boş soru koşum açmaya değmez; cümle ekranın gösterdiği cümledir.
BLANK_QUESTION = "Soru boş."
# R5-16: silinmek istenen kayıt zaten yoksa ekranın okuyacağı cümle.
NO_SAVED = "Kayıtlı soru bulunamadı."
# R5-16: dışa aktarımın red cümleleri; 404 bilinmeyen soru, 409 dışa aktarılacak cevap değil.
NO_ASK = "Bu sorunun kaydı bulunamadı."
NOT_ANSWERED = "Yalnızca cevaplanmış bir soru dışa aktarılabilir."
OTHER_DATASET = "Bu kayıt başka bir veri kümesine ait."
# R5-16: kural API'sinin red cümleleri; 404 bilinmeyen kural, 409 çakışan kimlik, 500 kurulamayan indeks.
NO_RULE = "Kural bulunamadı: {id}."
DUPLICATE_RULE = "Bu kimlikte bir kural zaten var: {id}."
REBUILD_FAILED = "İndeks yeniden kurulamadı: embedding uç noktası yanıt vermiyor olabilir."
NO_UI = "Arayüz derlenmemiş"
BUILD_COMMAND = "npm --prefix web run build"

# Arayüzün yerine geçen sayfa: R5-18'in renkleri, tek kart, tek cümle ve tek komut.
NO_UI_PAGE = f"""<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bilgin</title>
<style>
  :root {{ color-scheme: light dark; --bg: #F6F5F1; --surface: #FFFFFF; --text: #1D1D1B;
           --muted: #6A6963; --line: #E3E1DA; --accent: #1F5FAD; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg: #141413; --surface: #1D1D1B;
           --text: #F6F5F1; --muted: #9A9891; --line: #33322E; --accent: #7FAEE8; }} }}
  body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: var(--bg);
          color: var(--text); font: 16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; }}
  main {{ width: min(560px, calc(100% - 48px)); background: var(--surface); border: 1px solid var(--line);
          border-radius: 10px; padding: 32px; }}
  .mark {{ margin: 0 0 16px; color: var(--accent); font-weight: 650; letter-spacing: 0.02em; }}
  h1 {{ margin: 0 0 8px; font-size: 22px; }}
  p {{ margin: 0 0 16px; color: var(--muted); }}
  code, pre {{ font-family: ui-monospace, "Cascadia Mono", Consolas, monospace; }}
  code {{ background: var(--bg); border: 1px solid var(--line); border-radius: 4px; padding: 1px 5px; }}
  pre {{ margin: 0; padding: 12px; background: var(--bg); border: 1px solid var(--line);
         border-radius: 10px; overflow-x: auto; }}
</style>
</head>
<body>
<main>
  <p class="mark">Bilgin</p>
  <h1>{NO_UI}</h1>
  <p>API çalışıyor; ekranı görmek için arayüzü bir kez derleyin:</p>
  <pre>{BUILD_COMMAND}</pre>
  <p>Durumu okumak için: <code>GET /api/health</code></p>
</main>
</body>
</html>
"""


class AskBody(BaseModel):
    """``POST /api/ask`` gövdesi (Contracts): soru zorunlu, mod ve seçim sorulabilir."""

    question: str = ""
    mode: str | None = None
    choice: str | None = None


class SavedBody(BaseModel):
    """``POST /api/saved`` gövdesi (Contracts): soru zorunlu, mod ve SQL sorulabilir."""

    question: str = ""
    mode: str | None = None
    sql: str | None = None


class RuleRejected(Exception):
    """Kural doğrulamasının hataları (Contracts "rules API"): gövde ``{"errors": [...]}`` olur.

    ``HTTPException``ın gövdesi her zaman ``detail`` anahtarının altına yerleştiği için alan
    hataları onla yükselmez; ekran ``errors``ı okur.
    """

    def __init__(self, errors: list[dict]):
        super().__init__(errors)
        self.errors = errors


def create_app(session, saved_path: str | Path = config.APP_DB_PATH, static_dir: str | Path = config.STATIC_DIR) -> FastAPI:
    """Oturumun üstünde API: soru, sağlık, örnekler, tablolar, kayıtlar, dışa aktarım ve arayüz."""
    app = FastAPI(title="Bilgin")
    app.state.session = session
    app.state.saved_path = Path(saved_path)
    saved = SavedStore(saved_path)
    # Kayıtlar küme başına: ekran başlığın söylediği kümenin dışına çıkmaz (R5-16).
    dataset = _dataset_block(session)["name"]
    static = Path(static_dir)

    @app.exception_handler(RuleRejected)
    async def rule_rejected(request, exc: RuleRejected):
        """Alan hataları 422 olarak üst düzey ``errors`` anahtarıyla döner (R5-15)."""
        return JSONResponse(status_code=422, content={"errors": exc.errors})

    @app.post("/api/ask")
    def ask(body: AskBody) -> dict:
        """Sorunun cevabı: CLI ile birebir aynı payload, kaynağı ``web`` (R5-1)."""
        question = body.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail=BLANK_QUESTION)
        return ask_payload(session, question, mode=body.mode, choice=body.choice, source="web")

    @app.get("/api/health")
    def health() -> dict:
        """Başlığın çipleri: hangi küme, model sağ mı, indeks taze mi, auto eşiği ne."""
        return {
            "status": "ok",
            "dataset": _dataset_block(session),
            "llm": _llm_block(session),
            "index": _index_block(session),
            "schema_hash": content_hash(session.schema, []),
            "rules_hash": content_hash({}, session.rules),
            "mode": _mode_block(session),
            "budget": session.budget,
        }

    @app.get("/api/examples")
    def examples() -> dict:
        """Boş ekrandaki çipler: altın soruların ilki, yani gerçekten cevaplanabilenler."""
        lines = runner.load_golden(
            session.dataset.golden_path if session.dataset else config.GOLDEN_PATH
        )
        examples = [
            {"question": line["question"], "kind": "golden"} for line in lines[: config.EXAMPLES_N]
        ]
        # R5-15: belirsiz sorunun tek çipi netleştirme demosunu çiplerden erişilebilir kılar;
        # kümenin böyle bir dosyası yoksa çip de yoktur.
        ambiguous = session.dataset.ambiguous() if session.dataset else []
        if ambiguous:
            examples.append({"question": ambiguous[0]["question"], "kind": "ambiguous"})
        return {"examples": examples}

    @app.get("/api/tables")
    def tables() -> dict:
        """Kural formunun tablo listesi: ölçülen şemanın adları, sırasıyla."""
        return {"tables": [table["name"] for table in session.schema["tables"]]}

    @app.get("/api/rules")
    def rules_list() -> dict:
        """Kural ekranı: kümenin kuralları ve indeksin tazeliği (R5-16)."""
        return {"rules": session.rules, "index": _index_block(session)}

    @app.post("/api/rules")
    def rules_add(rule: dict) -> dict:
        """Yeni kural: çakışan kimlik 409, doğrulama hatası 422, sonra disk ve oturum tazelenir."""
        rid = str(rule.get("id", "")).strip()
        if any(existing.get("id") == rid for existing in session.rules):
            raise HTTPException(
                status_code=409, detail=[{"field": "id", "message": DUPLICATE_RULE.format(id=rid)}]
            )
        _check_rule(session, rule)
        return _write_rules(session, session.rules + [normalize_rule(rule)])

    @app.put("/api/rules/{rule_id}")
    def rules_update(rule_id: str, rule: dict) -> dict:
        """Kimliğiyle bulunan kuralı gövdeyle değiştirir; olmayan kimlik 404 (R5-16)."""
        _find_rule(session, rule_id)
        rule = {**rule, "id": rule_id}
        _check_rule(session, rule, editing_id=rule_id)
        return _write_rules(session, [
            normalize_rule(rule) if existing.get("id") == rule_id else existing
            for existing in session.rules
        ])

    @app.delete("/api/rules/{rule_id}")
    def rules_delete(rule_id: str) -> dict:
        """Kuralı hem diskten hem oturumdan çıkarır; olmayan kimlik 404 (R5-16)."""
        _find_rule(session, rule_id)
        return _write_rules(session, [r for r in session.rules if r.get("id") != rule_id])

    @app.post("/api/index/rebuild")
    def index_rebuild() -> dict:
        """İndeksi mevcut kurallarla yeniden kurar; bayatlık ancak böyle kalkar (R5-16).

        Embedder mevcut indeksin meta'sından alınır, yani aynı vektör uzayı korunur; indeks hiç
        yoksa ``--llm fake`` sahte uzayı, aksi halde OpenAI uyumlu uç noktayı kullanır.
        """
        embed = cli._index_embedder(session.index_dir)
        if not embed:
            embed = "fake" if session.llm_kind == "fake" else "openai"
        ds = session.dataset
        started = time.perf_counter()
        code = cli.build_index(
            embed,
            index_dir=session.index_dir,
            schema_path=ds.schema_path if ds else config.SCHEMA_PATH,
            rules_path=_rules_path(session),
            dataset=ds.name if ds else None,
        )
        if code != 0:
            raise HTTPException(status_code=500, detail=REBUILD_FAILED)
        return {
            "index": _index_block(session),
            "counts": _index_counts(session),
            "seconds": round(time.perf_counter() - started, 1),
        }

    @app.get("/api/saved")
    def saved_list() -> dict:
        """Kenar çubuğu: bu kümenin kayıtlı soruları, en yeni önce (R5-16)."""
        return {"saved": saved.list(dataset)}

    @app.post("/api/saved")
    def saved_add(body: SavedBody) -> dict:
        """Soruyu kenar çubuğuna eklemek: saklanan cevabı değil, sorunun metni ve SQL'i."""
        question = body.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail=BLANK_QUESTION)
        # ASSUMPTION: POST tek kaydın kendisini döndürür; ekran istersen listeyi yeniden çeker.
        return {"saved": saved.add(question, mode=body.mode, sql=body.sql, dataset=dataset)}

    @app.delete("/api/saved/{id}")
    def saved_delete(id: int) -> dict:
        """Kaydı kenar çubuğundan çıkarır; olmayan kaydın silinecek bir şeyi yok (404)."""
        if not saved.delete(id):
            raise HTTPException(status_code=404, detail=NO_SAVED)
        return {"deleted": id}

    @app.get("/api/history")
    def history() -> dict:
        """Son sorular: soru günlüğünün satırları, en yeni önce; veri satırları asla (R5-4)."""
        return {"history": asklog.history(session.ask_log)}

    @app.get("/api/export/{audit_id}.csv")
    def export_csv(audit_id: str) -> Response:
        """Cevabın tamamı CSV: ``bilgin_<id>.csv`` adı ile iner (R5-16)."""
        return _export(session, dataset, audit_id, "csv")

    @app.get("/api/export/{audit_id}.xlsx")
    def export_xlsx(audit_id: str) -> Response:
        """Cevabın tamamı Excel: sayı hücreleri sayı olarak kalır (R5-16)."""
        return _export(session, dataset, audit_id, "xlsx")

    assets = static / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", response_class=HTMLResponse)
    def index():
        """Derlenmiş arayüz varsa o, yoksa neyin eksik olduğunu söyleyen sayfa (200)."""
        page = static / "index.html"
        if page.is_file():
            return FileResponse(page, media_type="text/html")
        return HTMLResponse(NO_UI_PAGE)

    return app


def _export(session, dataset: str, audit_id: str, ext: str) -> Response:
    """Günlükteki SQL'i dışa aktarım bütçesiyle bir kez daha koşar ve dosyayı hazırlar (R5-16).

    Satırlar yürütücünün döndürdükleridir: PII maskesi bu yürüyüşte de üstlerinden geçer, yani
    indirme ekranın gösterdiğinden fazlasını asla vermez. Denetim satırı ``export:<id>`` kaynağını
    taşır, böylece hangi indirmenin hangi sorguyu koştuğu soru günlüğüyle birleşir (R5-4).
    """
    record = asklog.find_ask(audit_id, session.ask_log)
    if record is None:
        raise HTTPException(status_code=404, detail=NO_ASK)
    if record.get("status") != "answered":
        raise HTTPException(status_code=409, detail=NOT_ANSWERED)
    # ASSUMPTION: günlüğü yazan oturum küme adı taşımıyorsa ölçülen config'in kümesidir, yani
    # adsız ``serve`` kendi indirmesini reddetmez.
    if record.get("dataset") not in (None, dataset):
        raise HTTPException(status_code=409, detail=OTHER_DATASET)
    # Tavan da dışa aktarım bütçesidir: TOP_N'de kalan bir TOP, bütçe geniş olsa bile 1000 satır
    # döndürür ve `truncated` False kalırdı - dosya eksik, uyarısız (R5-16).
    result = session.executor.execute(
        record.get("sql") or "",
        Budget(max_rows=config.EXPORT_MAX_ROWS),
        f"export:{audit_id}",
        top_n=config.EXPORT_MAX_ROWS,
    )
    if result.error is not None:
        # ASSUMPTION: yeniden koşumun reddi bir çelişkidir; sebebi ekran okusun diye ayrıntıdadır.
        raise HTTPException(status_code=409, detail=result.error.message)
    render = to_csv_bytes if ext == "csv" else to_xlsx_bytes
    return Response(
        content=render(result.columns, result.rows),
        media_type=MEDIA_TYPES[ext],
        headers={"Content-Disposition": f'attachment; filename="bilgin_{audit_id}.{ext}"'},
    )


def _dataset_block(session) -> dict:
    """Küme çipi: ad ve görünen ad; küme söylenmemişse ölçülen zaten config'in kümesidir."""
    ds = session.dataset
    if ds is None:
        return {"name": config.DEFAULT_DATASET, "display_name": config.DEFAULT_DATASET}
    return {"name": ds.name, "display_name": ds.display_name}


def _llm_block(session) -> dict:
    """Model çipi: uç noktanın adı ve adresi, yoklamanın cevabı ile birlikte (R5-1)."""
    reason = session.ping()
    if session.llm_kind == "fake":
        # Sahte modelin yoklanacak adresi yok: çip "burada model konuşmuyor" der.
        return {"kind": "fake", "model": "fake", "url": None, "reachable": reason is None, "reason": reason}
    profile = session.profile
    settings = config.llm_settings()
    return {
        "kind": session.llm_kind,
        "model": profile.model if profile else settings.model,
        "url": profile.base_url if profile else settings.base_url,
        "reachable": reason is None,
        "reason": reason,
    }


def _index_block(session) -> dict:
    """İndeks bu şema ve kurallarla yüklenebiliyor mu: yüklenemiyorsa sebep kullanıcının cümlesi."""
    ds = session.dataset
    try:
        load_search(session.index_dir, session.schema, session.rules, ds.name if ds else None)
    except (MissingIndexError, StaleIndexError) as exc:
        return {"fresh": False, "reason": str(exc), "embedder": None}
    return {"fresh": True, "reason": None, "embedder": cli._index_embedder(session.index_dir) or None}


def _rules_path(session) -> Path:
    """Kümenin kural dosyası: küme söylenmemişse config'in kuralı (R5-16)."""
    return session.dataset.rules_path if session.dataset else config.RULES_PATH


def _find_rule(session, rule_id: str) -> dict:
    """Kimliğiyle kuralı bulur; yoksa ekranın okuyacağı 404 (R5-16)."""
    for rule in session.rules:
        if rule.get("id") == rule_id:
            return rule
    raise HTTPException(status_code=404, detail=NO_RULE.format(id=rule_id))


def _check_rule(session, rule: dict, editing_id: str | None = None) -> None:
    """Doğrulama hataları 422 olarak alanların hepsiyle birlikte yükselir (R5-16)."""
    errors = validate_rule(rule, session.schema, session.rules, editing_id=editing_id)
    if errors:
        raise RuleRejected(errors)


def _write_rules(session, rules: list[dict]) -> dict:
    """Kuralları diske yazar, oturumu tazeler ve cevabı tazelikle birlikte döndürür (R5-16).

    Kurallar değiştiği için imza kayar: indeks bayatlar, ekran ``indeksi yeniden kur``u önerir.
    """
    save_rules(rules, _rules_path(session))
    session.reload_rules()
    return {"rules": session.rules, "index": _index_block(session)}


def _index_counts(session) -> dict:
    """Yeni meta.json'daki koleksiyon sayıları; okunamazsa boş, ekran 0 gösterir (R5-16)."""
    try:
        meta = json.loads((session.index_dir / META_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return meta.get("counts") or {}


def _mode_block(session) -> dict:
    """auto'nun eşiği ve tam kurallı istemin bağlam tahmini - ``resolve_auto``nun ölçütüyle aynı."""
    limit = cli._auto_limit(session.profile)
    as_of = session.dataset.as_of if session.dataset else config.AS_OF
    return {
        "default": "auto",
        "auto_full_max_tokens": config.AUTO_FULL_MAX_TOKENS if limit is None else limit,
        "estimate": doc.estimate_tokens(prompt.full_rules_prompt(as_of, session.schema, session.rules)),
    }
