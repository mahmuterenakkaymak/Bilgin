"""Web API'si: tek kullanıcılık FastAPI uygulaması (PLAN R5-15).

Yolların ardında ikinci bir hesap kitap yok: ``/api/ask`` ``ask_payload``ı çağırır, yani ekran ile
``ask --json`` aynı cevabı görür. Uygulama kimlik doğrulaması olmadığı için yalnız 127.0.0.1'e
bağlanır (``serve`` söyler), arayüz derlenmemişse API yine çalışır - ``/`` o zaman neyin eksik
olduğunu kendi cümlesiyle söyler, node'a muhtaç kalmaz.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nl2sql import config
from nl2sql.agent import prompt
from nl2sql.app import asklog
from nl2sql.app.ask import ask_payload, down_payload, replay_payload
from nl2sql.app.conversations import ConversationNotFound, ConversationStore
from nl2sql.app.session import open_session
from nl2sql.cli import main as cli
from nl2sql.engine.connections import ConnectionStore
from nl2sql.engine.dbstatus import looks_like_connection_error
from nl2sql.engine.result import Budget
from nl2sql.eval import runner
from nl2sql.index.search import load_search
from nl2sql.index.store import META_FILE, MissingIndexError, StaleIndexError, content_hash
from nl2sql.report.export import MEDIA_TYPES, to_csv_bytes, to_xlsx_bytes
from nl2sql.schema_map import doc
from nl2sql.schema_map.rules_edit import normalize_rule, save_rules, validate_rule
from nl2sql.start.cards import StartCache
from nl2sql.start.ready import ReadyStore
from nl2sql.start.suggest import SuggestJobs
from nl2sql.web.auth_api import create_router as create_auth_router
from nl2sql.web.auth_api import create_users_router
from nl2sql.web.authz import NO_SESSION, ROUTE_ROLES, current_user, require
from nl2sql.web.connections_api import create_router as create_connections_router
from nl2sql.web.conversations_api import NO_CONVERSATION
from nl2sql.web.conversations_api import create_router as create_conversations_router
from nl2sql.web.datasets_api import create_router as create_datasets_router
from nl2sql.web.map_api import create_router as create_map_router
from nl2sql.web.saved import ALL as SAVED_ALL, SavedStore
from nl2sql.web.start_api import SessionExecutor
from nl2sql.web.start_api import create_router as create_start_router

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
# R7-25: kırmızı çipin yöneticiyi götürdüğü yer, yani bağlantıların düzenlendiği ekran (R7-27).
CONNECTIONS_URL = "#/baglantilar"

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
    """``POST /api/ask`` gövdesi (Contracts): soru zorunlu, mod, seçim ve konuşma sorulabilir.

    ``conversation_id`` verilmezse soru yeni bir konuşma açar, verilmişse o konuşmanın sıradaki
    turudur (R7-8, Contracts "ask body (ext.)").
    """

    question: str = ""
    mode: str | None = None
    choice: str | None = None
    conversation_id: str | None = None


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


def create_app(
    session,
    saved_path: str | Path = config.APP_DB_PATH,
    static_dir: str | Path = config.STATIC_DIR,
    users=None,
    connections: ConnectionStore | None = None,
    dbstatus=None,
) -> FastAPI:
    """Oturumun üstünde API: soru, sağlık, örnekler, tablolar, kayıtlar, dışa aktarım ve arayüz.

    ``users`` bir ``UserStore`` ise kimlik doğrulama açıktır; ``None`` Run 5'in tek kullanıcısıdır
    - hiçbir yol çevrilmez, oturumun kullanıcısı ``None``dır (R6-5).

    R6-10: oturum burada bir daha anılmaz - her yol onu ``app.state``ten kendi okur, yani bir küme
    geçişi hiçbir yolu yeniden kurmaz; kayıtlar ve dışa aktarım da süzgecini aynı yerden alır.

    R7-8: her ``/api/ask`` bir konuşmanın turudur - depo ``users``tan bağımsızdır, yani tek
    kullanıcılı modda da konuşma vardır; tek fark sahibinin adıdır, o da NULL kalır.

    R7-25: ``connections`` ve ``dbstatus`` ``serve``in kurduklarıdır - oturumla aynı depoyu paylaşan
    bir bağlantı listesi ve arka planda ``SELECT 1`` atan denetleyici. ``dbstatus`` verilmediği
    dünyada (test, model olmadan koşan inceleme) sorulacak bir sunucu yoktur: çip ``none``dır.
    """
    app = FastAPI(title="Bilgin")
    app.state.session = session
    # R6-10: geçiş tek bir atamadır; kilit, iki geçişin birbirinin üstüne yazmasını engeller.
    app.state.session_lock = threading.Lock()
    app.state.saved_path = Path(saved_path)
    app.state.users = users
    # R7-23: bağlantılar kullanıcıların ve kayıtların kendi dosyasındadır; her oturum kurulumu bu
    # depoyu sorar, yani ekrandan kaydedilen bağlantı sunucuyu yeniden başlatmadan geçerli olur.
    app.state.connections = (
        connections if connections is not None else ConnectionStore(saved_path)
    )
    # R7-25: durumun bekçisi; hiçbir istek onun yoluna girmez, yalnız son cevabı okunur.
    app.state.dbstatus = dbstatus
    saved = SavedStore(saved_path)
    # R7-8: konuşmalar kayıtlarla aynı SQLite dosyasında; yollar depoyu app.state'ten okur.
    app.state.conversations = ConversationStore(saved_path)
    # R7-17: hazır sorular da aynı dosyada. Kart önbelleği uygulamanın üstünde yaşar - TTL'i ve
    # tek uçuş kilidi uygulama kadar ömürlü olmalı - ama yürütücüyü her yürüyüşte o anki oturumdan
    # okur, yani bir küme geçişinden (R6-10) sonra kartlar eski veritabanında koşmaz.
    app.state.ready = ReadyStore(saved_path)
    app.state.start_cache = StartCache(SessionExecutor(app))
    # R7-20: öneri işi kendi oturumunu kendi kurar - öneri koşarken uygulamanın etkin kümesi
    # değişebilir, iş o geçişin üstüne yazmamalı.
    app.state.suggest = SuggestJobs(app.state.ready, _suggest_opener(app))
    static = Path(static_dir)

    @app.exception_handler(RuleRejected)
    async def rule_rejected(request, exc: RuleRejected):
        """Alan hataları 422 olarak üst düzey ``errors`` anahtarıyla döner (R5-15)."""
        return JSONResponse(status_code=422, content={"errors": exc.errors})

    app.include_router(create_auth_router())
    app.include_router(create_users_router())
    app.include_router(create_conversations_router())
    app.include_router(create_datasets_router())
    app.include_router(create_connections_router())
    app.include_router(create_map_router())
    app.include_router(create_start_router())

    def guarded(method: str, path: str, **kwargs):
        """Yolun kapısını ``ROUTE_ROLES``tan okuyan süsleyici (R6-5, R6-6).

        Matriste public yazmayan her yol oturum ister; matriste hiç olmayan bir yol da ister,
        yani yeni bir yol unutulursa açık değil kapalı doğar. Seviye de matristen okunur: admin
        satırı yönetici ister, kullanıcı satırı oturum - kapının bildiği üçüncü bir seviye yok.
        """
        level = ROUTE_ROLES.get((method, path), "user")
        deps = [] if level == "public" else [Depends(require(level))]
        return getattr(app, method.lower())(path, dependencies=deps, **kwargs)

    @guarded("POST", "/api/ask")
    def ask(body: AskBody, request: Request) -> dict:
        """Sorunun cevabı: CLI ile birebir aynı payload, kaynağı ``web`` (R5-1).

        Soruyu soran kişinin adı soru günlüğünün satırına ve denetim satırlarının başına karışır
        (R6-9); tek kullanıcılı modda ad yoktur, yani Run 5'in hâli sürer.

        Her soru konuşma deposuna da bir turdur (R7-8): ``conversation_id`` yoksa konuşma yeni
        açılır, payload ve günlük satırı ``conversation_id`` ile ``turn``i taşır. Olmayan ya da
        başkasının konuşması soru sayılmaz - cümle ``ConversationNotFound``ın kendi cümlesi.

        Etkin kümenin veritabanı düşmüşse soru hiç koşmaz: cevabın yerini arızanın cümlesi alır
        (``down_payload``, R7-25). Yoklama yalnız arka planda koşar, yani istek beklemez; bir
        sorgunun bağlantı hatasına benzeyen hatası da bekçiyi bekletmez. Düşmüşkü de bir konuşmanın
        turudur: ``conversation_id`` yoksa konuşmayı o soru açar, varsa sıradaki tur arızanın
        cümlesiyle yazılır - yani ekranın adresi yokluktan doğar, numara boşluksuz sürer.
        """
        question = body.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail=BLANK_QUESTION)
        status = getattr(request.app.state, "dbstatus", None)
        try:
            if status is not None and status.state(_dataset_name(request))["state"] == "down":
                # R7-25: veritabanı cevap vermiyor - koşacak bir yer yok, yani model de koşmaz.
                # Soru yine de konuşmanın turudur (R7-8): ekran adresi açacak, numarayı sürecek.
                return down_payload(_session(request), question, mode=body.mode, choice=body.choice,
                                    source="web", username=_asker(request),
                                    conversations=request.app.state.conversations,
                                    conversation_id=body.conversation_id)
            payload = ask_payload(_session(request), question, mode=body.mode, choice=body.choice,
                                  source="web", username=_asker(request),
                                  conversations=request.app.state.conversations,
                                  conversation_id=body.conversation_id)
        except ConversationNotFound:
            raise HTTPException(status_code=404, detail=NO_CONVERSATION) from None
        if status is not None:
            _kick_on_connection_error(status, payload)
        return payload

    @guarded("POST", "/api/replay/{audit_id}")
    def replay(audit_id: str, request: Request) -> dict:
        """Geçmişteki bir soru: kayıtlı SQL modelsiz yeniden çalışır, payload /api/ask ile aynı biçimde.

        R6-9: başkasının sorusu bu yol için hiç yoktur, yani cevabı yokluğu anlatan bir payload
        değil, dışa aktarımınkiyle aynı cümle ve durumda bir 404.
        """
        # ASSUMPTION: süzgeç ile ad ayrıdır: yönetici başkasının kaydını da görür (süzgeç herkese
        # açık), ama yeniden sorduğunda satırı ve denetim satırları kendi adını taşır (R6-9).
        payload = replay_payload(_session(request), audit_id, source="web", username=_asker(request),
                                 scope=_scope(request, asklog._ALL))
        if (payload["error"] or {}).get("kind") == "not_found":
            raise HTTPException(status_code=404, detail=NO_ASK)
        return payload

    @guarded("GET", "/api/health")
    def health(request: Request) -> dict:
        """Başlığın çipleri: hangi küme ve veritabanı sağ mı, model sağ mı, indeks taze mi, auto eşiği ne."""
        session = _session(request)
        return {
            "status": "ok",
            "dataset": _dataset_block(session),
            "db": _db_block(request),
            "llm": _llm_block(session),
            "index": _index_block(session),
            "schema_hash": content_hash(session.schema, []),
            "rules_hash": content_hash({}, session.rules),
            "mode": _mode_block(session),
            "budget": session.budget,
        }

    @guarded("GET", "/api/examples")
    def examples(request: Request) -> dict:
        """Boş ekrandaki çipler: altın soruların ilki, yani gerçekten cevaplanabilenler."""
        session = _session(request)
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

    @guarded("GET", "/api/tables")
    def tables(request: Request) -> dict:
        """Kural formunun tablo listesi: ölçülen şemanın adları, sırasıyla."""
        return {"tables": [table["name"] for table in _session(request).schema["tables"]]}

    @guarded("GET", "/api/rules")
    def rules_list(request: Request) -> dict:
        """Kural ekranı: kümenin kuralları ve indeksin tazeliği (R5-16)."""
        session = _session(request)
        return {"rules": session.rules, "index": _index_block(session)}

    @guarded("POST", "/api/rules")
    def rules_add(rule: dict, request: Request) -> dict:
        """Yeni kural: çakışan kimlik 409, doğrulama hatası 422, sonra disk ve oturum tazelenir."""
        session = _session(request)
        rid = str(rule.get("id", "")).strip()
        if any(existing.get("id") == rid for existing in session.rules):
            raise HTTPException(
                status_code=409, detail=[{"field": "id", "message": DUPLICATE_RULE.format(id=rid)}]
            )
        _check_rule(session, rule)
        return _write_rules(session, session.rules + [normalize_rule(rule)])

    @guarded("PUT", "/api/rules/{rule_id}")
    def rules_update(rule_id: str, rule: dict, request: Request) -> dict:
        """Kimliğiyle bulunan kuralı gövdeyle değiştirir; olmayan kimlik 404 (R5-16)."""
        session = _session(request)
        _find_rule(session, rule_id)
        rule = {**rule, "id": rule_id}
        _check_rule(session, rule, editing_id=rule_id)
        return _write_rules(session, [
            normalize_rule(rule) if existing.get("id") == rule_id else existing
            for existing in session.rules
        ])

    @guarded("DELETE", "/api/rules/{rule_id}")
    def rules_delete(rule_id: str, request: Request) -> dict:
        """Kuralı hem diskten hem oturumdan çıkarır; olmayan kimlik 404 (R5-16)."""
        session = _session(request)
        _find_rule(session, rule_id)
        return _write_rules(session, [r for r in session.rules if r.get("id") != rule_id])

    @guarded("POST", "/api/index/rebuild")
    def index_rebuild(request: Request) -> dict:
        """İndeksi mevcut kurallarla yeniden kurar; bayatlık ancak böyle kalkar (R5-16).

        Embedder mevcut indeksin meta'sından alınır, yani aynı vektör uzayı korunur; indeks hiç
        yoksa ``--llm fake`` sahte uzayı, aksi halde OpenAI uyumlu uç noktayı kullanır.
        """
        session = _session(request)
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

    @guarded("GET", "/api/saved")
    def saved_list(request: Request) -> dict:
        """Kenar çubuğu: bu kümenin ve bu kullanıcının kayıtlı soruları, en yeni önce (R5-16, R6-9)."""
        return {"saved": saved.list(_dataset_name(request), username=_scope(request, SAVED_ALL))}

    @guarded("POST", "/api/saved")
    def saved_add(body: SavedBody, request: Request) -> dict:
        """Soruyu kenar çubuğuna eklemek: saklanan cevabı değil, sorunun metni ve SQL'i."""
        question = body.question.strip()
        if not question:
            raise HTTPException(status_code=400, detail=BLANK_QUESTION)
        # ASSUMPTION: POST tek kaydın kendisini döndürür; ekran istersen listeyi yeniden çeker.
        return {
            "saved": saved.add(
                question, mode=body.mode, sql=body.sql, dataset=_dataset_name(request),
                username=_asker(request),
            )
        }

    @guarded("DELETE", "/api/saved/{id}")
    def saved_delete(id: int, request: Request) -> dict:
        """Kaydı kenar çubuğundan çıkarır; olmayan ya da başkasının kaydının silinecek bir şeyi yok (404)."""
        if not saved.delete(id, username=_scope(request, SAVED_ALL)):
            raise HTTPException(status_code=404, detail=NO_SAVED)
        return {"deleted": id}

    @guarded("GET", "/api/history")
    def history(request: Request) -> dict:
        """Son sorular: soru günlüğünün satırları, en yeni önce; veri satırları asla (R5-4).

        R6-9: kullanıcı kendi sorularını görür, yönetici kümenin hepsini - adı olmayan eski
        satırlar da yalnız yöneticide görünür.

        R7-8: konuşmayla koşan satır turunu taşır; konuşma alanı olmayan eski satırlarda iki alan
        da None'dır, yani ekranın okuduğu küme hiç değişmez (Contracts "history item (ext.)").
        """
        session = _session(request)
        name = getattr(getattr(session, "dataset", None), "name", None)
        items = asklog.history(session.ask_log, dataset=name, username=_scope(request, asklog._ALL))
        for item in items:
            item.setdefault("conversation_id", None)
            item.setdefault("turn", None)
        return {"history": items}

    @guarded("GET", "/api/export/{audit_id}.csv")
    def export_csv(audit_id: str, request: Request) -> Response:
        """Cevabın tamamı CSV: ``bilgin_<id>.csv`` adı ile iner (R5-16)."""
        return _export(
            _session(request), _dataset_name(request), audit_id, "csv", _scope(request, asklog._ALL)
        )

    @guarded("GET", "/api/export/{audit_id}.xlsx")
    def export_xlsx(audit_id: str, request: Request) -> Response:
        """Cevabın tamamı Excel: sayı hücreleri sayı olarak kalır (R5-16)."""
        return _export(
            _session(request), _dataset_name(request), audit_id, "xlsx", _scope(request, asklog._ALL)
        )

    assets = static / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    def page() -> Response:
        """Derlenmiş arayüz varsa o, yoksa neyin eksik olduğunu söyleyen sayfa (200)."""
        built = static / "index.html"
        if built.is_file():
            # The page names the hashed bundle; a cached copy keeps loading the old one after a rebuild
            # (2026-10-25). The hashed /assets files themselves can stay cached.
            return FileResponse(built, media_type="text/html", headers={"Cache-Control": "no-cache"})
        return HTMLResponse(NO_UI_PAGE)

    @guarded("GET", "/", response_class=HTMLResponse)
    def index() -> Response:
        return page()

    # ASSUMPTION: fallback tek bir yol değil, ROUTE_ROLES'ta satırı yok - sayfa publictir, kapı
    # yalnız /api altında kendiliğinden kurulur (M19 matris testi bu yolu public saymalı).
    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str, request: Request) -> Response:
        """R6-6: adres çubuğuna yazılan derin bağlantı 404 olmaz, kararı arayüz verir.

        Sayfa publictir; ``api`` ve ``assets`` altı sayfa değildir - bilinmeyen bir API yolu JSON
        olarak reddedilir (depo varken oturum yoksa 401, varsa 404), bir asset ise uydurulmaz.
        """
        head = path.partition("/")[0]
        if head == "api":
            if request.app.state.users is not None and current_user(request) is None:
                raise HTTPException(status_code=401, detail=NO_SESSION)
            raise HTTPException(status_code=404)
        if head == "assets":
            raise HTTPException(status_code=404)
        return page()

    return app


def _suggest_opener(app):
    """Öneri işinin oturum kurucusu (R7-20): aynı model ve günlükler, başka bir dünyanın üstünde.

    Alanlar ``datasets_api``nin küme geçişiyle aynıdır - öneri dünyayı değiştirir, sunduğu modeli
    değiştirmez. Oturum iş çağrıldığı anki oturumdan okunur, yani bir geçişten sonrakini taşır.
    """

    def open_for(name: str):
        current = app.state.session
        return open_session(
            dataset=name,
            model=current.profile.name if current.profile else None,
            llm=current.llm_kind,
            models_file=current.models_file,
            audit_path=current.audit_path,
            ask_log=current.ask_log,
            connections=app.state.connections,
        )

    return open_for


def _session(request: Request):
    """Yolun oturumu: her istekte ``app.state``ten okunur (R6-10).

    Kapanışa yakalansaydı bir küme geçişinden sonra ekran eskisini göstermeye devam ederdi;
    geçişin kendisi de yalnız alanı değiştirir, hiçbir yol yeniden kurulmaz.
    """
    return request.app.state.session


def _dataset_name(request: Request) -> str:
    """Kayıt ve dışa aktarım süzgecinin kümesi: oturumun o anki kümesinin adı (R5-16, R6-10)."""
    return _dataset_block(_session(request))["name"]


def _asker(request: Request) -> str | None:
    """Yeni kaydın sahibi: kapının çözdüğü kullanıcı; tek kullanıcılı modda ad yoktur (R6-9)."""
    user = current_user(request)
    return user["username"] if user else None


def _scope(request: Request, everyone):
    """Bu çağrının görebildiği kayıtların süzgeci: arayanın adı, ya da ``everyone`` (R6-9).

    Yönetici kümenin her kaydını görür, tek kullanıcılı mod (Run 5) hepsini: ikisinde de süzgeç
    kapının ``ALL``ıdır, yani adı hiç olmayan eski satırlar da ancak böyle görünür.
    """
    user = current_user(request)
    if user is None or user["role"] == "admin":
        return everyone
    return user["username"]


def _kick_on_connection_error(status, payload: dict) -> None:
    """Bağlantı hatasına benzeyen bir yürütme hatası bekçiyi bekletmez (R7-25).

    Nokta kendi turunda yenilenirdi; kullanıcı yeniden sormadan kırmızıya dönmez. Sözdizimi ya da
    politika hatası ise sunucunun ulaşılabildiğini zaten söyler, yani bekçiyi uyandırmaz.
    Sürücünün ham cümlesi kataloğun yerine okuduğu ``message``da değil ``detail``ındadır (R8-3):
    burada koklanan teknik metin, ekranda okunan cümle değil.
    """
    error = payload.get("error") or {}
    if str(error.get("kind", "")).startswith("exec:") and looks_like_connection_error(
        error.get("detail") or error.get("message")
    ):
        status.kick()


def _export(session, dataset: str, audit_id: str, ext: str, username) -> Response:
    """Günlükteki SQL'i dışa aktarım bütçesiyle bir kez daha koşar ve dosyayı hazırlar (R5-16).

    Satırlar yürütücünün döndürdükleridir: PII maskesi bu yürüyüşte de üstlerinden geçer, yani
    indirme ekranın gösterdiğinden fazlasını asla vermez. Denetim satırı ``export:<id>`` kaynağını
    taşır, böylece hangi indirmenin hangi sorguyu koştuğu soru günlüğüyle birleşir (R5-4).

    ``username`` arayanın süzgecidir (R6-9): başkasının kaydı bu arama için yoktur, yani indirme
    bilinmeyen bir kaydınkiyle aynı cümleyi alır - 404, 403 değil.
    """
    record = asklog.find_ask(audit_id, session.ask_log, username=username)
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


def _db_block(request: Request) -> dict:
    """Veritabanı çipi (R7-25): arka plan yoklamasının son cevabı, Contracts "health db".

    Okuma hiçbir zaman sunucuya sormaz - bekleyen bir ``SELECT 1``in yerinde olsa çip beklerdi.
    Kullanıcının okuduğu tek cümle geneldir; yönetici sürücünün kendi cümlesini ve bağlantıyı
    düzenlediği ekranın adresini de alır, çünkü "neden"i düzeltecek olan odur.
    """
    status = getattr(request.app.state, "dbstatus", None)
    answer = status.state(_dataset_name(request)) if status is not None else {}
    block = {
        "state": answer.get("state", "none"),
        "checked_at": answer.get("checked_at"),
        "message": answer.get("message"),
    }
    # Tek kullanıcılı modda (Run 5) kapının tanıdığı tek kişi yöneticidir - ``_scope`` da böyle sayar.
    user = current_user(request)
    if user is None or user["role"] == "admin":
        block["message_admin"] = answer.get("message_admin")
        block["connections_url"] = CONNECTIONS_URL
    return block


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
