"""Komut satırı: veritabanını kur, indeksi kur, bir Excel haritasını şemaya eşle, veritabanını yokla, geri çağırmayı ölç, tek bir soru sor, altın soruları koş.

Komutlar aynı parçaları kullanır ve hiçbir yola sahip çıkmaz: SQLite dosyası, audit kaydı,
rapor klasörü ve indeks klasörü parametredir, varsayılanı config'den gelir, testler kendi tmp
yolunu verir. ``ask``
koşuyu adım adım dökerek ekrana yazdırır (Delight 6), ``eval`` raporu yazıp skoru söyler; skor veri
olduğu için çıkış koduna geçmez, yalnız cevap gönderilmeyen bir soru 1 döner. Kullanıcının
düzeltebileceği arıza iz dökümüyle değil tek cümleyle çıkar (Delight 3): veritabanı dosyası
yoksa kod 2 ve "önce kur", verilecek dosya ya da eşleme okunamıyorsa kod 2 ve neyin okunamadığı,
uç nokta ya da embedding sunucusu hiç çalışmıyorsa kod 3 ve hangi adresin patladığı.
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

from openpyxl.utils.exceptions import InvalidFileException

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.agent.llm import ChatResponse, OpenAIClient
from nl2sql.agent.loop import AgentRun, Step, run_agent
from nl2sql.agent.modes import MODES, ToolContext, get_mode
from nl2sql.cli.table import format_table
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.eval import report, retrieval, runner
from nl2sql.eval.compare_modes import REUSED_NOTE, build_compare, reusable, write_compare
from nl2sql.eval.runner import _tokens
from nl2sql.graph.graph import build_graph
from nl2sql.graph.profile import load_profile
from nl2sql.index.docs import COLLECTIONS, build_documents
from nl2sql.index.embed import EmbedError, make_embedder
from nl2sql.index.search import build_search, load_search
from nl2sql.index.store import (
    META_FILE,
    FileStore,
    MissingIndexError,
    StaleIndexError,
    content_hash,
)
from nl2sql.schema_map import build, doc, excel, introspect, merge
from nl2sql.schema_map.rules import load_rules

LLMS = ("fake", "openai")
# ASSUMPTION: ölçüm aracının varsayılanı gerçek endpoint'tir; --llm fake model istemeyen ölçüm
# yolu olduğu için kendisi söylenerek seçilir.
DEFAULT_LLM = "openai"
EMBEDS = ("fake", "openai")
# ASSUMPTION: indeksin varsayılanı da gerçek embedding sunucusudur; --embed fake aramanın
# davranışını model olmadan ölçmek isteyen yol olduğu için kendisi söylenerek seçilir.
DEFAULT_EMBED = "openai"

AUDIT_SOURCE = "ask"
PROSE = "yanıt"
SQL_TOOLS = ("run_sql", "submit_sql")
NO_ANSWER = "Cevap gönderilmedi: {}"

# R2-14: arama araçlarının cevabı modele gider, ekrana değil; adımda kaç birim döndüğü ve
# uyarısı durur. Araç adının sığacağı genişlik de modların araç listesinden gelir.
TOOL_WIDTH = max(len(tool["function"]["name"]) for mode in MODES.values() for tool in mode.tools)
# Gerçek bir arama sonucu: "TABLO — ..." ya da çıplak "TABLO". Cümleler ("Eşleşen tablo yok.",
# "Hata: ...") eşleşmez; adları onların ilk sözcüğünden çıkarmak uydurma ad üretirdi (R2-14).
SCHEMA_HIT = re.compile(r"([A-Z][A-Z0-9_]*)(?: — .*)?$")
DETAIL_HEAD = re.compile(r"^[A-Z][A-Z0-9_]* — ", re.MULTILINE)  # detay bloğunun başlık satırı
JOIN_LINE = re.compile(r"\S+ = ")  # bir join satırı: A.X = B.Y (fk 1.0)
WARNING_MARK = "⚠"
VALUE_COUNT = re.compile(r"Değerler \((\d+)\)")
RUNNING = "{mode} koşuluyor ..."
NO_INDEX_NOTE = "İndeks yok/eski; full modda çalışılıyor."

ENV_URL = "NL2SQL_LLM_BASE_URL"
EMBED_ENV_URL = "NL2SQL_EMBED_BASE_URL"
NO_DB = "Veritabanı yok: {path}\nÖnce `python -m nl2sql build-db` çalıştırın."
NO_TAG = "Bu etiketle soru yok: {tag}"
LLM_HINT = f"Öneri: Strata'nın açık olup olmadığına bakın; adres farklıysa {ENV_URL} ile doğruyu verin."
EMBED_HINT = (
    f"Öneri: embedding sunucusunun açık olup olmadığına bakın; "
    f"adres farklıysa {EMBED_ENV_URL} ile doğruyu verin."
)
# ASSUMPTION: uç nokta hiçbir soruyu yanıtlamadıysa ortada ölçülen bir şey yoktur; koşu tamamlanmış
# sayılmaz (PLAN Decision 13'deki crash hali), o yüzden rapor yazılmadan kod 3 ile çıkılır.
EXIT_NO_DB = 2
EXIT_LLM = 3
# ASSUMPTION: ölü bir embedding sunucusu da aynı hali anlatır; indeks yazılmadan çıkılır (R2-14).
EXIT_EMBED = 3
# ASSUMPTION: rag'in indeksi yok ya da bayat; düzeltmesi kullanıcının elinde olan bir eksiklik,
# yani veritabanı gibi kod 2 (R2-9). Boş bir etiket seçimi de koşacak bir şey bırakmaz.
EXIT_NO_INDEX = 2
EXIT_NO_TAG = 2
# ASSUMPTION: verilecek dosyanın yokluğu da okunamayan eşleme de kullanıcının kendi düzelteceği bir
# eksikliktir, yani veritabanı gibi kod 2 (R3-13).
EXIT_BAD_INPUT = 2

# R3-13: import-map'ın iki sabit satırı; ilki model ile sözlüğün çeliştiğini, ikincisi dönüşümün
# ne yazdığını söyler. İkisi de kullanıcının denetleyeceği şeyi adıyla taşır.
DISAGREEMENT = "⚠ uyuşmuyor: {sheet}.{column} {field}: llm={llm} fallback={fallback}"
SCHEMA_WRITTEN = (
    "Şema yazıldı: {path} ({tables} tablo, {columns} kolon, {skipped} atlanan satır)"
)
SKELETON_WRITTEN = "İskelet: {tables} tablo, {columns} kolon -> {path}"
UNMAPPED = "hiçbir alan"
NONE = "-"
NO_FILE = "Excel dosyası yok: {path}"
BAD_MAPPING = "Eşleme dosyası okunamadı: {path}"
IMPORT_HINT = (
    "Devam: --accept ile şemayı yazdırın; "
    "eşlemeyi elle düzeltmek isterseniz --mapping ile geri verin."
)

# R3-13: diff-map'ın satırları — boş fark tek cümleyle, dolu fark bölüm bölüm sayıyla söylenir.
BAD_SCHEMA = "Şema dosyası okunamadı: {path}"
NO_DIFF = "Fark yok."

# R3-5: eval hangi şema dosyasıyla ölçtüğünü canlı satırlardan önce söyler (imzanın başı, yani iki
# koşunun aynı şemayı ölçüp ölçmediği ekrandan okunur); merge-map birleşik şemanın nereye yazıldığını.
SCHEMA_LINE = "Şema: {path} ({hash8})"
MERGED_WRITTEN = "Birleşik şema yazıldı: {path} ({tables} tablo, {columns} kolon)"


def build_database(
    seed: int = config.SEED,
    db_path: str = config.DB_PATH,
    sql_path: str = config.MSSQL_SCRIPT,
) -> int:
    """Sentetik veriyle SQLite dosyasını ve T-SQL kurulum betiğini üretir.

    Ekran ölçümün iki girdisini de söyler (R2-14): kaç tabloda gerçekten satır olduğu (distractor
    tabloların bir kısmı şemada öylece durur) ve ``full`` modun şema metninin bağlam maliyeti.
    """
    _utf8_stdout()
    digest = build.build_db(seed, db_path, sql_path)
    print(f"Tohum: {seed}")
    print(f"Veritabanı: {db_path}")
    print(f"T-SQL betiği: {sql_path}")
    toplam, dolu = _table_counts(db_path)
    print(f"Tablolar: {toplam} (veri {dolu}, şema-yalnız {toplam - dolu})")
    schema_text = doc.full_text(doc.load_schema())
    print(f"Şema metni (full mod): {len(schema_text)} karakter ≈ {doc.estimate_tokens(schema_text)} token")
    print(f"Sağlama (sha256): {digest[:12]}")
    return 0


def build_index(
    embed: str = DEFAULT_EMBED,
    index_dir: str = config.INDEX_DIR,
    schema_path: str = config.SCHEMA_PATH,
    rules_path: str = config.RULES_PATH,
) -> int:
    """Şema ile kurallardan arama indeksini kurar: dokümanlar, vektörler, imza (R2-14).

    Ekran dört şeyi söyler: kaç doküman yazıldığı (koleksiyon koleksiyon), vektörlerin kimin ve
    kaç genişlikte olduğu, içeriğin imzasının başı ve ne kadar sürdü. İmza, ``ask`` tarafının bayat
    indeksi reddetmesinin kendisi olduğu için burada ekrana da çıkıyor.
    """
    _utf8_stdout()
    started = time.perf_counter()
    schema = doc.load_schema(schema_path)
    rules = load_rules(rules_path)
    docs = build_documents(schema, rules)
    embedder = make_embedder(embed)
    try:
        vectors = embedder.embed([item.text for item in docs])
    except EmbedError as exc:
        return _embed_failed(str(exc))
    seconds = time.perf_counter() - started
    digest = content_hash(schema, rules)
    FileStore(index_dir).save(
        docs,
        vectors,
        {"content_hash": digest, "embedder": embedder.id, "dim": embedder.dim},
    )
    print(f"Şema: {schema_path} ({len(schema['tables'])} tablo)")
    print(f"Kurallar: {rules_path} ({len(rules)} kural)")
    print(
        "Dokümanlar: "
        + ", ".join(
            f"{name} {sum(1 for item in docs if item.collection == name)}" for name in COLLECTIONS
        )
        + f" (toplam {len(docs)})"
    )
    print(f"Embedder: {embedder.id} (dim {embedder.dim})")
    print(f"İmza: {digest[:12]}")
    print(f"Süre: {seconds:.1f} sn")
    print(f"İndeks: {index_dir}")
    return 0


def eval_retrieval(
    embed: str = DEFAULT_EMBED,
    k: int = config.SEARCH_K,
    out_dir: str | Path = retrieval.RETRIEVAL_OUT,
    schema_path: str = config.SCHEMA_PATH,
    rules_path: str = config.RULES_PATH,
    golden_path: str = config.GOLDEN_PATH,
) -> int:
    """Aramanın geri çağırmasını altın sorular üzerinde ölçer ve raporu yazar (R2-14).

    İndeks bellekte kurulur (R2-9): ölçüm diskteki indekse ya da veritabanına bakmaz, temiz bir
    koşumda da çalışır. Ekran soru başına bir satır, metod ve etiket ortalamalarıdır; sayıların
    kendisi ``eval_out/retrieval`` altındaki raporda da durur.
    """
    _utf8_stdout()
    started = time.perf_counter()
    schema = doc.load_schema(schema_path)
    rules = load_rules(rules_path)
    try:
        search = build_search(schema, rules, make_embedder(embed))
    except EmbedError as exc:
        return _embed_failed(str(exc))
    result = retrieval.run_retrieval(search, runner.load_golden(golden_path), k)
    print()
    for line in retrieval.console_lines(result):
        print(line)
    print(f"\nSüre: {time.perf_counter() - started:.1f} sn")
    run_dir = retrieval.write_retrieval(result, out_dir)
    print(f"Rapor: {run_dir / 'report.md'}")
    return 0


def ask(
    question: str,
    llm,
    mode: str = "full",
    db_path: str = config.DB_PATH,
    audit_path: str = config.AUDIT_LOG,
    index_dir: str = config.INDEX_DIR,
) -> int:
    """Bir soru: modunu söyle, adımları işaretle ve gecikmesiyle dök, gönderilen SQL'i ve tabloyu göster.

    ``llm`` hazır bir istemcidir; ``mode`` hangi araçların konuşacağını ve bağlamın nereden
    geleceğini söyler (rag indeksi ister, R2-9). Tablo için gönderilen SQL bir kez daha yürütülür,
    çünkü döngü yanıtı metin olarak görür, satırları ekrana basacak biçimde elinde tutmaz.
    """
    _utf8_stdout()
    if _db_missing(db_path):
        return _no_db(db_path)
    schema = doc.load_schema()
    executor = LocalExecutor(db_path=db_path, audit_path=audit_path)
    try:
        context = _context(mode, executor, schema, load_rules(), index_dir)
    except (MissingIndexError, StaleIndexError) as exc:
        return _index_failed(str(exc))
    run = run_agent(question, llm, executor, schema, AUDIT_SOURCE, mode=mode, context=context)

    print(f"Mod: {mode}")
    print(f"Soru: {question}\n")
    if run.steps:  # daha ilk turda düşen bir uç noktanın gösterecek adımı yok
        print("Adımlar:")
        for step in run.steps:
            for line in _step_lines(step):
                print(line)
        print()
    if run.status == "llm_error":
        return _llm_failed(run.stop_reason)
    if not run.submitted_sql:
        print(NO_ANSWER.format(run.stop_reason or "submit_sql hiç çağrılmadı."))
        _cost(run)
        return 1

    print("Cevap SQL:")
    print(run.submitted_sql)
    print("\nSonuç:")
    print(format_table(executor.execute(run.submitted_sql, Budget(), AUDIT_SOURCE)))
    print()
    _cost(run)
    return 0


def evaluate(
    llm,
    only: list[str] | None = None,
    tags: list[str] | None = None,
    mode: str = config.DEFAULT_EVAL_MODE,
    db_path: str = config.DB_PATH,
    audit_path: str = config.AUDIT_LOG,
    out_dir: str = config.EVAL_OUT,
    index_dir: str = config.INDEX_DIR,
    schema_path: str | Path = config.SCHEMA_PATH,
) -> int:
    """Altın soruları bir modda koşar, her soru biter bitmez tek satır dökerek (Delight 4)
    ilerler, raporu ``out_dir`` altına yazar (CLI ona ``eval_out/<mode>`` verir, R2-12), skoru söyler; koşu tamamlandıysa kod 0'dır.

    Mod yalnızca bir etiket değil, koşunun kendisi: ``full_rules`` kuralları bağlamdan ister,
    ``rag`` diskteki indeks ile join graphını yükler (R2-9: bayat indeks reddedilir, sessizce
    yeniden kurulmaz). Rapor modun kendi klasörüne gider ki fark iki farklı mod arasında
    kıyaslanmasın (R2-12); imza da o yüzden raporun içinde durur.

    ``schema_path`` de koşunun kendisini tanımlar (R3-5): allowlist, modelin gördüğü şema metni,
    join graphı ve indeks imzası hepsi okunan dosyadan gelir; yolu ve imzasının başı ekrana, yolu ve
    imzası rapora yazılır, böylece iki koşu ancak aynı şemayı ölçtüyse birbirinin devamı sayılır.
    """
    _utf8_stdout()
    if _db_missing(db_path):
        return _no_db(db_path)
    schema_file = _schema_file(schema_path)
    schema = _load_schema(schema_file)
    if schema is None:
        return EXIT_BAD_INPUT
    lines = runner.load_golden()
    absent = _absent_tags(lines, tags)
    if absent:
        for tag in absent:
            print(NO_TAG.format(tag=tag))
        return EXIT_NO_TAG

    info = report.schema_info(schema_file, schema)
    print(f"Mod: {mode}")
    print(SCHEMA_LINE.format(path=info["path"], hash8=info["hash"][:8]) + "\n")
    rules = load_rules()
    executor = LocalExecutor(
        db_path=db_path, allowlist=doc.allowlist(schema), audit_path=audit_path
    )
    try:
        context = _context(mode, executor, schema, rules, index_dir)
    except (MissingIndexError, StaleIndexError) as exc:
        return _index_failed(str(exc))

    results = runner.run_eval(
        lambda: llm,
        executor,
        golden=lines,
        only=only,
        schema=schema,
        mode=mode,
        tags=tags,
        context=context,
        on_progress=lambda result: print(runner.progress_line(result)),
    )
    if results and all(result.outcome == "llm_error" for result in results):
        print(f"Uç nokta {len(results)} sorunun hiçbirini yanıtlamadı; rapor yazılmadı.\n")
        return _llm_failed(results[0].reason)
    passed = sum(1 for result in results if result.outcome == "pass")
    kind = "fake" if isinstance(llm, fake.FakeLLM) else "openai"
    model = "fake" if kind == "fake" else config.llm_settings().model
    run_dir = report.write_report(
        results,
        out_dir,
        model=model,
        config={
            "backend": config.backend(),
            "llm": model,
            "embedder": _embedder_id(mode, index_dir),
            "fingerprint": _fingerprint(mode, kind, model, lines, results, schema, rules),
        },
        mode=mode,
        schema_info=info,
    )
    print(f"Skor: {passed}/{len(results)}")
    print(f"Rapor: {run_dir / 'report.md'}")
    return 0


def compare_modes(
    llm_factory,
    fresh: bool = False,
    db_path: str = config.DB_PATH,
    audit_path: str = config.AUDIT_LOG,
    out_dir: str = config.EVAL_OUT,
    index_dir: str = config.INDEX_DIR,
    schema_path: str | Path = config.SCHEMA_PATH,
) -> int:
    """Üç modu aynı sorularda koşar, tek karşılaştırma raporu yazar, mod başına tek satır söyler.

    ``llm_factory(mode)`` modun kendi kaydını oynatan istemciyi verir; ``fake`` mod başına farklı
    bir konuşma oynattığı için istemci burada üretilir. R2-12: bir modun ``<out>/<mode>/latest``i
    imzası ve (rag için) vektör uzayı bu koşununkiyle birebir eşitse yeniden koşulmaz ve satırı
    ``(önceki koşu)`` ile çıkar; ``fresh`` o kolaylığı bir kenara bırakır. Koşan mod raporunu
    kendi klasörüne yazar,
    karşılaştırma ``<out>/compare`` altına gider (R2-14).

    ``schema_path`` ``evaluate``ınkiyle aynı anlamı taşır (R3-5): üç mod da o dosyayla ölçer —
    allowlist, şema metni, join graphı, indeks imzası ve raporun ``schema`` alanı hepsi ondan
    gelir —, yani bir modun ``latest``i ancak aynı şemayla ölçmüşse yeniden kullanılabilir.
    """
    _utf8_stdout()
    if _db_missing(db_path):
        return _no_db(db_path)
    schema_file = _schema_file(schema_path)
    schema = _load_schema(schema_file)
    if schema is None:
        return EXIT_BAD_INPUT
    lines = runner.load_golden()
    info = report.schema_info(schema_file, schema)
    print(SCHEMA_LINE.format(path=info["path"], hash8=info["hash"][:8]) + "\n")
    rules = load_rules()
    executor = LocalExecutor(
        db_path=db_path, allowlist=doc.allowlist(schema), audit_path=audit_path
    )
    clients = {mode: llm_factory(mode) for mode in config.MODES}
    kind, model = _client_kind(clients[config.MODES[0]])
    fingerprints = {
        mode: _mode_fingerprint(mode, kind, model, lines, schema, rules) for mode in config.MODES
    }
    spaces = {mode: _embedder_id(mode, index_dir) for mode in config.MODES}
    stored = {mode: _mode_report(out_dir, mode) for mode in config.MODES}
    reused = {
        mode
        for mode in config.MODES
        if not fresh and reusable(stored[mode], fingerprints[mode], spaces[mode])
    }
    if "rag" not in reused:
        # rag koşacaksa indeksi baştan denetle; iki mod boşuna koşulduktan sonra red edilmesin.
        try:
            _context("rag", executor, schema, rules, index_dir)
        except (MissingIndexError, StaleIndexError) as exc:
            return _index_failed(str(exc))

    reports = {mode: stored[mode] for mode in reused}
    for mode in config.MODES:
        if mode in reports:
            continue
        print(RUNNING.format(mode=mode))
        results = runner.run_eval(
            lambda: clients[mode],
            executor,
            golden=lines,
            schema=schema,
            mode=mode,
            context=_context(mode, executor, schema, rules, index_dir),
        )
        if results and all(result.outcome == "llm_error" for result in results):
            print(f"Uç nokta {len(results)} sorunun hiçbirini yanıtlamadı; rapor yazılmadı.\n")
            return _llm_failed(results[0].reason)
        report.write_report(
            results,
            Path(out_dir) / mode,
            model=model,
            config={
                "backend": config.backend(),
                "llm": model,
                "embedder": spaces[mode],
                "fingerprint": fingerprints[mode],
            },
            mode=mode,
            schema_info=info,
        )
        reports[mode] = _mode_report(out_dir, mode)

    comparison = build_compare(reports, doc.estimate_tokens(doc.full_text(schema)), reused)
    run_dir = write_compare(comparison, Path(out_dir) / "compare")
    print()
    for mode in config.MODES:
        print(_compare_line(mode, comparison["modes"][mode]))
    print(f"\n{comparison['verdict']['line']}")
    print(f"Rapor: {run_dir / 'report.md'}")
    return 0


def import_map(
    path: str | Path,
    llm_factory,
    accept: bool = False,
    mapping: str | Path | None = None,
    proposal_path: str | Path | None = None,
    out: str | Path = config.IMPORTED_PATH,
) -> int:
    """Excel haritasının eşlemesini önerir, diske yazar; ``--accept`` ile şemaya dönüştürür (R3-2).

    Model eşlemeyi önerir ama satırları hiç görmez: dönüşümü tüm çalışma kitabına koddan
    ``convert`` uygular. Modelin sözlükle çeliştiği sütun sessizce çözülmez, ekrana uyuşmazlık
    olarak çıkar; eşleme diskte kaldığı için kullanıcı elle düzeltip ``--mapping`` ile geri verir
    ve o yolda model bir daha aranmaz.
    """
    _utf8_stdout()
    source = Path(path)
    if not source.is_file():
        print(NO_FILE.format(path=path))
        return EXIT_BAD_INPUT
    try:
        preview = excel.read_workbook(source)
    # ASSUMPTION: openpyxl'in cümlesi verilen biçimi ve desteklenenleri sayar ama dosyayı saymaz;
    # kullanıcının neyi düzelteceği tek satırda anlaşılsın diye yolu da buraya ekliyoruz.
    except (OSError, zipfile.BadZipFile, excel.SheetError, InvalidFileException) as exc:
        print(f"Hata: {source}: {exc}")
        return EXIT_BAD_INPUT

    proposal = mapping or _proposal_file(source, proposal_path)
    if mapping:
        chosen = _read_mapping(mapping)
        if chosen is None:
            return EXIT_BAD_INPUT
        by = "dosya"
    else:
        chosen = excel.propose(preview, llm_factory(preview))
        _write_json(proposal, chosen)
        by = str(chosen["generated_by"])

    print(f"Dosya: {source}")
    for line in _mapping_lines(chosen):
        print(line)
    for note in chosen.get("disagreements") or []:
        print(DISAGREEMENT.format(**{key: value or NONE for key, value in note.items()}))
    print(f"\nEşleme: {proposal} ({by})")

    if not accept:
        print(IMPORT_HINT)
        return 0
    report = excel.convert(source, chosen)
    _write_json(out, report["schema"])
    print(
        "\n"
        + SCHEMA_WRITTEN.format(
            path=out,
            tables=report["tables"],
            columns=report["columns"],
            skipped=len(report["skipped"]),
        )
    )
    for note in report["skipped"]:
        print(f"     ↳ {note['sheet']}.satır {note['row']}: {note['reason']}")
    return 0


def introspect_schema(
    out: str | Path = config.SKELETON_PATH,
    sample: bool = False,
    db_path: str | Path = config.DB_PATH,
    audit_path: str | Path = config.AUDIT_LOG,
) -> int:
    """Veritabanını yoklayıp iskelet şemayı yazar; ``--sample`` kısa metin kolonlarına değer ipucu ekler (R3-4).

    İpucu yoksa iskelet yalnız yapı taşır: ad, tip, nullability ve fk. Anlamı Excel haritası sonra
    ekler (R3-5), o yüzden burada boş açıklamalar bir eksik değil. ``--sample``ın sorguları da
    LocalExecutor'dan geçer, yani politika ve denetim kaydı model sorgularıyla aynı kapıdan yürür.
    """
    _utf8_stdout()
    if config.backend() == "mssql":
        try:
            skeleton = introspect.mssql_skeleton()
        except introspect.IntrospectError as exc:
            print(f"Hata: {exc}")
            return EXIT_BAD_INPUT
    else:
        if _db_missing(db_path):
            return _no_db(db_path)
        skeleton = introspect.sqlite_skeleton(db_path)
    if sample:
        # Allowlist yoklanan iskeletin kendisi: R3-14 gereği introspect bir Netsis kopyasında
        # schema.json yazılmadan önce koşar, varsayılan liste o kopyanın tablolarını bilmez.
        executor = LocalExecutor(
            db_path=db_path, audit_path=audit_path, allowlist=doc.allowlist(skeleton)
        )
        introspect.sample_hints(db_path, skeleton, executor)
    _write_json(out, skeleton)
    tables = skeleton["tables"]
    print(
        SKELETON_WRITTEN.format(
            tables=len(tables),
            columns=sum(len(table["columns"]) for table in tables),
            path=out,
        )
    )
    return 0


def diff_map(
    excel_path: str | Path,
    db_schema: str | Path | None = None,
    db_path: str | Path = config.DB_PATH,
    json_out: str | Path = config.DIFF_JSON_PATH,
    md_out: str | Path = config.DIFF_MD_PATH,
) -> int:
    """Excel haritası ile veritabanı iskeletini karşılaştırır; farkı diff.json + diff.md olarak yazar (R3-5).

    Veritabanı tarafı ya hazır bir iskelet dosyasından okunur (``db_schema``) ya da canlı yoklanır. Ekran
    bölüm bölüm sayıları, sonra iki çıktı yolunu söyler; fark yoksa "Fark yok." (R3-13).
    """
    _utf8_stdout()
    excel_doc = _read_schema(excel_path)
    if excel_doc is None:
        return EXIT_BAD_INPUT
    if db_schema:
        db_doc = _read_schema(db_schema)
        source = str(db_schema)
    else:
        db_doc = _introspect_db(db_path)
        source = f"canlı ({db_path})"
    if db_doc is None:
        return EXIT_BAD_INPUT

    report = merge.diff_map(excel_doc, db_doc)
    merge.save_diff(report, json_out, md_out)

    print(f"Excel: {excel_path}")
    print(f"Veritabanı: {source}\n")
    counts = [(title, len(report[key])) for key, title, _ in merge.SECTIONS if report.get(key)]
    if counts:
        for title, count in counts:
            print(f"{title}: {count}")
    else:
        print(NO_DIFF)
    print(f"\nJSON: {json_out}")
    print(f"Markdown: {md_out}")
    return 0


def merge_map(
    excel_path: str | Path,
    db_schema: str | Path | None = None,
    db_path: str | Path = config.DB_PATH,
    out: str | Path = config.MERGED_PATH,
) -> int:
    """Excel haritası ile veritabanı iskeletini tek şemada birleştirir ve ``out``a yazar (R3-5).

    Veritabanı tarafı varlığı, tipleri, nullability ve foreign keyleri taşır; Excel tarafı açıklamayı,
    değerleri ve modülü. Excel'in veritabanında olmayan tablosu buraya değil diff'in içine gider
    (R3-5), o yüzden merge-map diff-map'ın yerini almaz. Yazılan dosya ``eval --schema`` ile
    koşulabilir: ölçüm artık hangi şemayla yapıldıysa onunla yapılır.
    """
    _utf8_stdout()
    excel_doc = _read_schema(excel_path)
    if excel_doc is None:
        return EXIT_BAD_INPUT
    if db_schema:
        db_doc = _read_schema(db_schema)
        source = str(db_schema)
    else:
        db_doc = _introspect_db(db_path)
        source = f"canlı ({db_path})"
    if db_doc is None:
        return EXIT_BAD_INPUT

    schema = merge.merge_map(excel_doc, db_doc)
    _write_json(out, schema)
    tables = schema["tables"]
    print(f"Excel: {excel_path}")
    print(f"Veritabanı: {source}\n")
    print(
        MERGED_WRITTEN.format(
            path=out,
            tables=len(tables),
            columns=sum(len(table["columns"]) for table in tables),
        )
    )
    return 0


def make_client(kind: str, mode: str = config.DEFAULT_EVAL_MODE):
    """``--llm`` değerini istemciye çevirir: fake altın kaydı oynatır, openai config'teki endpoint'e gider.

    Sahte istemci oynatacağı kaydı moddan alır: ``rag`` aramadan geçerek, diğerleri şemadan.
    """
    if kind == "fake":
        return fake.for_golden(runner.load_golden(), mode=mode)
    settings = config.llm_settings()
    return OpenAIClient(settings.base_url, settings.model, settings.api_key)


def make_map_client(kind: str, preview: dict):
    """``import-map``ın ``--llm`` değeri.

    ``fake`` zekâ değil boru hattı ölçer: sözlük eşlemesini olduğu gibi JSON geri verir, böylece
    öneri → dosya → dönüşüm zincirinin tamamı model olmadan koşulur.
    """
    if kind == "fake":
        reply = json.dumps(excel.fallback_mapping(preview), ensure_ascii=False)
        return fake.FakeLLM([ChatResponse(content=reply)])
    return make_client(kind)


def main(argv: list[str] | None = None) -> int:
    """argparse: ``build-db`` | ``ask`` | ``eval``; seçilen komutun işlevini çağırır."""
    parser = argparse.ArgumentParser(prog="python -m nl2sql", description="NL -> T-SQL ölçüm aracı.")
    commands = parser.add_subparsers(dest="command", required=True)

    build_cmd = commands.add_parser("build-db", help="sentetik veritabanını ve T-SQL betiğini kurar")
    build_cmd.add_argument(
        "--seed", type=int, default=config.SEED, help="üretici tohumu (varsayılan %(default)s)"
    )

    index_cmd = commands.add_parser("build-index", help="şema ve kurallardan arama indeksini kurar")
    index_cmd.add_argument(
        "--embed",
        choices=EMBEDS,
        default=DEFAULT_EMBED,
        help="embedder kaynağı (varsayılan %(default)s)",
    )

    retrieval_cmd = commands.add_parser(
        "eval-retrieval", help="altın sorularında aramanın geri çağırmasını ölçer"
    )
    retrieval_cmd.add_argument(
        "--embed",
        choices=EMBEDS,
        default=DEFAULT_EMBED,
        help="embedder kaynağı (varsayılan %(default)s)",
    )
    retrieval_cmd.add_argument(
        "--k", type=int, default=config.SEARCH_K, help="kaç tablo (varsayılan %(default)s)"
    )

    import_cmd = commands.add_parser(
        "import-map", help="Excel şema haritasını eşler; --accept ile şemayı yazar"
    )
    import_cmd.add_argument("file", metavar="HARITA.xlsx", help="Excel şema haritasının yolu")
    import_cmd.add_argument(
        "--llm", choices=LLMS, default=DEFAULT_LLM, help="istem kaynağı (varsayılan %(default)s)"
    )
    import_cmd.add_argument(
        "--accept",
        action="store_true",
        help="eşlemeyi tüm satırlara uygular ve şemayı yazar (uygulamayı kod yapar, model değil)",
    )
    import_cmd.add_argument(
        "--mapping",
        metavar="DOSYA.json",
        help="--accept için eşleme dosyası (varsayılan: az önce yazılan)",
    )
    import_cmd.add_argument(
        "--out",
        default=str(config.IMPORTED_PATH),
        help="yazılacak şema dosyası (varsayılan %(default)s)",
    )

    introspect_cmd = commands.add_parser(
        "introspect", help="veritabanını yoklar ve iskelet şemayı yazar"
    )
    introspect_cmd.add_argument(
        "--out",
        default=str(config.SKELETON_PATH),
        help="yazılacak iskelet dosyası (varsayılan %(default)s)",
    )
    introspect_cmd.add_argument(
        "--sample",
        action="store_true",
        help=f"kısa metin kolonlarına en fazla {config.SAMPLE_HINT_N} örnek değer ekler",
    )

    diff_cmd = commands.add_parser(
        "diff-map", help="Excel haritası ile veritabanını karşılaştırır, farkı diff.json/md yazar"
    )
    diff_cmd.add_argument(
        "--excel", required=True, metavar="SEMA.json", help="Excel'den üretilmiş şema dosyası"
    )
    db_source = diff_cmd.add_mutually_exclusive_group(required=True)
    db_source.add_argument("--db", action="store_true", help="karşı taraf: canlı veritabanını yoklar")
    db_source.add_argument(
        "--db-schema", metavar="ISKELET.json", help="karşı taraf: hazır iskelet dosyası"
    )

    merge_cmd = commands.add_parser(
        "merge-map", help="Excel haritası ile veritabanını birleştirir, şemayı --outa yazar"
    )
    merge_cmd.add_argument(
        "--excel", required=True, metavar="SEMA.json", help="Excel'den üretilmiş şema dosyası"
    )
    merge_source = merge_cmd.add_mutually_exclusive_group(required=True)
    merge_source.add_argument("--db", action="store_true", help="birleşecek taraf: canlı veritabanını yoklar")
    merge_source.add_argument(
        "--db-schema", metavar="ISKELET.json", help="birleşecek taraf: hazır iskelet dosyası"
    )
    merge_cmd.add_argument(
        "--out",
        default=str(config.MERGED_PATH),
        help="yazılacak birleşik şema dosyası (varsayılan %(default)s)",
    )

    ask_cmd = commands.add_parser("ask", help="tek bir soruyu modelden geçirip cevabı gösterir")
    ask_cmd.add_argument("question", help='Türkçe soru, örn. "Geçen ayın cirosu ne kadar?"')
    ask_cmd.add_argument(
        "--llm", choices=LLMS, default=DEFAULT_LLM, help="istem kaynağı (varsayılan %(default)s)"
    )
    ask_cmd.add_argument(
        "--mode",
        choices=config.MODES,
        help="bağlam modu (verilmeyince taze indeks varsa rag, yoksa full)",
    )

    eval_cmd = commands.add_parser("eval", help="altın soruları koşar ve raporu yazar")
    eval_cmd.add_argument(
        "--llm", choices=LLMS, default=DEFAULT_LLM, help="istem kaynağı (varsayılan %(default)s)"
    )
    eval_cmd.add_argument(
        "--only", nargs="+", metavar="Q03", help="yalnız bu soru kimlikleri (boşlukla ayrılır)"
    )
    eval_cmd.add_argument(
        "--tag",
        nargs="+",
        metavar="archive",
        help="yalnız bu etiketlerden birini taşıyan sorular (boşlukla ayrılır)",
    )
    eval_cmd.add_argument(
        "--mode",
        choices=config.MODES,
        default=config.DEFAULT_EVAL_MODE,
        help="bağlam modu (varsayılan %(default)s)",
    )
    eval_cmd.add_argument(
        "--compare",
        action="store_true",
        help="üç modu aynı sorularda koşar ve tek raporda karşılaştırır",
    )
    eval_cmd.add_argument(
        "--fresh", action="store_true", help="--compare ile yeniden koşmayan modları da koşar"
    )
    eval_cmd.add_argument(
        "--schema",
        default="full",
        metavar="DOSYA|full|skeleton",
        help="ölçümün şeması: tam ad ya da yol (varsayılan %(default)s)",
    )

    args = parser.parse_args(argv)
    if args.command == "build-db":
        return build_database(seed=args.seed)
    if args.command == "build-index":
        return build_index(embed=args.embed)
    if args.command == "eval-retrieval":
        return eval_retrieval(embed=args.embed, k=args.k)
    if args.command == "import-map":
        return import_map(
            args.file,
            lambda preview: make_map_client(args.llm, preview),
            accept=args.accept,
            mapping=args.mapping,
            out=args.out,
        )
    if args.command == "introspect":
        return introspect_schema(out=args.out, sample=args.sample)
    if args.command == "diff-map":
        return diff_map(args.excel, db_schema=args.db_schema)
    if args.command == "merge-map":
        return merge_map(args.excel, db_schema=args.db_schema, out=args.out)
    if args.command == "ask":
        mode = args.mode or _ask_mode()
        return ask(question=args.question, llm=make_client(args.llm, mode), mode=mode)
    if args.compare:
        return compare_modes(
            lambda mode: make_client(args.llm, mode),
            fresh=args.fresh,
            schema_path=args.schema,
        )
    return evaluate(
        llm=make_client(args.llm, args.mode),
        only=args.only,
        tags=args.tag,
        mode=args.mode,
        out_dir=Path(config.EVAL_OUT) / args.mode,
        schema_path=args.schema,
    )


def _step_lines(step: Step) -> list[str]:
    """Adımın satırları: sıra, ✓/✗, araç, gecikme; reddedilen bir sorgu sebebini alt satırda taşır."""
    head = f"  {step.n:>2} {'✓' if step.ok else '✗'} {step.tool or PROSE:<{TOOL_WIDTH}} {step.latency_ms:>5.0f} ms"
    if not step.ok:
        return [head, f"       ↳ {step.summary}"]
    if not step.tool:
        return [head, *(f"       {line}" for line in step.summary.splitlines())]
    if step.tool in SQL_TOOLS:
        # Şema adımı zaten okunan bir metindir, özetinin ilk satırı bir sonuç değil; sorgu adımları
        # kaç kolon döndürdüğünü söylemeyi hak eder.
        note = _first_line(step.summary)
        return [f"{head} · {note}"] if note else [head]
    notes = _search_notes(step.tool, step.summary)
    return [head, *(f"       {line}" for line in notes)] if notes else [head]


def _search_notes(tool: str, summary: str) -> list[str]:
    """R2-14: arama aracının cevabı modele gider, ekrana kaç birim döndüğü ve uyarısı yazılır.

    Araç hiçbir şey bulamadıysa (eşleşen tablo yok, tek tablo, değer yok) kendi cümlesi gösterilir;
    boş hali de kullanıcı için bir bilgidir.
    """
    lines = [line.strip() for line in summary.splitlines() if line.strip()]
    if tool == "search_schema":
        names = [match.group(1) for line in lines if (match := SCHEMA_HIT.match(line))]
        note = f"→ {', '.join(names)}" if names else ""
    elif tool == "get_table_details":
        count = len(DETAIL_HEAD.findall(summary))
        note = f"→ {count} tablo" if count else ""
    elif tool == "find_join_path":
        joins = sum(1 for line in lines if JOIN_LINE.match(line))
        note = f"→ {joins} join" if joins else ""
    elif tool == "search_rules":
        terms = [block.splitlines()[0].strip() for block in summary.split("\n\n") if block.strip()]
        note = f"→ {', '.join(terms)}" if terms else ""
    elif tool == "sample_values":
        found = VALUE_COUNT.search(summary)
        note = f"→ {found.group(1)} değer" if found else ""
    else:
        return []
    warnings = [line for line in lines if line.startswith(WARNING_MARK)]
    if not note and lines:
        note = f"→ {lines[0]}"
    return [note, *warnings] if note else warnings


def _cost(run: AgentRun) -> None:
    """Koşunun maliyeti: toplam token (nasıl bölündüğüyle birlikte) ve geçen süre."""
    total = run.total_prompt_tokens + run.total_completion_tokens
    print(f"Token: {total} (istem {run.total_prompt_tokens} + cevap {run.total_completion_tokens})")
    print(f"Süre: {run.elapsed_s:.1f} sn")


def _mapping_lines(mapping: dict) -> list[str]:
    """R3-13: önerinin tablosu — sayfa ve başlık satırı başına her sütunun eşlenen alanları.

    Alan listesi kaydın kendi anahtarlarından gelir; eşlenmemiş sütun "hiçbir alan" ile görünür
    kalır, çünkü müşterinin haritasında tanınmayan bir başlık düzeltilmesi gereken bir bilgidir.
    """
    lines: list[str] = []
    for sheet in mapping.get("sheets") or []:
        columns = [item for item in sheet.get("columns") or [] if isinstance(item, dict)]
        lines.append(f"\n{sheet.get('sheet')} — başlık satırı {sheet.get('header_row')}")
        width = max((len(str(item.get("column"))) for item in columns), default=0)
        for item in columns:
            fields = [
                name for name, value in item.items() if name != "column" and value is not None
            ]
            lines.append(f"  {str(item.get('column')):<{width}}  {' · '.join(fields) or UNMAPPED}")
    return lines


def _proposal_file(source: Path, proposal_path: str | Path | None) -> Path:
    """Önerinin yazılacağı yol; adlandırma kuralı config'de, testler kendi tmp yolunu verir."""
    return Path(proposal_path) if proposal_path else config.mapping_path(source.stem)


def _read_mapping(path: str | Path) -> dict | None:
    """Kullanıcının elle düzelttiği eşleme dosyası; okunamazsa ya da nesne değilse None."""
    try:
        chosen = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"{BAD_MAPPING.format(path=path)}\n{exc}")
        return None
    if not isinstance(chosen, dict):
        print(f'{BAD_MAPPING.format(path=path)}\nÜst düzey bir JSON nesnesi olmalı: {{"sheets": [...]}}.')
        return None
    return chosen


def _read_schema(path: str | Path) -> dict | None:
    """Şema/iskelet dosyası; okunamazsa ya da üst düzey nesne değilse None (yarı yolda düşmez)."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"{BAD_SCHEMA.format(path=path)}\n{exc}")
        return None
    if not isinstance(data, dict):
        print(f'{BAD_SCHEMA.format(path=path)}\nÜst düzey bir JSON nesnesi olmalı: {{"tables": [...]}}.')
        return None
    return data


def _schema_file(value: str | Path) -> Path:
    """``--schema`` değeri: ``full`` ve ``skeleton`` config'in iki dosyasının adı, başkası yolun kendisi (R3-5).

    Yollar çağrı anında alınır; bir test ``config.SKELETON_PATH``ı kendi tmp kopyasına çevirebilir.
    """
    aliases = {"full": config.SCHEMA_PATH, "skeleton": config.SKELETON_PATH}
    return Path(aliases.get(str(value), value))


def _load_schema(path: str | Path) -> dict | None:
    """``--schema`` dosyası sözleşme varsayılanlarıyla yüklenir; okunamazsa tek cümle ve None (Delight 3).

    Üst düzeyi nesne olmayan ya da ``tables`` taşımayan bir dosya da (yanlış yola verilmiş bir
    eşleme gibi) aynı cümleyle döner: kullanıcının düzelteceği bir eksik, iz dökümü değil.
    """
    try:
        return doc.load_schema(path)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"{BAD_SCHEMA.format(path=path)}\n{exc}")
        return None


def _write_json(path: str | Path, payload: dict) -> None:
    """Elle düzenlenecek dosya: Türkçe metin olduğu gibi, iki boşlukla girintili."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _context(mode: str, executor, schema: dict, rules: list[dict], index_dir: str | Path):
    """Modun bağlamı: üçü de kuralları taşır, rag bir de diskteki indeksi ve join graphını ister.

    İndeks yoksa ya da bayatsa yükleyici yükseltir; R2-9 onun sessizce yeniden kurulmasını
    yasaklıyor, çünkü bayat vektörler bulunamayan tabloyu modelin hatası gibi gösterir.
    """
    search = graph = None
    if mode == "rag":
        search = load_search(index_dir, schema, rules)
        graph = build_graph(schema, load_profile())
    return ToolContext(
        executor=executor, schema=schema, rules=rules, search=search, graph=graph, mode=mode
    )


def _ask_mode(index_dir: str | Path = config.INDEX_DIR) -> str:
    """``ask``a mod söylenmediyse varsayılan (R2-12): taze bir indeks varsa rag, yoksa notla full.

    İndeks gerçekten yüklenir: bayat vektörler bulunamayan tabloyu modelin hatası gibi gösterir,
    o yüzden R2-9 onu reddediyor. Ne kaybedildiği tek satırda söylensin, sessiz düşmesin.
    """
    try:
        load_search(index_dir, doc.load_schema(), load_rules())
    except (MissingIndexError, StaleIndexError):
        print(NO_INDEX_NOTE)
        return "full"
    return "rag"


def _fingerprint(mode: str, kind: str, model: str, lines: list[dict], results, schema, rules) -> dict:
    """Koşunun neyi ölçtüğünün imzası (R2-12); iki koşu ancak eşitse birbirinin devamı sayılır.

    İmza yalnız koşan soruları taşır; ``--only`` ile kısalan bir koşu hepsini ölçmüş gibi aynı
    imzayı verirse yeniden koşmak gerekip gerekmediği yanlış okunur.
    """
    ran = {result.id for result in results}
    return _mode_fingerprint(
        mode, kind, model, [line for line in lines if line["id"] in ran], schema, rules
    )


def _mode_fingerprint(
    mode: str, kind: str, model: str, lines: list[dict], schema: dict, rules: list[dict]
) -> dict:
    """İmza koşu öncesi de kurulabilir: compare bir modun ``latest``ini ancak bu imza eşitse yeniden koşar."""
    return report.fingerprint(
        mode=mode,
        llm=kind,
        model=model,
        golden=lines,
        schema=schema,
        rules=rules,
        index_hash=content_hash(schema, rules) if mode == "rag" else "",
        max_tool_calls=get_mode(mode).max_tool_calls,
    )


# ASSUMPTION: imzanın alan listesi Contracts'ta sabit, o yüzden vektör uzayı imzaya değil raporun
# ayar satırına yazılır; ``reusable`` imzayla birlikte onu da doğrular.
def _embedder_id(mode: str, index_dir: str | Path) -> str:
    """Koşunun vektör uzayı (``fake:64`` gibi): rag ölçümü indeksin vektörleriyle yapılır, diğerleri boş.

    ``NL2SQL_EMBED_MODEL`` değişip indeks yeniden kurulunca içerik imzası aynı kalıyor, o yüzden
    rag'in ``latest``i bayatken yeniden kullanılıp R2-13 kararı o bayat koşuyla kuruluyordu.
    """
    return _index_embedder(index_dir) if mode == "rag" else ""


def _index_embedder(index_dir: str | Path) -> str:
    """Kurulu indeksin ``meta.json``daki ``embedder`` alanı; indeks yoksa ya da bozuksa boş.

    Yalnız küçük imza dosyası okunur; vektörler burada gerekmez. İndeks eksikse rag'in
    koşamayacağını zaten ``_context`` söyler.
    """
    try:
        meta = json.loads((Path(index_dir) / META_FILE).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    return str(meta.get("embedder") or "")


def _client_kind(llm) -> tuple[str, str]:
    """İstemcinin adı ve raporun model hanesi: fake kendinin adını, openai config'teki modeli taşır."""
    if isinstance(llm, fake.FakeLLM):
        return "fake", "fake"
    return "openai", config.llm_settings().model


def _mode_report(out_dir: str | Path, mode: str) -> dict | None:
    """Modun ``latest`` raporu (R2-12); yoksa ya da okunamazsa None, yani yeniden koşulur."""
    return report._load(Path(out_dir) / mode / "latest" / report.REPORT_FILES[0])


def _compare_line(mode: str, summary: dict) -> str:
    """R2-14: mod başına tek satır — skor, tepe/medyan bağlam, ortalama araç, toplam süre, not."""
    score, context = summary["score"], summary["context"]
    note = f"  {REUSED_NOTE}" if summary["reused"] else ""
    return (
        f"{mode:<{TOOL_WIDTH}} {score['passed']}/{score['total']}"
        f"  bağlam {_tokens(context['max_prompt_tokens'])}/{_tokens(context['median_prompt_tokens'])}"
        f"  araç {summary['tool_calls']['mean']:.1f}"
        f"  {summary['seconds']['total']:.1f} sn{note}"
    )


def _absent_tags(lines: list[dict], tags: list[str] | None) -> list[str]:
    """İstenen etiketlerden hiçbir sorunun taşımadığı; sessiz boş bir koşu yerine adı söyle."""
    if not tags:
        return []
    carried = {tag for line in lines for tag in line.get("tags") or []}
    return [tag for tag in tags if tag not in carried]


def _table_counts(db_path: str | Path) -> tuple[int, int]:
    """Kurulu dosyada: tablo sayısı ve en az bir satırı olan tablo sayısı; şema-yalnız = farkı."""
    conn = sqlite3.connect(db_path)
    try:
        names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        dolu = sum(1 for name in names if conn.execute(f'SELECT 1 FROM "{name}" LIMIT 1').fetchone())
    finally:
        conn.close()
    return len(names), dolu


def _db_missing(db_path: str | Path) -> bool:
    """SQLite dosyası yoksa komutun yürütecek bir şeyi yok; mssql tarafı yerel dosyaya bakmaz."""
    return config.backend() == "sqlite" and not Path(db_path).exists()


def _no_db(db_path: str | Path) -> int:
    """Eksik veritabanı bir sorgu hatası gibi düşmesin: tek cümle, ne yapılacağı, kod 2."""
    print(NO_DB.format(path=db_path))
    return EXIT_NO_DB


def _introspect_db(db_path: str | Path) -> dict | None:
    """Canlı veritabanının iskeleti; yoklama yapılamıyorsa sebep ekrana, None döner (yarı yolda düşmez)."""
    if config.backend() == "mssql":
        try:
            return introspect.mssql_skeleton()
        except introspect.IntrospectError as exc:
            print(f"Hata: {exc}")
            return None
    if _db_missing(db_path):
        _no_db(db_path)
        return None
    return introspect.sqlite_skeleton(db_path)


def _index_failed(reason: str) -> int:
    """Rag'in indeksi yok ya da bayat: cümleyi store kurar, içinde hangi komutun çözdüğü de durur."""
    print(reason)
    return EXIT_NO_INDEX


def _llm_failed(reason: str) -> int:
    """Ölü uç nokta: adres ve sebep cümlesini llm.py üretir, eksik kalırsa öneri buradan eklenir."""
    print(f"Hata: {reason}")
    if ENV_URL not in reason:
        print(LLM_HINT)
    return EXIT_LLM


def _embed_failed(reason: str) -> int:
    """Ölü embedding sunucusu: adresi ve çözümü embed.py söyler; indeks hiç yazılmadan çıkılır."""
    print(f"Hata: {reason}")
    if EMBED_ENV_URL not in reason:
        print(EMBED_HINT)
    return EXIT_EMBED


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _utf8_stdout() -> None:
    """Türkçe etiketler ve ✓/✗ Windows konsolunun kod sayfasına sığmaz; akış bir kez UTF-8'e döner."""
    sys.stdout.reconfigure(encoding="utf-8")
