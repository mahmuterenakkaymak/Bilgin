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
import functools
import getpass
import json
import math
import os
from collections.abc import Callable
from decimal import Decimal
import re
import sqlite3
import sys
import time
import zipfile
from pathlib import Path

from openpyxl.utils.exceptions import InvalidFileException

from nl2sql import config, datasets
from nl2sql.agent import fake, llm, prompt
from nl2sql.agent.clarify import follow_up_text
from nl2sql.agent.llm import (
    ChatResponse,
    LLMError,
    ModelProfile,
    OpenAIClient,
    ProfileError,
    client_for,
    get_profile,
    load_profiles,
)
from nl2sql.agent.loop import AgentRun, Step, run_agent
from nl2sql.agent.modes import MODES, ToolContext, get_mode
from nl2sql.auth.bootstrap import dev_admin
from nl2sql.auth.store import UserError, UserStore
from nl2sql.cli.table import format_table
from nl2sql.engine import checks, login_script
from nl2sql.engine.connections import ConnectionStore, resolve as resolve_connection
from nl2sql.engine.dbstatus import DbStatus
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget, Result
from nl2sql.eval import metrics, report, retrieval, runner
from nl2sql.eval import compare_models
from nl2sql.eval.compare_modes import (
    build_compare,
    reusable,
    score_cell,
    write_compare,
)
from nl2sql.eval.runner import _tokens
from nl2sql.graph.graph import build_graph
from nl2sql.graph.profile import load_profile
from nl2sql.i18n import normalize_lang, t
from nl2sql.i18n.detect import detect_lang
from nl2sql.index.docs import COLLECTIONS, build_documents
from nl2sql.index.embed import EmbedError, make_embedder
from nl2sql.index.search import build_search, load_search
from nl2sql.index.store import (
    META_FILE,
    FileStore,
    ForeignIndexError,
    MissingIndexError,
    StaleIndexError,
    content_hash,
    dataset_arg,
)
from nl2sql.index.summaries import table_summaries
from nl2sql.policy import pii
from nl2sql.report.facts import compute_facts
from nl2sql.report.narrate import narrate
from nl2sql.schema_map import build, doc, excel, introspect, merge, template
from nl2sql.schema_map.rules import load_rules

LLMS = ("fake", "openai")
# ASSUMPTION: ölçüm aracının varsayılanı gerçek endpoint'tir; --llm fake model istemeyen ölçüm
# yolu olduğu için kendisi söylenerek seçilir.
DEFAULT_LLM = "openai"
# ASSUMPTION: indeksin varsayılanı da gerçek embedding sunucusudur; --embed fake aramanın
# davranışını model olmadan ölçmek isteyen yol olduğu için kendisi söylenerek seçilir.
DEFAULT_EMBED = "openai"
# R3-9: --embed artık choices değil, çünkü iki sonek de geçerli olmalı (fake:<dim>, openai:<model>);
# biçimi bozuk olan argparse yerine burada, kullanıcının kendi cümlesiyle reddedilir.
EMBED_ID = re.compile(r"(?:fake(?::[1-9]\d*)?|openai(?::\S+)?)\Z", re.IGNORECASE)

AUDIT_SOURCE = "ask"
# R5-14: ``ask --json`` soruyu web ile aynı kapıdan koşar; günlük ve denetim satırları bu ada
# bağlanır, çıkış kodu ise durumun adıdır — anlatı gelen cevaplar da başarılıdır.
JSON_SOURCE = "cli"
JSON_OK = ("answered", "needs_clarification")
# R5-14/R5-15: adresin seçimi kullanıcıya bırakılmaz: kendi makinesinin dışına çıkmaz, çıkarsa
# hiçbir şey dinlemeye başlamaz. R6-7: kimlik doğrulama artık her zaman açık, yani cümlenin
# gerekçesi tek kullanıcı değil, TLS ve ağ erişiminin kapsam dışı kalması.
LOOPBACK_HOSTS = (config.SERVE_HOST, "localhost")
# Sahte yoklamanın bağlantı dizesi: sunucunun adı kümenin kendisidir, çözücü de yoklayıcı da oradan okur.
PROBE_PREFIX = "PROBE:"
# R6-11: ayar artık yüklenmeyen bir küme söylüyorsa sunucu bunu tek satırda söyler ve düşer.
# R8-11: cümle kataloğa taşındı, sabit yine durur - testler onu buradan okur, değeri tr'nindir.
STORED_LOST = t("cli.serve.stored_lost", config.DEFAULT_LANG)
# Run 8: ``--dataset`` söylenmemişse sunulan dünya vitrin kümesidir; sentetik küme testin dünyasıdır.
DEMO_DATASET = "wwi"
SQL_TOOLS = ("run_sql", "submit_sql")

# R2-14: arama araçlarının cevabı modele gider, ekrana değil; adımda kaç birim döndüğü ve
# uyarısı durur. Araç adının sığacağı genişlik de modların araç listesinden gelir.
TOOL_WIDTH = max(len(tool["function"]["name"]) for mode in MODES.values() for tool in mode.tools)
# Gerçek bir arama sonucu: "TABLO — ..." ya da çıplak "TABLO". Cümleler ("Eşleşen tablo yok.",
# "Hata: ...") eşleşmez; adları onların ilk sözcüğünden çıkarmak uydurma ad üretirdi (R2-14).
# R4-8: ad "Şema.Tablo" da olabilir, yani büyük/küçük harf karışık ve tek noktalı.
TABLE_NAME = r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)?"
SCHEMA_HIT = re.compile(rf"({TABLE_NAME})(?: — .*)?$")
DETAIL_HEAD = re.compile(rf"^{TABLE_NAME} — ", re.MULTILINE)  # detay bloğunun başlık satırı
JOIN_LINE = re.compile(r"\S+ = ")  # bir join satırı: A.X = B.Y (fk 1.0)
WARNING_MARK = "⚠"
VALUE_COUNT = re.compile(r"Değerler \((\d+)\)")
# R8-4: reddin cümlesi kataloğa taşındı; sabit yine durur - test onu buradan okur, değeri tr'nindir.
BAD_REPEAT = t("cli.eval.bad_repeat", config.DEFAULT_LANG)
# R8-10: ekranın satırları kataloğa taşındı; iki sabit yine de adlarıyla durur - app/session ve
# testler onları buradan okur, yani değerleri program dilinin cümlesidir.
NO_INDEX_NOTE = t("cli.ask.no_index", config.DEFAULT_LANG)
# R8-11: eval ekranının satırları kataloğun ``cli.eval.*`` anahtarlarıdır. R3-10'un auto yasağı
# (bir A/B ölçümünün hangi kolu ölçtüğü baştan belli olmalı), R5-12/R7-14'un set yokluğu reddi
# (ölçülecek soru yoktur) ve R5-14'un metrik başlığı da orada durur.
# R4-13: kapalı bir uç nokta bütün modeli düşürür; sebep satırı hem ekranda hem raporun
# ``skipped``ında durur, yani okuyan hangi modelin neden ölçülmediğini rapordan da görür.
# R8-4: cümle kataloğa taşındı; sabit yine durur - test onu buradan okur, değeri tr'nindir.
MODEL_SKIPPED = t("cli.compare.model_skipped", config.DEFAULT_LANG)
# ASSUMPTION: hiçbir model koşmadıysa ortada ölçülen bir hücre yoktur; rapor yazılmadan çıkılır
# (ölü uç noktanın kod 3'ü gibi - koşulmamış bir karşılaştırmanın raporu kullanıcıyı yanıltır).
EXIT_NO_CELLS = 3

ENV_URL = "NL2SQL_LLM_BASE_URL"
EMBED_ENV_URL = "NL2SQL_EMBED_BASE_URL"
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

# R3-13: import-map ve diff-map'ın satırları kataloğun ``cli.import_map.*``/``cli.map.*``
# anahtarlarıdır; ikisi de kullanıcının denetleyeceği şeyi adıyla taşır.
NONE = "-"

# R5-14: netleştirmenin numaralı şıkkı — şıkkın kendisi modelin verdiği metindir, yani çevrilmez.
CLARIFY_OPTION = "  {n}. {option}"

# R3-5: eval hangi şema dosyasıyla ölçtüğünü canlı satırlardan önce söyler (imzanın başı, yani iki
# koşunun aynı şemayı ölçüp ölçmediği ekrandan okunur); satırı ``cli.eval.schema`` kataloğu kurar.

# ``--schema``nın argparse varsayılanı: tek başına tam şemanın adı, ``--dataset`` ile birlikte
# "şema söylenmedi" demek, yani kümenin kendi şemasının önüne geçmez (R4-4).
FULL_SCHEMA = "full"

# R6-8: ``user`` komutunun satırları kataloğun ``cli.user.*`` satırlarıdır. Parola hiçbir zaman
# argüman değildir, iki kez sorulur ve uyuşmazsa hiçbir şey yazılmaz; ``list`` sözleşme
# "User (public)" alanlarını basar, yani karma ekranın hiçbir yerine girmez.
NO_USERS = t("cli.user.no_users", config.DEFAULT_LANG)  # serve da bu cümleyi söyler (R6-7)
USER_COLUMN_KEYS = (
    "cli.user.col_username",
    "cli.user.col_role",
    "cli.user.col_business_role",
    "cli.user.col_status",
    "cli.user.col_last_login",
)

# R8-11: ``main``in argv'den çözdüğü ekran dili; ``--lang`` görmemiş bir çağrı tr'de kalır.
_LANG = config.DEFAULT_LANG


def build_database(
    seed: int | None = None,
    db_path: str | Path | None = None,
    sql_path: str | Path | None = None,
    dataset: str | None = None,
    lang: str | None = None,
) -> int:
    """Sentetik veriyle SQLite dosyasını ve T-SQL kurulum betiğini üretir.

    Ekran ölçümün iki girdisini de söyler (R2-14): kaç tabloda gerçekten satır olduğu (distractor
    tabloların bir kısmı şemada öylece durur) ve ``full`` modun şema metninin bağlam maliyeti.
    ``dataset`` verildiğinde tohum, iki hedef yol ve şema metnine kadar her şey o kümenin
    tanımıdır (R4-14); açıkça verilen yol ya da tohum onun önüne geçer. ``lang`` ekranın dilidir
    (R8-11): satırlar ``cli.build`` kataloğundan o dilde gelir.
    """
    _utf8_stdout()
    ds, code = _dataset(dataset)
    if code:
        return code
    _dataset_line(ds, lang)
    seed = _or(seed, ds.seed if ds else None, config.SEED)
    db_path = _or(db_path, ds.db_path if ds else None, config.DB_PATH)
    sql_path = _or(sql_path, ds.mssql_script if ds else None, config.MSSQL_SCRIPT)
    digest = ds.build_db(seed, db_path, sql_path) if ds else build.build_db(seed, db_path, sql_path)
    print(_t("cli.build.seed", lang, seed=seed))
    print(_t("cli.build.db", lang, path=db_path))
    print(_t("cli.build.sql", lang, path=sql_path))
    toplam, dolu = _table_counts(db_path)
    print(
        _t(
            "cli.build.tables",
            lang,
            total=toplam,
            filled=dolu,
            schema_only=toplam - dolu,
        )
    )
    schema_text = doc.full_text(ds.schema() if ds else doc.load_schema())
    print(
        _t(
            "cli.build.schema_text",
            lang,
            chars=len(schema_text),
            tokens=doc.estimate_tokens(schema_text),
        )
    )
    print(_t("cli.build.digest", lang, hash=digest[:12]))
    return 0


def build_index(
    embed: str = DEFAULT_EMBED,
    index_dir: str | Path | None = None,
    schema_path: str | Path | None = None,
    rules_path: str | Path | None = None,
    dataset: str | None = None,
    dataset_name: str | None = None,
    lang: str | None = None,
) -> int:
    """Şema ile kurallardan arama indeksini kurar: dokümanlar, vektörler, imza (R2-14).

    Ekran dört şeyi söyler: kaç doküman yazıldığı (koleksiyon koleksiyon), vektörlerin kimin ve
    kaç genişlikte olduğu, içeriğin imzasının başı ve ne kadar sürdü. İmza, ``ask`` tarafının bayat
    indeksi reddetmesinin kendisi olduğu için burada ekrana da çıkıyor. İmzanın yanına bir de hangi
    veri kümesinin indeksi olduğu yazılır (R4-8), çünkü iki kümenin şemaları birbiriyle karışabilir.
    ``dataset`` o kümenin adını, şemasını, kurallarını ve indeks klasörünü de verir (R4-14).
    Tablo dokümanlarının yanına bir de tablo başına bir özet yazılır (R5-20); sayım satırı onu
    kendi koleksiyonuyla gösterir.

    ``dataset_name`` aynı satırın T131'deki adı: ikisi de ``meta.dataset``a yazılır, ikisi birden
    verilirse ``dataset`` kazanır. ``lang`` ekranın dilidir (R8-11): satırlar ``cli.index``
    kataloğundan o dilde gelir.
    """
    _utf8_stdout()
    ds, code = _dataset(dataset)
    if code:
        return code
    _dataset_line(ds, lang)
    schema_path = _or(schema_path, ds.schema_path if ds else None, config.SCHEMA_PATH)
    rules_path = _or(rules_path, ds.rules_path if ds else None, config.RULES_PATH)
    index_dir = _or(index_dir, ds.index_dir if ds else None, config.INDEX_DIR)
    profile_path = ds.profile_path if ds else config.PROFILE_PATH
    started = time.perf_counter()
    schema = doc.load_schema(schema_path)
    rules = load_rules(rules_path)
    docs = build_documents(schema, rules)
    # R5-20: özetler şema + kural + graphdan türetilir, yani imzaya yeni bir girdi girmez; graphın
    # burada kurulmasının nedeni de yalnızca komşu satırıdır.
    docs += table_summaries(schema, rules, build_graph(schema, load_profile(profile_path)))
    embedder = make_embedder(embed)
    try:
        vectors = embedder.embed([item.text for item in docs])
    except EmbedError as exc:
        return _embed_failed(str(exc), lang)
    seconds = time.perf_counter() - started
    digest = content_hash(schema, rules)
    FileStore(index_dir).save(
        docs,
        vectors,
        {
            "content_hash": digest,
            "embedder": embedder.id,
            "dim": embedder.dim,
            "dataset": _or(dataset, dataset_name, config.DEFAULT_DATASET),
        },
    )
    print(_t("cli.index.schema", lang, path=schema_path, tables=len(schema["tables"])))
    print(_t("cli.index.rules", lang, path=rules_path, rules=len(rules)))
    print(
        _t(
            "cli.index.docs",
            lang,
            counts=", ".join(
                f"{name} {sum(1 for item in docs if item.collection == name)}"
                for name in COLLECTIONS
            ),
            total=len(docs),
        )
    )
    print(f"Embedder: {embedder.id} (dim {embedder.dim})")
    print(_t("cli.index.signature", lang, hash=digest[:12]))
    print(_t("cli.index.duration", lang, seconds=f"{seconds:.1f}"))
    print(_t("cli.index.dir", lang, path=index_dir))
    return 0


def eval_retrieval(
    embed: str = DEFAULT_EMBED,
    k: int = config.SEARCH_K,
    out_dir: str | Path | None = None,
    schema_path: str | Path | None = None,
    rules_path: str | Path | None = None,
    golden_path: str | Path | None = None,
    profile_path: str | Path | None = None,
    dataset: str | None = None,
    summaries: bool = False,
    lang: str | None = None,
) -> int:
    """Aramanın geri çağırmasını altın sorular üzerinde ölçer ve raporu yazar (R2-14).

    İndeks bellekte kurulur (R2-9): ölçüm diskteki indekse ya da veritabanına bakmaz, temiz bir
    koşumda da çalışır. Ekran soru başına bir satır, metod ve etiket ortalamalarıdır; sayıların
    kendisi ``eval_out/retrieval`` altındaki raporda da durur. R3-9'un üç varyantı (taban,
    +komşu, +eşanlam) aynı sorular üzerinde koşar, o yüzden join graphı da burada kurulur.
    ``dataset`` ölçümün dört girdisini de o kümenin klasöründen getirir (R4-14): şema, kurallar,
    profil ve altın sorular. Rapor da o kümenin ``eval_out``u altına yazılır (R4-3, R4-4): iki
    dünya aynı ``latest``i paylaşırsa ikincinin koşumu birincinin kıyasını yutar. Açıkça verilen
    yol yine önüne geçer.

    ``summaries`` açıkken (R5-20) tablo dokümanlarının yanına tablo özetleri de indekse girer ve
    dördüncü varyant olarak ölçülür; kapalıyken koşum bugünkü üç varyantın halidir.
    """
    _utf8_stdout()
    lang = lang or _LANG
    ds, code = _dataset(dataset)
    if code:
        return code
    _dataset_line(ds, lang)
    schema_path = _or(schema_path, ds.schema_path if ds else None, config.SCHEMA_PATH)
    rules_path = _or(rules_path, ds.rules_path if ds else None, config.RULES_PATH)
    golden_path = _or(golden_path, ds.golden_path if ds else None, config.GOLDEN_PATH)
    profile_path = _or(profile_path, ds.profile_path if ds else None, config.PROFILE_PATH)
    out_dir = _or(out_dir, Path(ds.eval_out) / "retrieval" if ds else None, retrieval.RETRIEVAL_OUT)
    started = time.perf_counter()
    schema = doc.load_schema(schema_path)
    rules = load_rules(rules_path)
    graph = build_graph(schema, load_profile(profile_path))
    try:
        search = build_search(schema, rules, make_embedder(embed), graph if summaries else None)
    except EmbedError as exc:
        return _embed_failed(str(exc), lang)
    result = retrieval.run_variants(
        search, runner.load_golden(golden_path), k, graph, schema, summaries, lang=lang
    )
    print()
    for line in retrieval.console_lines(result, lang):
        print(line)
    print("\n" + _t("cli.eval_retrieval.duration", lang, seconds=f"{time.perf_counter() - started:.1f}"))
    run_dir = retrieval.write_retrieval(result, out_dir, lang)
    print(_t("cli.eval.report", lang, path=run_dir / "report.md"))
    return 0


def ask(
    question: str,
    llm,
    mode: str = "full",
    db_path: str | Path | None = None,
    audit_path: str = config.AUDIT_LOG,
    index_dir: str | Path | None = None,
    estimate: int | None = None,
    dataset: str | None = None,
    dataset_line: bool = True,
    budget: int | None = None,
    profile: ModelProfile | None = None,
    choice: str | None = None,
    conversations=None,
    conversation_id: str | None = None,
    lang: str = "tr",
) -> int:
    """Bir soru: modunu söyle, adımları işaretle ve gecikmesiyle dök, gönderilen SQL'i, tabloyu,
    uyarıları ve tek cümlelik cevabı göster.

    ``llm`` hazır bir istemcidir; ``mode`` hangi araçların konuşacağını ve bağlamın nereden
    geleceğini söyler (rag indeksi ister, R2-9). ``mode`` olarak ``auto`` da verilebilir (R3-10):
    bağlam tahmini bütçeye sığıyorsa full_rules, sığmıyorsa rag denenir, indeksi yoksa notla full'a
    düşülür; ``ask`` komutu argparse üzerinden auto ile açılır, ``main`` çözülmüş modu ve tahmini
    buraya geçirir. ``estimate`` auto'nun tahminidir; verilirse mod satırı auto çözümü olarak basılır.
    Tablo için gönderilen SQL bir kez daha yürütülür, çünkü döngü yanıtı metin olarak görür, satırları
    ekrana basacak biçimde elinde tutmaz. Tablo şemanın pii işaretlerinden gelen maskeyle görünür ve
    maskelenen kolonların adı altta söylenir (R3-6).

    ``dataset`` verildiğinde şema, kurallar, join profili, veritabanı, indeks ve referans tarihi o
    kümenin tanımıdır (R4-4); açıkça verilen yol ya da mod onun önüne geçer. ``dataset_line``
    False ise çağıran küme satırını çoktan basmıştır (R4-14): ``main`` auto çözümünden önce
    bastığı için burada yinelenmez, yoksa satır ekranın ilk satırı olmaktan çıkar.

    ``budget`` tur başına istem bütçesidir (R4-11): döngü ona sığmayan cevabı kısaltır, kısaltma da
    yetmezse modele hiç gitmeden durur ve ekran hangi cevabın kısaltıldığını ya da cevabın neden
    hiç gelmediğini söyler.

    ``profile`` ``--model``in profilidir (R4-10): ekran hangi modelle ve hangi pencereyle koşulduğunu
    ilk satırlarda söyler, bütçe söylenmediyse profilin penceresinden gelir ve auto'nun eşiği de o
    pencereye göre kurulur. Verilmediğinde koşum Run 3'ün halidir: config'in ucu, bütçe yok.

    İlk soru netleştirme sorabilir (R5-10): ekran soruyu ve şıklarını yazar ve kod 0 ile çıkar —
    cevap gelmedi, ama bir hata da olmadı. ``choice`` o şıklardan biridir (R5-11): soru seçilen
    anlamla koşar ve o tur yeniden sormaz.

    ``conversations`` verildiğinde (R7-9) çağrı bir konuşmanın turudur: ``conversation_id`` yoksa
    konuşma yeni açılır, varsa yüklenir (bulunamazsa ``ConversationNotFound``) ve son turlar
    döngüye history olarak girer; tur konuşmaya yazılır ve ekranın son satırı ``Konuşma: <id> ·
    tur <n>`` olur. Verilmediğinde koşum Run 1'in halidir, uygulamaya hiçbir şey yazılmaz.

    ``lang`` ekranın dilidir (R8-10): çerçevenin her satırı ``cli.ask`` kataloğundan o dilde gelir.
    Cevabın dili yine sorunun dilidir (R8-6), yani ``--lang en`` Türkçe bir sorunun çevresini
    İngilizce söyler; "tr" çıktısı bugünküyle bayt aynıdır.
    """
    _utf8_stdout()
    # R8-6: cevabın dili sorunun dilidir; ``lang`` yalnız soru hiçbir dil söylemediğinde devreye
    # girer. Çerçeve ``lang``ı, olgular ve anlatı ``answer_lang``i konuşur.
    answer_lang = detect_lang(question, lang)
    ds, code = _dataset(dataset)
    if code:
        return code
    if dataset_line:
        _dataset_line(ds)
    if profile:
        print(_model_line(profile, lang))
    budget = _or(budget, profile.prompt_limit if profile else None)
    db_path = _or(db_path, ds.db_path if ds else None, config.DB_PATH)
    index_dir = _or(index_dir, ds.index_dir if ds else None, config.INDEX_DIR)
    if _db_missing(db_path):
        return _no_db(db_path, ds.name if ds else None, lang)
    schema = ds.schema() if ds else doc.load_schema()
    rules = ds.rules() if ds else load_rules()
    if mode == "auto":
        try:
            mode, estimate = resolve_auto(
                schema,
                rules,
                index_dir,
                ds.as_of if ds else config.AS_OF,
                ds.name if ds else None,
                max_tokens=_auto_limit(profile),
                lang=lang,
            )
        except ForeignIndexError as exc:
            # R4-8: başka dünyanın vektörleri düşülecek bir indeks değil, reddedilecek biridir.
            return _index_failed(str(exc))
    executor = LocalExecutor(
        db_path=db_path,
        allowlist=doc.allowlist(schema),
        audit_path=audit_path,
        pii_schema=schema,
    )
    try:
        context = _context(
            mode, executor, schema, rules, index_dir, ds,
            clarify=not choice, answer_lang=answer_lang,
        )
    except (MissingIndexError, StaleIndexError) as exc:
        return _index_failed(str(exc))
    # R7-9: ``--new``/``--conversation`` konuşmayı açar ya da yükler; miras turlar döngüye history
    # olarak girer. Depo yoksa (düz ask) history None kalır, koşum Run 1'in halidir.
    pending = None
    history = None
    if conversations is not None:
        conversation_id, pending, history = _conversation_thread(
            conversations, conversation_id, question, choice, ds.name if ds else None
        )
    # Bütçe yalnız verildiğinde geçirilir (R4-11: ``budget=None`` = Run 3'ün koşumu olduğu gibi).
    asked = follow_up_text(question, choice) if choice else question
    # ASSUMPTION: ekran ``ask``ı ask_payload'dan geçmez - soru günlüğü satırı da audit_id'si de yoktur, yani
    # R6-9'un adı taşıyacak bir kaydı burada yoktur; kaynak Run 1'in ``ask``ı olarak kalır.
    run = run_agent(
        asked,
        llm,
        executor,
        schema,
        AUDIT_SOURCE,
        mode=mode,
        context=context,
        **_given(budget=budget, history=history),
    )

    if estimate is None:
        print(t("cli.ask.mode", lang, mode=mode))
    else:
        print(_auto_line(mode, estimate, _auto_limit(profile), lang))
    print(t("cli.ask.question", lang, question=question))
    if choice:
        print(t("cli.ask.choice", lang, option=choice))
    print()
    if run.steps:  # daha ilk turda düşen bir uç noktanın gösterecek adımı yok
        print(t("cli.ask.steps", lang))
        for step in run.steps:
            for line in _step_lines(step, lang):
                print(line)
        print()
    if run.trimmed:
        # R4-11: kırpma görünmez bir olay değil; modelin hangi araç cevabını eksik gördüğü
        # ekrandan okunmalı.
        print(t("cli.ask.trimmed", lang, trimmed=run.trimmed) + "\n")
    if run.status == "llm_error":
        return _llm_failed(run.stop_reason, lang)
    if run.status == "needs_clarification":
        for line in _clarify_lines(question, run.clarification, lang):
            print(line)
        _cost(run, lang)
        if conversations is not None:
            _conversation_line(
                conversations, conversation_id, pending, lang=lang,
                question=question, choice=choice,
                status="needs_clarification", sql=None, columns=[], rows=[], row_count=0,
                facts=[], answer_text="", clarification=run.clarification,
            )
        return 0
    if not run.submitted_sql:
        reason = run.stop_reason or t("cli.ask.no_submission", lang)
        print(t("cli.ask.no_answer", lang, reason=reason))
        _cost(run, lang)
        if conversations is not None:
            _conversation_line(
                conversations, conversation_id, pending, lang=lang, question=question, choice=choice,
                status="failed", sql=None, columns=[], rows=[], row_count=0, facts=[],
                answer_text="", clarification=None,
            )
        return 1

    print(t("cli.ask.sql_head", lang))
    print(run.submitted_sql)
    print("\n" + t("cli.ask.result_head", lang))
    result = executor.execute(run.submitted_sql, Budget(), AUDIT_SOURCE)
    print(format_table(result, lang))
    if result.masked_columns:
        # R3-6: maskelenen kolonlar tablonun altında adlarıyla söylenir; hangi değerin maskeli
        # olduğu okunabilsin diye, değerin kendisi asla ekrana çıkmadığı için.
        print(t("cli.ask.masked", lang, cols=", ".join(result.masked_columns)))
    for warning in checks.post_checks(run.submitted_sql, result, executor, answer_lang):
        print(f"{WARNING_MARK} {warning.message}")
    facts = compute_facts(result.columns, result.rows, answer_lang)
    sentence = narrate(asked, result.columns, result.rows, facts, llm, lang=answer_lang).text
    print(f"\n{t('cli.ask.answer', lang, text=sentence)}")
    print()
    _cost(run, lang)
    if conversations is not None:
        _conversation_line(
            conversations, conversation_id, pending, lang=lang, question=question, choice=choice,
            status="answered", sql=run.submitted_sql, columns=result.columns, rows=result.rows,
            row_count=len(result.rows), facts=[fact.to_dict() for fact in facts],
            answer_text=sentence, clarification=None,
        )
    return 0


def _conversation(args) -> tuple:
    """``--new``/``--conversation``: konuşma deposu ve kimliği; ikisi de yoksa ``(None, None)`` = düz ask.

    Depo yalnız bayraklardan biri verildiğinde açılır, yani düz ``ask`` uygulamanın veritabanına
    konuşma tablosunu bile yazmaz (R7-9).
    """
    if not (args.new or args.conversation):
        return None, None
    from nl2sql.app.conversations import ConversationStore

    return ConversationStore(config.app_db_path()), args.conversation


def _conversation_thread(conversations, conversation_id, question, choice, dataset) -> tuple:
    """Ekran için konuşmanın hali (R7-9): ``(kimlik, tamamlanacak bekleyen tur, miras turlar)``.

    ``conversation_id`` yoksa konuşma yeni açılır; varsa yüklenir ve bulunamazsa
    ``ConversationNotFound``dır - CLI'nin kod 2'si oradan okunur. Sahiplik sorulmaz: ekran tek
    kullanıcılıdır, konuşmanın sahibi NULL kalır.
    """
    from nl2sql.app.conversations import ConversationNotFound

    if conversation_id is None:
        return conversations.create(dataset=dataset, title=question), None, None
    found = conversations.get(conversation_id, dataset=dataset)
    if found is None:
        raise ConversationNotFound()
    last = found["turns"][-1] if found["turns"] else None
    pending = (
        last["n"]
        if choice and last and last["status"] == "needs_clarification" and last["question"] == question
        else None
    )
    return conversation_id, pending, conversations.last_turns(conversation_id, config.CONV_TURNS)


def _conversation_turn(conversations, conversation_id, pending, **turn) -> int:
    """Ekran turunun konuşmaya yazılışı (R7-9): bekleyen netleştirme varsa üstüne, yoksa yeni tur."""
    from nl2sql.agent.context import turn_summary

    row = {
        "question": turn["question"],
        "choice": turn["choice"],
        "status": turn["status"],
        "sql": turn["sql"] or None,
        "columns": turn["columns"],
        "summary": turn_summary(
            {
                "columns": turn["columns"],
                "row_count": turn["row_count"],
                "rows": turn["rows"],
                "facts": turn["facts"],
                "clarification": turn["clarification"],
            }
        ),
        "answer_text": turn["answer_text"],
        "audit_id": None,
    }
    n = conversations.complete_turn(conversation_id, pending, row) if pending is not None else None
    return n if n is not None else conversations.add_turn(conversation_id, row)


def _conversation_line(conversations, conversation_id, pending, lang: str = "tr", **turn) -> None:
    """Turu konuşmaya yazar ve son satırı basar: ``Konuşma: <id> · tur <n>`` (R7-9)."""
    n = _conversation_turn(conversations, conversation_id, pending, **turn)
    print(t("cli.ask.conversation", lang, id=conversation_id, n=n))


def evaluate(
    llm,
    only: list[str] | None = None,
    tags: list[str] | None = None,
    mode: str = config.DEFAULT_EVAL_MODE,
    db_path: str | Path | None = None,
    audit_path: str = config.AUDIT_LOG,
    out_dir: str | Path | None = None,
    index_dir: str | Path | None = None,
    schema_path: str | Path | None = None,
    dataset: str | None = None,
    budget: int | None = None,
    profile: ModelProfile | None = None,
    ambiguous: bool = False,
    narrate: bool = False,
    followups: bool = False,
    lang: str | None = None,
) -> int:
    """Altın soruları bir modda koşar, her soru biter bitmez tek satır dökerek (Delight 4)
    ilerler, raporu ``out_dir`` altına yazar (CLI ona ``eval_out/<mode>`` verir, R2-12), skoru söyler; koşu tamamlandıysa kod 0'dır.

    Mod yalnızca bir etiket değil, koşunun kendisi: ``full_rules`` kuralları bağlamdan ister,
    ``rag`` diskteki indeks ile join graphını yükler (R2-9: bayat indeks reddedilir, sessizce
    yeniden kurulmaz). Rapor modun kendi klasörüne gider ki fark iki farklı mod arasında
    kıyaslanmasın (R2-12); imza da o yüzden raporun içinde durur.

    ``schema_path`` de koşunun kendisini tanımlar (R3-5): allowlist, modelin gördüğü şema metni,
    join graphı, indeks imzası ve pii işaretleri (R3-6; ölçüm maskelenmiş satırla yapılır) hepsi
    okunan dosyadan gelir; yolu ve imzasının başı ekrana, yolu ve imzası rapora yazılır, böylece
    iki koşu ancak aynı şemayı ölçtüyse birbirinin devamı sayılır. ``--schema`` verildiğinde
    kümenin şemasının önüne geçer (R4-4).

    ``dataset`` verildiğinde altın sorular, kurallar, profil, veritabanı, indeks, rapor klasörü ve
    referans tarihi o kümenin tanımıdır (R4-4); açıkça verilen her yol onun önüne geçer.

    ``profile`` ``--model``in profilidir (R4-10): bütçe söylenmediyse tur başına istem bütçesi onun
    penceresinden gelir, rapor hangi modelle ve hangi pencereyle ölçtüğünü ondan yazar, imzaya da
    bütçe yalnız o zaman girer. ``budget`` açıkça verildiğinde o kazanır; ikisi de yoksa Run 3'ün
    koşumu olduğu gibi kalır - bütçesiz ve imzası Run 3'ün anahtarlarıyla.

    ``ambiguous`` altın soruların ardına kümenin belirsiz setini de katar ve netleştirmeyi açar
    (R5-12): soru soruldukça ölçülen şey cevap isabeti değil, tahmin etmek yerine sormaktır. Kümenin
    böyle bir seti yoksa koşacak belirsiz soru yoktur, yani tek cümle ve kod 2. ``narrate``
    gönderilen her altın cevabı bir kez daha yürütüp anlatır ve anlatıcı kaynaklarını sayar (R5-13).

    ``followups`` altın koşumun ardına kümenin ardışık soru zincirlerini de ``ask_payload``dan
    geçirir (R7-14): her tur gerçek konuşma deposundan geçer, ölçüm tur/zincir/bağlam doğruluğudur.
    Kümenin böyle bir seti yoksa koşulacak zincir yoktur, yani tek cümle ve kod 2.

    ``lang`` ölçümün dilidir (R8-11): ``en`` kümenin İngilizce altın setini koşar ve ekran ile
    report.md İngilizce konuşur; söylenmediğinde ``main``in ``--lang``dan çözdüğü dil okunur.
    Koşulan sorular kümenin verisidir - hangi dilin seti koşulduysa onun soruları ölçülür.
    """
    _utf8_stdout()
    lang = lang or _LANG
    ds, code = _dataset(dataset)
    if code:
        return code
    _dataset_line(ds, lang)
    # Belirsiz setin yokluğu veritabanından önce sorulur: eksik olan ölçümün tanımıdır, kurulu bir
    # dosya onu geri getirmez (R5-12).
    ambiguous_lines = ds.ambiguous() if ambiguous and ds else []
    if ambiguous and not ambiguous_lines:
        print(_t("cli.eval.no_ambiguous", lang))
        return EXIT_BAD_INPUT
    # Ardışık setin yokluğu da veritabanından önce sorulur: eksik olan ölçümün tanımıdır (R7-14).
    # Zincirler dilin kendi setidir (R8-12): küme İngilizce zincirleri taşımıyorsa Türkçe halidir.
    chains = ds.followups(lang) if followups and ds else []
    if followups and not chains:
        print(_t("cli.eval.no_followups", lang))
        return EXIT_BAD_INPUT
    budget = _or(budget, profile.prompt_limit if profile else None)
    db_path = _or(db_path, ds.db_path if ds else None, config.DB_PATH)
    index_dir = _or(index_dir, ds.index_dir if ds else None, config.INDEX_DIR)
    out_dir = _or(out_dir, ds.eval_out if ds else None, config.EVAL_OUT)
    if _db_missing(db_path):
        return _no_db(db_path, ds.name if ds else None, lang)
    schema_file = _schema_file(_or(schema_path, ds.schema_path if ds else None, FULL_SCHEMA))
    schema = _load_schema(schema_file, lang)
    if schema is None:
        return EXIT_BAD_INPUT
    # Ölçümün soruları dilin kendi setidir (R8-11): küme İngilizce kümeyi taşımıyorsa sorular
    # Türkçedir, yani ``en`` isteyen bir koşum yanlış dili ölçmüş olmaz - çevirisi olmayanı ölçemez.
    lines = ds.golden(lang) if ds else runner.load_golden()
    absent = _absent_tags(lines, tags)
    if absent:
        for tag in absent:
            print(_t("cli.eval.no_tag", lang, tag=tag))
        return EXIT_NO_TAG

    info = report.schema_info(schema_file, schema)
    print(_t("cli.eval.mode", lang, mode=mode))
    print(_t("cli.eval.schema", lang, path=info["path"], hash8=info["hash"][:8]) + "\n")
    rules = ds.rules() if ds else load_rules()
    executor = LocalExecutor(
        db_path=db_path, allowlist=doc.allowlist(schema), audit_path=audit_path, pii_schema=schema
    )
    try:
        context = _context(mode, executor, schema, rules, index_dir, ds)
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
        on_progress=lambda result: print(runner.progress_line(result, lang)),
        budget=budget,
        clarify=ambiguous,
        ambiguous=ambiguous_lines,
        lang=lang,
    )
    if results and all(result.outcome == "llm_error" for result in results):
        print(_t("cli.eval.no_endpoint", lang, n=len(results)) + "\n")
        return _llm_failed(results[0].reason, lang)
    narration = _narrate_results(results, executor, _narrator(llm)) if narrate else None
    # Ekrandaki skor report.json ile aynı paydayı taşır (R5-12): belirsiz satırlar altın setin
    # yerine geçmez, hemen altında basılan Doğruluk ile çelişmez.
    judged = runner.scored(results)
    passed = sum(1 for result in judged if result.outcome == "pass")
    kind, model = _client_kind(llm, profile)
    name = ds.name if ds else config.DEFAULT_DATASET
    followup_data = None
    if followups:
        followup_data = _run_followup_chains(
            ds, schema, rules, executor, profile, budget, index_dir, db_path, audit_path,
            out_dir, llm, kind, chains, mode, lang,
        )
    run_dir = report.write_report(
        results,
        out_dir,
        model=model,
        config={
            "backend": config.backend(),
            "llm": model,
            "embedder": _embedder_id(mode, index_dir),
            "fingerprint": _fingerprint(
                mode, kind, model, lines, results, schema, rules, name, budget, ambiguous
            ),
        },
        mode=mode,
        schema_info=info,
        dataset=name,
        profile=_profile_block(profile),
        narration=narration,
        followups=followup_data,
        followup_chains=chains if followups else None,
        lang=lang,
    )
    print(_t("cli.eval.score", lang, passed=passed, total=len(judged)))
    if ambiguous:
        print("\n" + _t("cli.eval.metrics_head", lang))
        for line in report.metrics_block(metrics.compute_metrics(results), lang):
            print(line)
        print()
    if followups:
        print("\n" + _t("cli.eval.followups_head", lang))
        for line in _followup_lines(followup_data, lang):
            print(line)
    print(_t("cli.eval.report", lang, path=run_dir / "report.md"))
    return 0


def _run_followup_chains(
    ds, schema, rules, executor, profile, budget, index_dir, db_path, audit_path, out_dir,
    llm, kind, chains, mode, lang,
) -> dict:
    """Ardışık zincirleri altın koşumla aynı yürütücü ve istemci üzerinden ``ask_payload``dan geçirir.

    Oturum ``open_session``dan değil doğrudan kurulur: altın koşumun şeması, kuralları, yürütücüsü ve
    istemcisi zaten vardır, ölçüm onların üstünde aynı dünyayı görmelidir. Konuşma deposu ve soru
    günlüğü ``out_dir/followups`` altında, yani her koşumda sil-baştan (R7-14).
    """
    from nl2sql.app.session import Session
    from nl2sql.eval.followups import followup_metrics, run_followups

    session = Session(
        dataset=ds, schema=schema, rules=rules, executor=executor, profile=profile,
        budget=budget, llm_kind=kind, index_dir=Path(index_dir), db_path=Path(db_path),
        audit_path=Path(audit_path),
        ask_log=Path(out_dir) / "followups" / "asks.jsonl",
        client_factory=lambda _mode: llm,
    )
    return followup_metrics(run_followups(session, chains, out_dir, mode=mode, lang=lang))


def _followup_lines(followup_data: dict, lang: str = config.DEFAULT_LANG) -> list[str]:
    """Konsolun ardışık soru bloğu (R7-14): zincir başına bir satır, sonda üç doğruluğun toplamı."""
    chains: dict[str, list[bool]] = {}
    for item in followup_data["items"]:
        chains.setdefault(item["id"], []).append(item["outcome"] == "pass")
    lines = [
        _t(
            "cli.eval.followup_chain",
            lang,
            id=chain_id,
            passed=sum(ok for ok in oks),
            total=len(oks),
            mark="✓" if all(oks) else "✗",
        )
        for chain_id, oks in chains.items()
    ]
    lines.append(
        _t(
            "cli.eval.followup_total",
            lang,
            turn=report.metric_percent(followup_data["turn_accuracy"], lang),
            chain=report.metric_percent(followup_data["chain_accuracy"], lang),
            context=report.metric_percent(followup_data["context_accuracy"], lang),
        )
    )
    return lines


def compare_modes(
    llm_factory,
    fresh: bool = False,
    db_path: str | Path | None = None,
    audit_path: str = config.AUDIT_LOG,
    out_dir: str | Path | None = None,
    index_dir: str | Path | None = None,
    schema_path: str | Path | None = None,
    repeat: int = 1,
    dataset: str | None = None,
    profile: ModelProfile | None = None,
    lang: str | None = None,
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

    ``repeat`` her modun kaç kez koşulacağıdır (R3-11): aynı imzada tekrarlandıkça yayılım
    ölçülür, karar ortalamalarla kurulur ve satır gürültüyü de söyler.

    ``dataset`` ``evaluate``ınkiyle aynı anlamı taşır (R4-4): üç mod da o kümenin sorularını,
    şemasını, kurallarını, veritabanını, indeksini ve rapor klasörünü kullanır.

    ``profile`` ``evaluate``ınkiyle aynı anlamı taşır (R4-10): üç mod da o pencerenin bütçesiyle
    koşar, yani bir kolun ``latest``i ancak aynı bütçeyle ölçüldüyse yeniden kullanılır.
    """
    _utf8_stdout()
    lang = lang or _LANG
    ds, code = _dataset(dataset)
    if code:
        return code
    _dataset_line(ds, lang)
    budget = profile.prompt_limit if profile else None
    db_path = _or(db_path, ds.db_path if ds else None, config.DB_PATH)
    index_dir = _or(index_dir, ds.index_dir if ds else None, config.INDEX_DIR)
    out_dir = _or(out_dir, ds.eval_out if ds else None, config.EVAL_OUT)
    if _db_missing(db_path):
        return _no_db(db_path, ds.name if ds else None, lang)
    schema_file = _schema_file(_or(schema_path, ds.schema_path if ds else None, FULL_SCHEMA))
    schema = _load_schema(schema_file, lang)
    if schema is None:
        return EXIT_BAD_INPUT
    lines = ds.golden(lang) if ds else runner.load_golden()
    info = report.schema_info(schema_file, schema)
    print(_t("cli.eval.schema", lang, path=info["path"], hash8=info["hash"][:8]) + "\n")
    rules = ds.rules() if ds else load_rules()
    name = ds.name if ds else config.DEFAULT_DATASET
    executor = LocalExecutor(
        db_path=db_path, allowlist=doc.allowlist(schema), audit_path=audit_path, pii_schema=schema
    )
    clients = {mode: llm_factory(mode) for mode in config.MODES}
    kind, model = _client_kind(clients[config.MODES[0]], profile)
    fingerprints = {
        mode: _mode_fingerprint(mode, kind, model, lines, schema, rules, name, budget)
        for mode in config.MODES
    }
    spaces = {mode: _embedder_id(mode, index_dir) for mode in config.MODES}
    stored = {mode: _mode_report(out_dir, mode) for mode in config.MODES}
    reused = {
        mode
        for mode in config.MODES
        # ASSUMPTION: R3-11 tekrarlı koşuda ``latest`` yeniden kullanılmaz; tek ölçümün yayılımı
        # yoktur, yani gürültüyü ölçmek isteyen bir koşu N ölçümün kendisini ister.
        if not fresh
        and repeat == 1
        and reusable(stored[mode], fingerprints[mode], spaces[mode])
    }
    if "rag" not in reused:
        # rag koşacaksa indeksi baştan denetle; iki mod boşuna koşulduktan sonra red edilmesin.
        try:
            _context("rag", executor, schema, rules, index_dir, ds)
        except (MissingIndexError, StaleIndexError) as exc:
            return _index_failed(str(exc))
    if repeat > 1:
        print(_t("cli.compare.repeat_line", lang, repeat=repeat) + "\n")

    reports = {mode: stored[mode] for mode in reused}
    for mode in config.MODES:
        if mode in reports:
            continue
        context = _context(mode, executor, schema, rules, index_dir, ds)
        runs = []
        for attempt in range(1, repeat + 1):
            print(
                _t("cli.compare.running_repeat", lang, mode=mode, attempt=attempt, repeat=repeat)
                if repeat > 1
                else _t("cli.compare.running", lang, mode=mode)
            )
            results = runner.run_eval(
                lambda: clients[mode],
                executor,
                golden=lines,
                schema=schema,
                mode=mode,
                context=context,
                budget=budget,
                lang=lang,
            )
            if results and all(result.outcome == "llm_error" for result in results):
                print(_t("cli.eval.no_endpoint", lang, n=len(results)) + "\n")
                return _llm_failed(results[0].reason, lang)
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
                dataset=name,
                profile=_profile_block(profile),
                lang=lang,
            )
            runs.append(_mode_report(out_dir, mode))
        reports[mode] = runs

    comparison = build_compare(reports, doc.estimate_tokens(doc.full_text(schema)), reused, lang)
    run_dir = write_compare(comparison, Path(out_dir) / "compare")
    print()
    for mode in config.MODES:
        print(_compare_line(mode, comparison["modes"][mode], lang))
    print(f"\n{comparison['verdict']['line']}")
    print(_t("cli.eval.report", lang, path=run_dir / "report.md"))
    return 0


def compare_models_cmd(
    models: list[str],
    modes: list[str] | None = None,
    dataset: str | None = None,
    llm_kind: str = DEFAULT_LLM,
    repeat: int = 1,
    models_file: str | Path | None = None,
    db_path: str | Path | None = None,
    audit_path: str = config.AUDIT_LOG,
    out_dir: str | Path | None = None,
    index_dir: str | Path | None = None,
    lang: str | None = None,
    ping=llm.ping,
) -> int:
    """Model x mod hücrelerini aynı sorularda koşar, tek model-karşılaştırma raporu yazar (R4-13).

    ``models`` profil adlarıdır ve verildikleri sırayla koşulur; her model kendi penceresiyle
    (``profile.prompt_limit``) ölçer. ``--llm openai``da modelden önce uç nokta yoklanır: kapıysa
    model ``skipped``a sebebiyle yazılır ve hiçbir hücresi olmaz, açıksa her mod x tekrar
    ``runner.run_eval``den geçer; profilin anahtar değişkeni tanımsızsa sebep kapalı uç noktanınki
    değil cümlenin kendisidir (R4-10). ``--llm fake`` yoklamayı atlar ve altın kaydı aynı bütçeyle
    oynatır, yani sahte bir karşılaştırma bile hangi modun hangi pencereye sığdığını gösterir.

    ``modes`` söylenmediğinde ``config.COMPARE_MODEL_MODES``; ``dataset`` ``evaluate``ınkiyle aynı
    anlamı taşır (R4-4). Hiçbir model koşmadıysa rapor yazılmaz ve kod 3 döner; değilse hücre
    satırları, atlananların ⚠ satırları ve rapor yolu basılır. ``repeat`` R3-11 kuralına uyar: 1'den
    küçükse hiçbir uç nokta yoklanmadan, hiçbir hücre koşmadan ve hiçbir dosya yazmadan kod 2 döner.
    """
    _utf8_stdout()
    lang = lang or _LANG
    if repeat < 1:
        print(_t("cli.eval.bad_repeat", lang))
        return EXIT_BAD_INPUT
    ds, code = _dataset(dataset)
    if code:
        return code
    _dataset_line(ds, lang)
    modes = list(modes) if modes else list(config.COMPARE_MODEL_MODES)
    db_path = _or(db_path, ds.db_path if ds else None, config.DB_PATH)
    index_dir = _or(index_dir, ds.index_dir if ds else None, config.INDEX_DIR)
    out_dir = _or(out_dir, ds.eval_out if ds else None, config.EVAL_OUT)
    if _db_missing(db_path):
        return _no_db(db_path, ds.name if ds else None, lang)
    try:
        profiles = load_profiles(models_file or config.MODELS_PATH)
    except ProfileError as exc:
        print(exc)
        return EXIT_BAD_INPUT
    unknown = [model for model in models if model not in profiles]
    if unknown:
        print(
            f"Bilinmeyen model profili: {', '.join(unknown)} "
            f"(bilinenler: {', '.join(sorted(profiles))})"
        )
        return EXIT_BAD_INPUT
    schema = ds.schema() if ds else doc.load_schema()
    rules = ds.rules() if ds else load_rules()
    lines = ds.golden(lang) if ds else runner.load_golden()
    executor = LocalExecutor(
        db_path=db_path, allowlist=doc.allowlist(schema), audit_path=audit_path, pii_schema=schema
    )
    if "rag" in modes:
        # rag koşacaksa indeksi baştan denetle; hiçbir model boşuna koşulmasın (R2-9).
        try:
            _context("rag", executor, schema, rules, index_dir, ds)
        except (MissingIndexError, StaleIndexError) as exc:
            return _index_failed(str(exc))

    cells: dict[str, dict] = {}
    skipped: dict[str, str] = {}
    used: dict[str, ModelProfile] = {}
    for model in models:
        profile = profiles[model]
        if llm_kind == "openai":
            # Eksik anahtar değişkeni kapalı uç noktadan önce sorulur: tavsiyesi kendi cümlesidir,
            # açık bir sunucuya "GPU'da bu modeli açıp yeniden koşun" olmaz (R4-10, T151'in kapısı).
            reason = llm.key_missing_reason(profile.api_key_env)
            if not reason and ping(profile):
                reason = _t("cli.compare.model_skipped", lang, url=profile.base_url)
            if reason:
                skipped[model] = reason
                continue
        budget = profile.prompt_limit
        used[model] = profile
        cells[model] = {}
        for mode in modes:
            context = _context(mode, executor, schema, rules, index_dir, ds)
            client = make_client(llm_kind, mode, ds, profile)
            cells[model][mode] = [
                runner.run_eval(
                    lambda: client,
                    executor,
                    golden=lines,
                    schema=schema,
                    mode=mode,
                    context=context,
                    budget=budget,
                    lang=lang,
                )
                for _ in range(repeat)
            ]

    if not cells:
        for model, reason in skipped.items():
            print(f"⚠ {model}: {reason}")
        return EXIT_NO_CELLS
    report_data = compare_models.build_model_compare(
        cells,
        profiles=used,
        dataset=ds.name if ds else config.DEFAULT_DATASET,
        skipped=skipped,
        lang=lang,
    )
    path = compare_models.write_model_compare(report_data, out_dir)
    print()
    for line in compare_models.console_lines(report_data):
        print(line)
    print("\n" + _t("cli.eval.report", lang, path=path))
    return 0


def import_map(
    path: str | Path,
    llm_factory,
    accept: bool = False,
    mapping: str | Path | None = None,
    proposal_path: str | Path | None = None,
    out: str | Path = config.IMPORTED_PATH,
    lang: str | None = None,
) -> int:
    """Excel haritasının eşlemesini önerir, diske yazar; ``--accept`` ile şemaya dönüştürür (R3-2).

    ``lang`` ekranın dilidir (R8-11): çerçevenin satırları ``cli.import_map`` kataloğundan o dilde
    gelir; sayfa ve sütun adları müşterinin haritasından geldiği için olduğu gibi kalır.

    Model eşlemeyi önerir ama satırları hiç görmez: dönüşümü tüm çalışma kitabına koddan
    ``convert`` uygular. Modelin sözlükle çeliştiği sütun sessizce çözülmez, ekrana uyuşmazlık
    olarak çıkar; eşleme diskte kaldığı için kullanıcı elle düzeltip ``--mapping`` ile geri verir
    ve o yolda model bir daha aranmaz.
    """
    _utf8_stdout()
    source = Path(path)
    if not source.is_file():
        print(_t("cli.import_map.no_file", lang, path=path))
        return EXIT_BAD_INPUT
    try:
        preview = excel.read_workbook(source)
    # ASSUMPTION: openpyxl'in cümlesi verilen biçimi ve desteklenenleri sayar ama dosyayı saymaz;
    # kullanıcının neyi düzelteceği tek satırda anlaşılsın diye yolu da buraya ekliyoruz.
    except (OSError, zipfile.BadZipFile, excel.SheetError, InvalidFileException) as exc:
        print(_t("cli.common.error", lang, reason=f"{source}: {exc}"))
        return EXIT_BAD_INPUT

    proposal = mapping or _proposal_file(source, proposal_path)
    if mapping:
        chosen = _read_mapping(mapping, lang)
        if chosen is None:
            return EXIT_BAD_INPUT
        by = _t("cli.import_map.by_file", lang)
    else:
        chosen = excel.propose(preview, llm_factory(preview))
        _write_json(proposal, chosen)
        by = str(chosen["generated_by"])

    print(_t("cli.import_map.file", lang, path=source))
    for line in _mapping_lines(chosen, lang):
        print(line)
    for note in chosen.get("disagreements") or []:
        print(
            _t(
                "cli.import_map.disagreement",
                lang,
                **{key: value or NONE for key, value in note.items()},
            )
        )
    print("\n" + _t("cli.import_map.mapping", lang, path=proposal, by=by))

    if not accept:
        print(_t("cli.import_map.hint", lang))
        return 0
    report = excel.convert(source, chosen)
    _write_json(out, report["schema"])
    print(
        "\n"
        + _t(
            "cli.import_map.written",
            lang,
            path=out,
            tables=report["tables"],
            columns=report["columns"],
            skipped=len(report["skipped"]),
        )
    )
    for note in report["skipped"]:
        print(
            "     "
            + _t(
                "cli.import_map.skipped",
                lang,
                sheet=note["sheet"],
                row=note["row"],
                reason=note["reason"],
            )
        )
    return 0


def introspect_schema(
    out: str | Path = config.SKELETON_PATH,
    sample: bool = False,
    db_path: str | Path = config.DB_PATH,
    audit_path: str | Path = config.AUDIT_LOG,
    lang: str | None = None,
) -> int:
    """Veritabanını yoklayıp iskelet şemayı yazar; ``--sample`` kısa metin kolonlarına değer ipucu ekler (R3-4).

    İpucu yoksa iskelet yalnız yapı taşır: ad, tip, nullability ve fk. Anlamı Excel haritası sonra
    ekler (R3-5), o yüzden burada boş açıklamalar bir eksik değil. ``--sample``ın sorguları da
    LocalExecutor'dan geçer, yani politika ve denetim kaydı model sorgularıyla aynı kapıdan yürür.
    ``lang`` ekranın dilidir (R8-11): satır ``cli.introspect`` kataloğundan o dilde gelir.
    """
    _utf8_stdout()
    if config.backend() == "mssql":
        try:
            skeleton = introspect.mssql_skeleton()
        except introspect.IntrospectError as exc:
            print(_t("cli.common.error", lang, reason=str(exc)))
            return EXIT_BAD_INPUT
    else:
        if _db_missing(db_path):
            return _no_db(db_path, lang=lang)
        skeleton = introspect.sqlite_skeleton(db_path)
    if sample:
        # Allowlist yoklanan iskeletin kendisi: R3-14 gereği introspect bir ERP kopyasında
        # schema.json yazılmadan önce koşar, varsayılan liste o kopyanın tablolarını bilmez.
        executor = LocalExecutor(
            db_path=db_path,
            audit_path=audit_path,
            allowlist=doc.allowlist(skeleton),
            pii_schema=skeleton,
        )
        introspect.sample_hints(db_path, skeleton, executor)
    _write_json(out, skeleton)
    tables = skeleton["tables"]
    print(
        _t(
            "cli.introspect.written",
            lang,
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
    lang: str | None = None,
) -> int:
    """Excel haritası ile veritabanı iskeletini karşılaştırır; farkı diff.json + diff.md olarak yazar (R3-5).

    Veritabanı tarafı ya hazır bir iskelet dosyasından okunur (``db_schema``) ya da canlı yoklanır. Ekran
    bölüm bölüm sayıları, sonra iki çıktı yolunu söyler; fark yoksa "Fark yok." (R3-13). ``lang``
    ekranın dilidir (R8-11); bölüm başlıkları ``merge`` raporunun kendi satırlarıdır.
    """
    _utf8_stdout()
    excel_doc = _read_schema(excel_path, lang)
    if excel_doc is None:
        return EXIT_BAD_INPUT
    if db_schema:
        db_doc = _read_schema(db_schema, lang)
        source = str(db_schema)
    else:
        db_doc = _introspect_db(db_path, lang)
        source = _t("cli.map.live", lang, path=db_path)
    if db_doc is None:
        return EXIT_BAD_INPUT

    report = merge.diff_map(excel_doc, db_doc)
    merge.save_diff(report, json_out, md_out)

    print(_t("cli.map.excel", lang, path=excel_path))
    print(_t("cli.map.database", lang, source=source) + "\n")
    counts = [(title, len(report[key])) for key, title, _ in merge.SECTIONS if report.get(key)]
    if counts:
        for title, count in counts:
            print(f"{title}: {count}")
    else:
        print(_t("cli.diff_map.no_diff", lang))
    print(f"\nJSON: {json_out}")
    print(f"Markdown: {md_out}")
    return 0


def merge_map(
    excel_path: str | Path,
    db_schema: str | Path | None = None,
    db_path: str | Path = config.DB_PATH,
    out: str | Path = config.MERGED_PATH,
    lang: str | None = None,
) -> int:
    """Excel haritası ile veritabanı iskeletini tek şemada birleştirir ve ``out``a yazar (R3-5).

    Veritabanı tarafı varlığı, tipleri, nullability ve foreign keyleri taşır; Excel tarafı açıklamayı,
    değerleri ve modülü. Excel'in veritabanında olmayan tablosu buraya değil diff'in içine gider
    (R3-5), o yüzden merge-map diff-map'ın yerini almaz. Yazılan dosya ``eval --schema`` ile
    koşulabilir: ölçüm artık hangi şemayla yapıldıysa onunla yapılır. ``lang`` ekranın dilidir
    (R8-11): satırlar ``cli.merge_map`` kataloğundan o dilde gelir.
    """
    _utf8_stdout()
    excel_doc = _read_schema(excel_path, lang)
    if excel_doc is None:
        return EXIT_BAD_INPUT
    if db_schema:
        db_doc = _read_schema(db_schema, lang)
        source = str(db_schema)
    else:
        db_doc = _introspect_db(db_path, lang)
        source = _t("cli.map.live", lang, path=db_path)
    if db_doc is None:
        return EXIT_BAD_INPUT

    schema = merge.merge_map(excel_doc, db_doc)
    _write_json(out, schema)
    tables = schema["tables"]
    print(_t("cli.map.excel", lang, path=excel_path))
    print(_t("cli.map.database", lang, source=source) + "\n")
    print(
        _t(
            "cli.merge_map.written",
            lang,
            path=out,
            tables=len(tables),
            columns=sum(len(table["columns"]) for table in tables),
        )
    )
    return 0


def make_login_script(
    login: str = login_script.DEFAULT_LOGIN,
    schema_path: str | Path | None = None,
    out: str | Path = config.LOGIN_SCRIPT_PATH,
    dataset: str | None = None,
    lang: str | None = None,
) -> int:
    """Salt okunur MSSQL giriş betiğini üretir ve ``out``a yazar (R3-8).

    Allowlist ve PII kolonları okunan şemadan gelir; betiğin kendisi ``readonly_login_sql``de
    kurulur. Ekran kaç tablonun allowlist'te, kaç PII kolonunun reddedildiğini ve nereye
    yazıldığını söyler — parolanın yer tutucusu olduğu için dosya repoda durabilir.
    ``dataset`` sınırın hangi kümenin şemasından kurulacağını söyler (R4-14). ``lang`` ekranın
    dilidir (R8-11): satırlar ``cli.login`` kataloğundan o dilde gelir.
    """
    _utf8_stdout()
    ds, code = _dataset(dataset)
    if code:
        return code
    _dataset_line(ds, lang)
    schema_path = _or(schema_path, ds.schema_path if ds else None, config.SCHEMA_PATH)
    schema = doc.load_schema(schema_path)
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(login_script.readonly_login_sql(schema, login), encoding="utf-8")
    print(_t("cli.login.login", lang, login=login))
    print(_t("cli.login.allowlist", lang, tables=len(doc.allowlist(schema))))
    print(_t("cli.login.pii", lang, columns=len(pii.column_map(schema))))
    print(_t("cli.login.script", lang, path=out))
    return 0


def write_template(
    out: str | Path,
    dataset: str | None = None,
    lang: str | None = None,
) -> int:
    """Doldurulacak boş şablonu ``out``a yazar; ``--dataset`` Tablolar/Kolonlar'ı o kümenin şemasıyla doldurur (R8-12).

    Şablonun dili ``--lang``dır: sayfa adları, başlıklar, açılır listeler ve ``_bilgin``in ``lang``
    satırı birlikte o dile döner, yani dosya kendi başına okunabilir. İskelet yalnız yapı taşır -
    açıklamaları dolduracak kişi bilir (``introspect``in R3-4 ayrımı). Ekran kaç tablo ve kolonun
    hazır geldiğini söyler; boş şablonda ikisi de sıfırdır.
    """
    _utf8_stdout()
    ds, code = _dataset(dataset)
    if code:
        return code
    _dataset_line(ds, lang)
    skeleton = ds.schema() if ds else None
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(template.build_template(skeleton, lang or _LANG))
    tables = (skeleton or {}).get("tables") or []
    print(
        _t(
            "cli.template.written",
            lang,
            tables=len(tables),
            columns=sum(len(table.get("columns") or []) for table in tables),
            path=out,
        )
    )
    return 0


def user_add(
    name: str,
    role: str,
    business_role: str = config.DEFAULT_BUSINESS_ROLE,
    lang: str = "tr",
) -> int:
    """Yeni kullanıcı: parolayı iki kez sorar, uyuşmazsa hiçbir şey yazmadan çıkar (R6-8)."""
    _utf8_stdout()
    password = _ask_password(lang)
    if password is None:
        return EXIT_BAD_INPUT
    try:
        user = UserStore(config.app_db_path()).add_user(
            name, password, role, business_role=business_role
        )
    except UserError as exc:
        print(_user_error(exc, lang))
        return EXIT_BAD_INPUT
    print(t("cli.user.added", lang, username=user["username"], role=user["role"]))
    print(t("cli.user.added_business", lang, business=_business_label(user["business_role"])))
    return 0


def user_list(lang: str = "tr") -> int:
    """Bütün kullanıcılar: ad, rolleri, durum, son giriş; hiç yoksa ne yapılacağı söylenir (R6-8)."""
    _utf8_stdout()
    users = UserStore(config.app_db_path()).list_users()
    if not users:
        print(t("cli.user.no_users", lang))
        return 0
    print(
        format_table(
            Result(
                columns=[t(key, lang) for key in USER_COLUMN_KEYS],
                rows=[
                    (
                        user["username"],
                        user["role"],
                        _business_label(user["business_role"]),
                        _user_status(user, lang),
                        user["last_login_at"],
                    )
                    for user in users
                ],
                row_count=len(users),
            ),
            lang,
        )
    )
    return 0


def user_passwd(name: str, lang: str = "tr") -> int:
    """Kullanıcının parolasını değiştirir; eski oturumları store kendisi düşürür (R6-8)."""
    _utf8_stdout()
    store = UserStore(config.app_db_path())
    user = _user_by_name(store, name, lang)
    if user is None:
        return EXIT_BAD_INPUT
    password = _ask_password(lang)
    if password is None:
        return EXIT_BAD_INPUT
    try:
        store.update_user(user["id"], password=password)
    except UserError as exc:
        print(_user_error(exc, lang))
        return EXIT_BAD_INPUT
    print(t("cli.user.passwd", lang, username=user["username"]))
    return 0


def user_set(
    name: str,
    role: str | None = None,
    active: bool | None = None,
    business_role: str | None = None,
    lang: str = "tr",
) -> int:
    """Rolü, etkinliği ya da iş rolünü değiştirir; son etkin yöneticiyi store korur (R6-8, R7-16).

    ``lang`` ekranın dilidir (R8-10): satırlar ``cli.user`` kataloğundan o dilde gelir.
    """
    _utf8_stdout()
    store = UserStore(config.app_db_path())
    user = _user_by_name(store, name, lang)
    if user is None:
        return EXIT_BAD_INPUT
    try:
        updated = store.update_user(
            user["id"], **_given(role=role, active=active, business_role=business_role)
        )
    except UserError as exc:
        print(_user_error(exc, lang))
        return EXIT_BAD_INPUT
    if business_role is not None:
        print(
            t(
                "cli.user.set_business",
                lang,
                username=updated["username"],
                business=_business_label(updated["business_role"]),
            )
        )
        return 0
    print(
        t(
            "cli.user.set",
            lang,
            username=updated["username"],
            role=updated["role"],
            status=_user_status(updated, lang),
        )
    )
    return 0


def _business_label(value: str) -> str:
    """İş rolünün ekrandaki adı (R7-16): config listesinde yoksa kendi değeri yazılır."""
    return config.BUSINESS_ROLES.get(value, value)


def _user_status(user: dict, lang: str) -> str:
    """Etkinliğin ekrandaki sözü: ``etkin``/``pasif``, yani tablonun iki hali."""
    return t("cli.user.active" if user["active"] else "cli.user.inactive", lang)


def _user_error(exc: UserError, lang: str) -> str:
    """Reddin cümlesi: store anahtarı ve parametreleri taşır (R8-5), ekran kendi dilinde kurar."""
    return t(exc.key, lang, **exc.params)


def _ask_password(lang: str = "tr") -> str | None:
    """Parolayı iki kez sorar; uyuşmazlık bir yazım hatasıdır, yani cümle ve None (R6-8)."""
    password = getpass.getpass(t("cli.user.password", lang))
    if getpass.getpass(t("cli.user.password_repeat", lang)) != password:
        print(t("cli.user.password_mismatch", lang))
        return None
    return password


def _user_by_name(store: UserStore, name: str, lang: str = "tr") -> dict | None:
    """Adı kullanıcının ``id``sine çeviren okuma; yoksa reddin cümlesi ekrana çıkar."""
    user = store.get_user(name)
    if user is None:
        print(t("auth.user_not_found", lang))
    return user


def make_client(kind: str, mode: str = config.DEFAULT_EVAL_MODE, dataset=None, profile=None):
    """``--llm`` değerini istemciye çevirir: fake altın kaydı oynatır, openai config'teki endpoint'e gider.

    Sahte istemci oynatacağı kaydı moddan alır: ``rag`` aramadan geçerek, diğerleri şemadan.
    ``dataset`` verildiğinde kayıtlar o kümenin altın sorularıdır ve eşleşmeyen bir sorunun
    cevabı da kümenin kendi sorgusudur (R4-4) - başka bir kümenin tablosunu uydurmasın. Belirsiz
    soruları da küme taşır (R5-11); kümenin böyle bir dosyası yoksa sahte hiçbir soruyu sormaz.
    Ardışık soru zincirleri de kümenin dosyasıdır (R7-13); olmayan kümede sahte zincir tanımaz.
    Küme İngilizce altın kümeyi ve İngilizce zincirleri de taşıyorsa (R8-10) sahte hepsini birden
    oynatır - eşleşme soru metniyle olduğu için iki dilin kayıtları birbirinin üstüne yazmaz.

    ``profile`` ``--model``in profilidir (R4-10): openai istemcisi onun uç noktasından, model
    adından ve anahtar değişkeninden kurulur; anahtar tanımsızsa ``LLMError`` burada yükseltir.
    Sahte istemci profil tanımaz - oynatacağı kayıt hangisinin olduğuyla değişmez, bütçe değişir.
    """
    if kind == "fake":
        golden = dataset.golden() if dataset else runner.load_golden()
        if dataset and dataset.golden_en_path is not None:
            golden = [*golden, *dataset.golden("en")]
        chains = dataset.followups() if dataset else ()
        if dataset and dataset.followups_en_path is not None:
            chains = [*chains, *dataset.followups("en")]
        return fake.for_golden(
            golden,
            dataset.fake_fallback_sql if dataset else fake.FALLBACK_SQL,
            mode=mode,
            ambiguous=dataset.ambiguous() if dataset else (),
            followups=chains,
        )
    if profile is not None:
        return client_for(profile)
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


def _add_dataset_option(command: argparse.ArgumentParser, lang: str) -> None:
    """``--dataset``: komutun hiçbir varsayılanı config'de kalmaz, hepsi o kümenin tanımıdır (R4-14)."""
    command.add_argument(
        "--dataset",
        metavar="AD",
        help=_h("dataset", lang, default=config.DEFAULT_DATASET),
    )


def _add_model_options(command: argparse.ArgumentParser, lang: str) -> None:
    """``--model`` bir profil seçer (R4-10): uç nokta, model adı, anahtar değişkeni ve pencere.

    Söylenmediğinde koşum Run 3'ün halidir - ``NL2SQL_LLM_*`` ile kurulan uç nokta, bütçe yok.
    ``--models-file`` aynı profilin başka bir dosyadan okunmasıdır; testler kendi tmp dosyasını
    verir, böylece gerçek ``config/models.json``a ve içindeki anahtar değişkenlerine dokunulmaz.
    """
    command.add_argument(
        "--model",
        metavar="PROFIL",
        help=_h("model", lang, url=config.llm_settings().base_url),
    )
    command.add_argument(
        "--models-file",
        metavar="DOSYA.json",
        help=_h("models_file", lang, path=config.MODELS_PATH),
    )


def _add_embed_options(command: argparse.ArgumentParser, lang: str) -> None:
    """``build-index`` ile ``eval-retrieval``ın ortak embedder bayrakları (R3-9).

    ``--embed-model`` model adını doğrudan söyler: aynı sunucuda duran iki modeli (embeddinggemma,
    bge-m3) ölçmek için ortam değişkeni değiştirmek yerine komutun kendisi yazılır.
    """
    command.add_argument(
        "--embed",
        default=DEFAULT_EMBED,
        help=_h("embed", lang),
    )
    command.add_argument(
        "--embed-model",
        metavar="AD",
        help=_h("embed_model", lang),
    )


def _embed_arg(args, lang: str | None = None) -> str | None:
    """``--embed`` ile ``--embed-model`` tek embedder metnine döner: ``fake:64``, ``openai:bge-m3``.

    Model adı bir uç nokta kaynağı ister; ``fake``in soneki vektör genişliği olduğu için
    ``--embed fake --embed-model bge-m3``in anlatmak istediği bir şey yok.
    """
    value = f"{args.embed}:{args.embed_model}" if args.embed_model else str(args.embed)
    if not EMBED_ID.match(value):
        print(_t("cli.index.bad_embed", lang, value=value))
        return None
    return value


def _dataset(name: str | None) -> tuple[datasets.Dataset | None, int]:
    """``--dataset`` adı yüklenir; ad verilmediyse ``(None, 0)``, yani komut config'in sabitleriyle yürür.

    Ad verilmeyen hal küme klasörünü okumaz: ``synthetic_erp``nin tohumu ve yolları config'dekiyle
    aynı değerler, o yüzden küme tanımı olmayan bir kurulum da çalışmaya devam eder (R4-14).
    Bilinmeyen ad kullanıcının kendi düzelteceği bir eksikliktir (Delight 3) — cümleyi ``datasets``
    kurar, bilinenleri de sayar.
    """
    if not name:
        return None, 0
    try:
        return datasets.load_dataset(name), 0
    except datasets.DatasetError as exc:
        print(exc)
        return None, EXIT_BAD_INPUT


def _dataset_line(ds: datasets.Dataset | None, lang: str | None = None) -> None:
    """Kümeyi kendisi seçen komut hangi dünyayla çalıştığını ilk satırda söyler (R4-14, R8-11)."""
    if ds:
        print(_t("cli.common.dataset_line", lang, display_name=ds.display_name, name=ds.name))


def _profile_arg(args) -> tuple[ModelProfile | None, int]:
    """``--model`` profili ``--models-file``dan okunur; ad söylenmediyse ``(None, 0)``, yani Run 3'ün ucu.

    Bilinmeyen ad, okunamayan dosya ya da içinde boşluk bırakmayan profil kullanıcının kendi
    düzelteceği bir eksikliktir (Delight 3): cümleyi ``llm`` kurar, bilinenleri de sayarak.
    """
    if not args.model:
        return None, 0
    try:
        return get_profile(args.model, args.models_file), 0
    except ProfileError as exc:
        print(exc)
        return None, EXIT_BAD_INPUT


def _auto_inputs(ds: datasets.Dataset | None) -> tuple:
    """``--mode auto``nun girdileri: küme verildiyse şema, kural, indeks, tarih ve ad onun tanımıdır (R4-4)."""
    if ds:
        return ds.schema(), ds.rules(), ds.index_dir, ds.as_of, ds.name
    return doc.load_schema(), load_rules(), config.INDEX_DIR, config.AS_OF, None


def _eval_out(ds: datasets.Dataset | None, mode: str | None = None) -> Path:
    """Koşunun rapor klasörü: kümenin ``eval_out``u, R2-12 gereği modun kendi alt klasörüyle (R4-4)."""
    base = Path(ds.eval_out if ds else config.EVAL_OUT)
    return base / mode if mode else base


def _or(value, *fallbacks):
    """İlk verilen değer kazanır: açık parametre > kümenin varsayılanı > config."""
    for candidate in (value, *fallbacks):
        if candidate is not None:
            return candidate
    return None


def _given(**values) -> dict:
    """argparse yalnız verildiğini geçirir; verilmeyen, kümenin kendi varsayılanına bırakılır."""
    return {key: value for key, value in values.items() if value is not None}


def _h(key: str, lang: str, **params) -> str:
    """Yardımcı satırın kataloğu: her ``help``/``description``/``epilog`` ``cli.help.<key>``dır (R8-5)."""
    return t(f"cli.help.{key}", lang, **params)


def _scan_lang(argv: list[str]) -> str:
    """Parserı kurmadan önce dil: ``--lang X`` > ``NL2SQL_LANG`` > tr (R8-5).

    Argparse bayrağı zaten doğrular; ön tarama yalnız yardımın hangi dilde kurulacağını seçer, o
    yüzden tanınmayan bir değerde susar ve ortam/varsayılan sırasına düşer.
    """
    for i, arg in enumerate(argv):
        if arg == "--lang" and i + 1 < len(argv):
            found = normalize_lang(argv[i + 1])
        elif arg.startswith("--lang="):
            found = normalize_lang(arg.split("=", 1)[1])
        else:
            continue
        if found:
            return found
    return config.lang()


def _lang_parent(lang: str) -> argparse.ArgumentParser:
    """``--lang {tr,en}``: üst parserın ve her alt komunun ortak ebeveyni (R8-5).

    Varsayılan çözülmüş dildir, böylece bayrak verilmediğinde de ``args.lang`` komuta çözümü taşır.
    """
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument(
        "--lang", choices=list(config.LANGUAGES), default=lang, help=_h("lang", lang)
    )
    return parent


def build_parser(lang: str) -> argparse.ArgumentParser:
    """Komut ağacı; her ``help``/``description``/``epilog`` ``cli.help`` anahtarlarından ``lang``da gelir (R8-5)."""
    lang_parent = _lang_parent(lang)
    parser = argparse.ArgumentParser(
        prog="python -m nl2sql", description=_h("description", lang), parents=[lang_parent]
    )
    commands = parser.add_subparsers(dest="command", required=True)

    build_cmd = commands.add_parser(
        "build-db", help=_h("build_db", lang), parents=[lang_parent]
    )
    build_cmd.add_argument(
        "--seed",
        type=int,
        help=_h("seed", lang, seed=config.SEED),
    )
    _add_dataset_option(build_cmd, lang)

    index_cmd = commands.add_parser(
        "build-index", help=_h("build_index", lang), parents=[lang_parent]
    )
    _add_embed_options(index_cmd, lang)
    _add_dataset_option(index_cmd, lang)

    retrieval_cmd = commands.add_parser(
        "eval-retrieval", help=_h("eval_retrieval", lang), parents=[lang_parent]
    )
    _add_embed_options(retrieval_cmd, lang)
    _add_dataset_option(retrieval_cmd, lang)
    retrieval_cmd.add_argument(
        "--k", type=int, default=config.SEARCH_K, help=_h("k", lang)
    )
    # Varsayılan bilinçli olarak None: verilmeyen bayrak ``eval_retrieval``in kendi varsayılanına
    # (off) düşer, yani ``--summaries`` yazılmayan bir koşumun raporu bugünkü raporun aynısıdır.
    retrieval_cmd.add_argument(
        "--summaries",
        choices=("on", "off"),
        default=None,
        help=_h("summaries", lang),
    )

    import_cmd = commands.add_parser(
        "import-map", help=_h("import_map", lang), parents=[lang_parent]
    )
    import_cmd.add_argument("file", metavar="HARITA.xlsx", help=_h("map_file", lang))
    import_cmd.add_argument(
        "--llm", choices=LLMS, default=DEFAULT_LLM, help=_h("llm", lang)
    )
    import_cmd.add_argument(
        "--accept",
        action="store_true",
        help=_h("accept", lang),
    )
    import_cmd.add_argument(
        "--mapping",
        metavar="DOSYA.json",
        help=_h("mapping", lang),
    )
    import_cmd.add_argument(
        "--out",
        default=str(config.IMPORTED_PATH),
        help=_h("out_schema", lang),
    )

    introspect_cmd = commands.add_parser(
        "introspect", help=_h("introspect", lang), parents=[lang_parent]
    )
    introspect_cmd.add_argument(
        "--out",
        default=str(config.SKELETON_PATH),
        help=_h("out_skeleton", lang),
    )
    introspect_cmd.add_argument(
        "--sample",
        action="store_true",
        help=_h("sample", lang, n=config.SAMPLE_HINT_N),
    )

    diff_cmd = commands.add_parser(
        "diff-map", help=_h("diff_map", lang), parents=[lang_parent]
    )
    diff_cmd.add_argument(
        "--excel", required=True, metavar="SEMA.json", help=_h("excel", lang)
    )
    db_source = diff_cmd.add_mutually_exclusive_group(required=True)
    db_source.add_argument("--db", action="store_true", help=_h("db_live", lang))
    db_source.add_argument(
        "--db-schema", metavar="ISKELET.json", help=_h("db_schema", lang)
    )

    merge_cmd = commands.add_parser(
        "merge-map", help=_h("merge_map", lang), parents=[lang_parent]
    )
    merge_cmd.add_argument(
        "--excel", required=True, metavar="SEMA.json", help=_h("excel", lang)
    )
    merge_source = merge_cmd.add_mutually_exclusive_group(required=True)
    merge_source.add_argument("--db", action="store_true", help=_h("db_live_merge", lang))
    merge_source.add_argument(
        "--db-schema", metavar="ISKELET.json", help=_h("db_schema_merge", lang)
    )
    merge_cmd.add_argument(
        "--out",
        default=str(config.MERGED_PATH),
        help=_h("out_merged", lang),
    )

    login_cmd = commands.add_parser(
        "make-login-script", help=_h("make_login_script", lang), parents=[lang_parent]
    )
    login_cmd.add_argument(
        "--login",
        default=login_script.DEFAULT_LOGIN,
        help=_h("login", lang),
    )
    _add_dataset_option(login_cmd, lang)

    template_cmd = commands.add_parser(
        "template", help=_h("template", lang), parents=[lang_parent]
    )
    template_cmd.add_argument("--out", required=True, help=_h("template_out", lang))
    _add_dataset_option(template_cmd, lang)

    ask_cmd = commands.add_parser(
        "ask", help=_h("ask", lang), parents=[lang_parent]
    )
    ask_cmd.add_argument("question", help=_h("question", lang))
    ask_cmd.add_argument(
        "--llm", choices=LLMS, default=DEFAULT_LLM, help=_h("llm", lang)
    )
    ask_cmd.add_argument(
        "--mode",
        choices=(*config.MODES, "auto"),
        default="auto",
        help=_h("mode", lang),
    )
    ask_cmd.add_argument(
        "--json",
        action="store_true",
        help=_h("json", lang),
    )
    ask_cmd.add_argument(
        "--choice",
        metavar=_h("choice_metavar", lang),
        help=_h("choice", lang),
    )
    conversation = ask_cmd.add_mutually_exclusive_group()
    conversation.add_argument(
        "--conversation",
        metavar="ID",
        help=_h("conversation", lang),
    )
    conversation.add_argument(
        "--new",
        action="store_true",
        help=_h("new", lang),
    )
    _add_model_options(ask_cmd, lang)
    _add_dataset_option(ask_cmd, lang)

    serve_cmd = commands.add_parser(
        "serve", help=_h("serve", lang), parents=[lang_parent]
    )
    serve_cmd.add_argument(
        "--host",
        default=config.SERVE_HOST,
        help=_h("host", lang, hosts=", ".join(LOOPBACK_HOSTS)),
    )
    serve_cmd.add_argument(
        "--port", type=int, default=config.SERVE_PORT, help=_h("port", lang)
    )
    serve_cmd.add_argument(
        "--llm", choices=LLMS, default=DEFAULT_LLM, help=_h("llm", lang)
    )
    _add_model_options(serve_cmd, lang)
    _add_dataset_option(serve_cmd, lang)
    # R7-26: gizli - görsel inceleme ve duman testinin kendi seçeneği, kullanıcıya anlatılacak bir
    # ayar değil; yardımı bu yüzden basılmaz.
    serve_cmd.add_argument("--db-probe-file", default=None, help=argparse.SUPPRESS)

    # R6-8: kullanıcı hesapları parolayı asla komut satırından almaz — iki kez sorulur, yani
    # kabuk geçmişine düşmez. Komut login istemez: kendi makinesinin dosyasını kendi yönetir.
    user_cmd = commands.add_parser(
        "user", help=_h("user", lang), parents=[lang_parent]
    )
    user_sub = user_cmd.add_subparsers(dest="user_command", required=True)
    user_add_cmd = user_sub.add_parser(
        "add", help=_h("user_add", lang), parents=[lang_parent]
    )
    user_add_cmd.add_argument("name", metavar="AD")
    user_add_cmd.add_argument(
        "--role",
        choices=("admin", "user"),
        default="user",
        help=_h("role", lang),
    )
    user_add_cmd.add_argument(
        "--business-role",
        choices=tuple(config.BUSINESS_ROLES),
        default=config.DEFAULT_BUSINESS_ROLE,
        help=_h("business_role", lang),
    )
    user_sub.add_parser("list", help=_h("user_list", lang), parents=[lang_parent])
    user_passwd_cmd = user_sub.add_parser(
        "passwd", help=_h("user_passwd", lang), parents=[lang_parent]
    )
    user_passwd_cmd.add_argument("name", metavar="AD")
    user_set_cmd = user_sub.add_parser(
        "set", help=_h("user_set", lang), parents=[lang_parent]
    )
    user_set_cmd.add_argument("name", metavar="AD")
    user_change = user_set_cmd.add_mutually_exclusive_group(required=True)
    user_change.add_argument("--role", choices=("admin", "user"), help=_h("new_role", lang))
    user_change.add_argument(
        "--deactivate", action="store_true", help=_h("deactivate", lang)
    )
    user_change.add_argument("--activate", action="store_true", help=_h("activate", lang))
    user_change.add_argument(
        "--business-role", choices=tuple(config.BUSINESS_ROLES), help=_h("new_business_role", lang)
    )

    eval_cmd = commands.add_parser("eval", help=_h("eval", lang), parents=[lang_parent])
    eval_cmd.add_argument(
        "--llm", choices=LLMS, default=DEFAULT_LLM, help=_h("llm", lang)
    )
    eval_cmd.add_argument(
        "--only", nargs="+", metavar="Q03", help=_h("only", lang)
    )
    eval_cmd.add_argument(
        "--tag",
        nargs="+",
        metavar="archive",
        help=_h("tag", lang),
    )
    eval_cmd.add_argument(
        "--mode",
        choices=(*config.MODES, "auto"),
        default=config.DEFAULT_EVAL_MODE,
        help=_h("eval_mode", lang),
    )
    eval_cmd.add_argument(
        "--compare",
        action="store_true",
        help=_h("compare", lang),
    )
    eval_cmd.add_argument(
        "--fresh", action="store_true", help=_h("fresh", lang)
    )
    eval_cmd.add_argument(
        "--models",
        metavar="A,B",
        help=_h("models", lang),
    )
    eval_cmd.add_argument(
        "--modes",
        metavar="M1,M2",
        help=_h("modes", lang, modes=",".join(config.COMPARE_MODEL_MODES)),
    )
    eval_cmd.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help=_h("repeat", lang),
    )
    eval_cmd.add_argument(
        "--schema",
        default=FULL_SCHEMA,
        metavar="DOSYA|full|skeleton",
        help=_h("schema", lang),
    )
    eval_cmd.add_argument(
        "--ambiguous",
        action="store_true",
        help=_h("ambiguous", lang),
    )
    eval_cmd.add_argument(
        "--narrate",
        action="store_true",
        help=_h("narrate", lang),
    )
    eval_cmd.add_argument(
        "--followups",
        action="store_true",
        help=_h("followups", lang),
    )
    _add_model_options(eval_cmd, lang)
    _add_dataset_option(eval_cmd, lang)

    return parser


def _t(key: str, lang: str | None = None, **params) -> str:
    """Kataloğun satırı, komutun dilinde: ``lang`` None ise ``main``in çözdüğü dil okunur (R8-11).

    Komutların kwargs sözleşmesi testlerde donuk (R8-5: ``main`` komuta yalnız kullanıcının
    verdiği argümanları iletir), o yüzden ``--lang``ın yolu imza değil ``_LANG``dır; ``lang``
    parametresi komutu doğrudan çağıranın (testler, betikler) açıkça verebildiği yerler için durur.
    """
    return t(key, lang or _LANG, **params)


def _resolved_lang(command_line):
    """``main``in argv'den çözdüğü dil, koşum boyunca komutların okuduğu modül hali (R8-11).

    Çözüm ``main``in argümanı değil yan etkisidir: ``main``den çıkınca geri alınır, yani ``main``i
    hiç çağırmayan bir koşan (web, onboard, testler) tr'de kalır.
    """

    @functools.wraps(command_line)
    def wrapped(argv: list[str] | None = None) -> int:
        global _LANG
        previous, _LANG = _LANG, _scan_lang(list(sys.argv[1:] if argv is None else argv))
        try:
            return command_line(argv)
        finally:
            _LANG = previous

    return wrapped


@_resolved_lang
def main(argv: list[str] | None = None) -> int:
    """argparse: ``build-db`` | ``ask`` | ``eval``; seçilen komutun işlevini çağırır.

    Dili argv'den önce tarar (``--lang`` > ``NL2SQL_LANG`` > tr), parserı o dilde kurar; çözülen dil
    ``args.lang`` olarak kendisinin, ``_LANG`` olarak komutların ekran satırlarının dilidir (R8-5,
    R8-11).
    """
    argv = list(sys.argv[1:] if argv is None else argv)
    lang = _scan_lang(argv)
    parser = build_parser(lang)
    args = parser.parse_args(argv)
    # ASSUMPTION: komutların argümanı dil taşımaz; çözülen dil buradan komuta ``args.lang`` ile kalır.
    # Üst düzey ``--lang``ı alt komanın varsayılanı ezebildiği için argparse'ın değerine değil ön
    # taramanın çözümüne güvenilir (R8-5).
    args.lang = lang
    if args.command == "build-db":
        return build_database(**_given(seed=args.seed, dataset=args.dataset))
    if args.command == "build-index":
        embed = _embed_arg(args, args.lang)
        if not embed:
            return EXIT_BAD_INPUT
        return build_index(embed=embed, **_given(dataset=args.dataset))
    if args.command == "eval-retrieval":
        embed = _embed_arg(args, args.lang)
        if not embed:
            return EXIT_BAD_INPUT
        return eval_retrieval(
            embed=embed,
            k=args.k,
            **_given(
                dataset=args.dataset,
                summaries=None if args.summaries is None else args.summaries == "on",
            ),
        )
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
    if args.command == "make-login-script":
        return make_login_script(login=args.login, **_given(dataset=args.dataset))
    if args.command == "template":
        return write_template(out=args.out, lang=args.lang, **_given(dataset=args.dataset))
    if args.command == "ask":
        from nl2sql.app.conversations import ConversationNotFound

        if args.json:
            try:
                return _ask_json(args)
            except ConversationNotFound:
                print(t("conversations.not_found", args.lang))
                return EXIT_BAD_INPUT
        ds, code = _dataset(args.dataset)
        if code:
            return code
        profile, code = _profile_arg(args)
        if code:
            return code
        # R4-14: küme satırı her halükarda ilk satırdır; auto çözümü NO_INDEX_NOTE basabildiği için
        # buraya alındı ve ask() kendisinin basmadığını ``dataset_line`` ile öğreniyor.
        _dataset_line(ds, args.lang)
        # ASSUMPTION: "ask'ın varsayılanı auto" komutun varsayılanıdır (argparse default); buradaki
        # çözümleme istemciye de çözülmüş modu vermek için — sahte kayıt rag ile diğerlerinde farklı
        # oynar. ask() fonksiyonunun kendi varsayılanı "full" kalır, doğrudan çağıranı etkilemesin.
        mode, estimate = args.mode, None
        try:
            if mode == "auto":
                mode, estimate = resolve_auto(
                    *_auto_inputs(ds), max_tokens=_auto_limit(profile), lang=args.lang
                )
            store, conversation_id = _conversation(args)
            return ask(
                question=args.question,
                llm=make_client(args.llm, mode, ds, profile),
                mode=mode,
                estimate=estimate,
                dataset_line=False,
                conversations=store,
                conversation_id=conversation_id,
                lang=args.lang,
                **_given(dataset=args.dataset, profile=profile, choice=args.choice),
            )
        except ForeignIndexError as exc:
            # R4-8: yabancı bir indeksin çözümü full'a düşmek değil, kendi kümesini kurmaktır.
            return _index_failed(str(exc))
        except LLMError as exc:
            # R4-10: profilin gösterdiği anahtar değişkeni tanımsıysa koşacak bir uç nokta yoktur;
            # düzeltmesi kullanıcının elinde olduğu için iz dökümü değil tek satır ve kod 2.
            print(exc)
            return EXIT_BAD_INPUT
        except ConversationNotFound:
            # R7-9: --conversation bilinmeyen bir kimlik söylüyorsa düzeltmesi kullanıcının elinde:
            # konuşma yok, başkasının ya da başka bir kümede - tek cümle ve kod 2.
            print(t("conversations.not_found", args.lang))
            return EXIT_BAD_INPUT
    if args.command == "serve":
        return serve(
            host=args.host,
            port=args.port,
            llm_kind=args.llm,
            **_given(
                dataset=args.dataset,
                model=args.model,
                models_file=args.models_file,
                db_probe_file=args.db_probe_file,
            ),
        )
    if args.command == "user":
        if args.user_command == "list":
            return user_list(args.lang)
        if args.user_command == "add":
            return user_add(args.name, args.role, args.business_role, args.lang)
        if args.user_command == "passwd":
            return user_passwd(args.name, args.lang)
        return user_set(
            args.name,
            role=args.role,
            active=None if not (args.activate or args.deactivate) else args.activate,
            business_role=args.business_role,
            lang=args.lang,
        )
    if args.modes and not args.models:
        print(_t("cli.eval.modes_without_models"))
        return EXIT_BAD_INPUT
    if args.mode == "auto":
        print(_t("cli.eval.no_auto"))
        return EXIT_BAD_INPUT
    if args.compare and args.ambiguous:
        print(_t("cli.eval.ambiguous_compare"))
        return EXIT_BAD_INPUT
    # ASSUMPTION: --ambiguous/--followups setleri bir veri kümesinden okunur; --dataset söylenmemişse
    # ölçülen dünya adıyla da söylenir, yani config'in sabitleriyle aynı değerleri taşıyan sentetik ERP
    # (R5-12, R7-14) — sahte kayıt belirsiz soruları ve zincirleri ancak küme tanınırsa oynatır.
    dataset = args.dataset or (
        config.DEFAULT_DATASET if (args.ambiguous or args.followups) else None
    )
    ds, code = _dataset(dataset)
    if code:
        return code
    profile, code = _profile_arg(args)
    if code:
        return code
    # ``--schema`` söylenmediyse küme kendi şemasını ölçer; ``full`` onun önüne geçmez (R4-4).
    schema = None if dataset and args.schema == FULL_SCHEMA else args.schema
    try:
        if args.compare and args.models:
            # R4-13: ``--models`` model x mod karşılaştırmasıdır; Run 2/3 mod karşılaştırması
            # (adsız ``--compare``) aşağıda olduğu gibi kalır.
            return compare_models_cmd(
                models=[name.strip() for name in args.models.split(",") if name.strip()],
                modes=[name.strip() for name in args.modes.split(",") if name.strip()]
                if args.modes
                else None,
                dataset=dataset,
                llm_kind=args.llm,
                repeat=args.repeat,
                models_file=args.models_file,
            )
        if args.compare:
            if args.repeat < 1:
                print(_t("cli.eval.bad_repeat"))
                return EXIT_BAD_INPUT
            return compare_modes(
                lambda mode: make_client(args.llm, mode, ds, profile),
                fresh=args.fresh,
                repeat=args.repeat,
                **_given(schema_path=schema, dataset=dataset, profile=profile),
            )
        return evaluate(
            llm=make_client(args.llm, args.mode, ds, profile),
            only=args.only,
            tags=args.tag,
            mode=args.mode,
            out_dir=_eval_out(ds, args.mode),
            ambiguous=args.ambiguous,
            narrate=args.narrate,
            followups=args.followups,
            **_given(schema_path=schema, dataset=dataset, profile=profile),
        )
    except LLMError as exc:
        print(exc)
        return EXIT_BAD_INPUT


def _ask_json(args) -> int:
    """``ask --json``: ekranın yerini AskPayload alır (R5-14); stdout'da yalnız JSON durur.

    Oturum ``open_session``dan geçer, yani eksik veritabanı, bilinmeyen küme ya da profil ve eksik
    anahtar cümlesini ve kodunu oradan alır; ne küme satırı ne mod satırı basılır, auto'nun düşüş
    notu payload'ın ``notes``unda kalır. Yollar çağrı anında config'den okunur, yani test kendi tmp
    yolunu monkeypatch edebilir (``open_session``ın varsayılanları import'da bağlanıyor).

    Dil ``--lang``dır (R8-10): payload'ın kendi cümleleri o dildedir, anahtar seti değişmez.
    """
    # R5-1: ``ask --json`` ile ``POST /api/ask`` aynı kapı; nl2sql.app içe yalnız burada girilir.
    from nl2sql.app.ask import ask_payload
    from nl2sql.app.session import SessionError, open_session

    _utf8_stdout()
    try:
        session = open_session(
            dataset=args.dataset,
            model=args.model,
            llm=args.llm,
            models_file=args.models_file,
            audit_path=config.AUDIT_LOG,
            ask_log=config.ASK_LOG,
        )
    except SessionError as exc:
        print(exc)
        return exc.exit_code
    # R6-9: makinedeki oturumun sahibi soruyu sorandır; adı hem günlüğe hem denetim satırlarına karışır.
    # R7-9: ``--new``/``--conversation`` verilmişse payload bir konuşmanın turudur (conversation_id/turn/context).
    # Konuşmanın sahibi ekranla aynı: NULL (M21 review 2) - iki uç aynı threadin turlarını sürdürür.
    store, conversation_id = _conversation(args)
    payload = ask_payload(
        session,
        args.question,
        mode=args.mode,
        choice=args.choice,
        source=JSON_SOURCE,
        username=getpass.getuser(),
        conversations=store,
        conversation_id=conversation_id,
        owner=None,
        lang=args.lang,
    )
    # SQL Server returns DECIMAL/MONEY as Decimal and dates as date objects (SQLite never did); the API
    # side gets the same conversion from FastAPI's encoder.
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_value))
    return 0 if payload["status"] in JSON_OK else 1


def _json_value(value):
    """JSON form of a database value json cannot write: Decimal -> number, anything else -> text."""
    return float(value) if isinstance(value, Decimal) else str(value)


def serve(
    host: str = config.SERVE_HOST,
    port: int = config.SERVE_PORT,
    llm_kind: str = DEFAULT_LLM,
    dataset: str | None = None,
    model: str | None = None,
    models_file: str | Path | None = None,
    db_probe_file: str | Path | None = None,
    lang: str | None = None,
) -> int:
    """``serve``: oturumu bir kez kurar, API'yi loopback'e bağlar (R5-15).

    Oturumun kurulmuş olması adresin serbest olduğu anlamına gelmez: hangi veriyi gördüğü belli
    olan bir oturum, dinlemeye başlamadan önce reddedilir. Açılış satırı hangi dünyanın hangi
    modelle ve hangi kaynakla sunulduğunu söyler - ekranın kendisi henüz açılmamıştır.

    Küme söylenmediğinde sunulan dünya adıyla da söylenir (`--ambiguous`ın yaptığı gibi): çipin
    adı başka sunulan başka olmasın - belirsiz sorular, altın kayıt, ``as_of`` ve indeks kümden
    gelir, yani küme tanınmadan sahte istemci R5-11'in kartını hiç açmaz.

    R6-7: sunulan uygulama her zaman bir kullanıcı deposunun üstünde durur, yani oturum ister.
    Kullanıcı yoksa dinlemeye başlamaz: ya geliştirme yöneticisi açılır ya da ``user add`` cümlesi
    söylenir - ikisi de olmazsa hiçbir adres dinlenmemiş olur.

    R6-11: ``--dataset`` söylenmemişse sunulan dünya ekranda yapılan son geçişin kümesidir, yani
    ayardaki ``active_dataset``; ``--dataset`` her zaman onu da yener. Ayar yoksa - taze bir kurulum,
    model olmadan koşan inceleme - vitrin kümesi sunulur: ``_demo_dataset``. R8-11: açılışın,
    reddin ve düşen notun satırları ``cli.serve`` kataloğundan ``lang``da gelir.

    R7-25: sunucu ayrıca veritabanının bekçisini kurar - bağlantı deposu oturumla aynı dosyadadır,
    bekçi ``SELECT 1``i kendi iş parçacığında atar, hiçbir istek onun yoluna girmez.
    ``--db-probe-file`` (R7-26, gizli) yoklamayı bir sunucunun yerine geçen bir dosyaya bağlar;
    modelin gerçekten koştuğu bir sunucuda uydurma durum okunmasın diye yalnız ``--llm fake``le
    kabul edilir.
    """
    # R5-1: web ve app içe yalnız burada girilir; cli'yi çağıran katmanlar döngü kurmasın.
    from nl2sql.app.session import SessionError, open_session
    from nl2sql.start.ready import ReadyStore
    from nl2sql.start.seed import ensure_seeded
    from nl2sql.web.app import create_app

    _utf8_stdout()
    if db_probe_file and llm_kind != "fake":
        print(_t("cli.serve.probe_needs_fake", lang))
        return EXIT_BAD_INPUT
    # R7-23: SQL Server kümesi sunuluyorsa yürütücü kullanıcı deposundaki kendi bağlantı satırına
    # kurulur; depo ``serve``in birazdan açacağı kullanıcı dosyasıyla aynıdadır.
    connections = ConnectionStore(config.app_db_path())
    try:
        session = open_session(
            dataset=dataset or _served_dataset(lang),
            model=model,
            llm=llm_kind,
            models_file=models_file,
            audit_path=config.AUDIT_LOG,
            ask_log=config.ASK_LOG,
            connections=connections,
        )
    except SessionError as exc:
        print(exc)
        return exc.exit_code
    if host not in LOOPBACK_HOSTS:
        print(_t("cli.serve.loopback", lang))
        return EXIT_BAD_INPUT
    # R6-7: oturumun sorulacağı bir depo olmadan dinlenmez; boş tabloda sıra bootstrapte.
    users = UserStore(config.app_db_path())
    if not users.count_users() and not dev_admin(users, os.environ):
        print(_t("cli.user.no_users", lang))
        return EXIT_BAD_INPUT
    ds = session.dataset
    print(
        _t(
            "cli.serve.line",
            lang,
            url=f"http://{host}:{port}",
            dataset=ds.name if ds else config.DEFAULT_DATASET,
            model=session.profile.name if session.profile else session.llm_kind,
            llm=session.llm_kind,
        )
    )
    # R7-19: kümenin tohum hazır soruları ilk açılışta bir kez deposuna yazılır, böylece başlangıç
    # ekranı taze bir kurulumda da boş kalmaz; sonraki açılışlar ayarı gördüğü için geçmez.
    ensure_seeded(ReadyStore(users.path), users, ds, session.executor)
    # R6-9: kayıtlar kullanıcıyla aynı dosyadadır; ``saved_path`` söylenmezse kapı import anının
    # ``config.APP_DB_PATH``ine düşer ve ``NL2SQL_APP_DB``i aşarak ``data/bilgin.db``yi açar.
    app = create_app(session, saved_path=users.path, users=users, connections=connections)
    # M25 incelemesi: genel ``NL2SQL_MSSQL_CONN`` yalnız etkin kümenin olduğundan (R7-23) bekçi
    # etkin kümenin adını sunucunun başlangıcından değil kapının o anki oturumundan almalıdır -
    # aksi halde bir geçişten sonra eski küme yoklanmaya, yenisinin noktası hiç yanmamaya devam eder.
    status = _db_status(connections, ds, db_probe_file,
                        get_active=lambda: getattr(app.state.session.dataset, "name", None))
    app.state.dbstatus = status
    if db_probe_file:
        # R7-26: bağlantı yoklaması da dosyaya sorar; guard'ın sorguladığı sunucu gerçek değildir.
        app.state.conn_connect = _probe_guard_connect(Path(db_probe_file))
    status.start()
    run_server(app, host, port)
    return 0


def _db_status(
    store: ConnectionStore,
    ds,
    db_probe_file: str | Path | None = None,
    get_active: Callable[[], str | None] | None = None,
) -> DbStatus:
    """Veritabanı bekçisi (R7-25): ``SELECT 1``i kendi iş parçacığı atar, istekler son cevabı okur.

    ``--db-probe-file`` verildiyse (R7-26) bekçi sunucuya değil dosyaya sorar - görsel inceleme ve
    duman testinin yeşil/kırmızı noktası bir SQL Server gerektirmez.

    ``get_active`` etkin kümenin adını her yoklamada yeniden söyler (R7-23: genel bağlantı
    değişkeni yalnız ona aittir); söylenmezse ``ds``nin adı, yani bekçinin doğduğu küme.
    """
    active = get_active if get_active is not None else (lambda: ds.name if ds else None)

    def record(dataset: str, ok: bool, error: str | None) -> None:
        # Ekrandaki "Son başarılı"/"Son hata" satırları bağlantı satırında durur (R7-22): bekçinin
        # her gerçek yoklaması buradan geçer, yoksa sütunlar hiç dolmaz.
        if ok:
            store.mark_ok(dataset)
        else:
            store.mark_error(dataset, error)

    if db_probe_file:
        path = Path(db_probe_file)
        return DbStatus(_probe_resolve(path, store, active), ping=_probe_ping(path), record=record)
    return DbStatus(lambda name: resolve_connection(name, store, active()), record=record)


def _probe_read(path: Path) -> dict:
    """Yoklama dosyasının o anki hâli (R7-26): her yoklamada yeniden okunur, okunamayanı boştur."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    return {"status": data.get("status") or {}, "guard": data.get("guard") or {}}


def _probe_resolve(path: Path, store: ConnectionStore, active: Callable[[], str | None]):
    """Sayılan her küme bağlantılı sayılır (R7-26): nokta SQLite'a düşmez, yoklamanın cevabını bekler."""

    def resolve(dataset: str) -> dict:
        if str(dataset) in _probe_read(path)["status"]:
            return {"source": "probe", "conn_str": PROBE_PREFIX + str(dataset)}
        return resolve_connection(dataset, store, active())

    return resolve


def _probe_ping(path: Path):
    """``SELECT 1``in yerine geçen cevap: dosya ``down`` diyorsa sürücü cümlesiyle düşer."""

    def ping(conn_str: str, timeout: float | None = None) -> None:
        dataset = str(conn_str).removeprefix(PROBE_PREFIX)
        if _probe_read(path)["status"].get(dataset) == "down":
            # ASSUMPTION: sahte sürücü cümlesidir - gerçek pyodbc hatası gibi sabit ve İngilizce;
            # gerçek sürücü cümleleri de çevrilmediği için kataloğa girmez.
            raise ConnectionError(f"[08001] {dataset} server unreachable (probe file).")

    return ping


def _probe_guard_connect(path: Path):
    """Guard'ın sahte bağdaçı (R7-26): cevap sunucudan değil, sunucu adının dosyadaki karşılığından."""

    def connect(conn_str: str) -> "_ProbeConnection":
        power = _probe_read(path)["guard"].get(_probe_server(conn_str), "readonly")
        return _ProbeConnection(power)

    return connect


def _probe_server(conn_str: str) -> str:
    """Bağlantı dizesinin ``SERVER=`` değeri; port virgülle ayrılmışsa adı önü söyler."""
    found = re.search(r"(?i);?SERVER=([^;]*)", str(conn_str))
    return found.group(1).split(",")[0] if found else ""


class _ProbeConnection:
    """``guard``ın yoklama dosyasından cevaplayan sahte bağlantısı (R7-26).

    ``readonly`` hiçbir gücü olmayan bir giriş, ``sysadmin`` ve ``db_owner`` kendi yetkilerini,
    ``writer`` beş yazma yetkisini 1 yanıtlar. Haritanın tabloları her zaman okunur: uydurma bir
    sunucuda eksik tablo arızası uydurulmak istenmiyordur.
    """

    def __init__(self, power: str) -> None:
        self._power = power
        self._sql = ""

    def execute(self, sql: str) -> "_ProbeConnection":
        self._sql = sql
        return self

    def fetchone(self) -> tuple:
        return (1 if self._answers() else 0,)

    def close(self) -> None:
        pass

    def _answers(self) -> bool:
        if "'OBJECT'" in self._sql:  # tablo yetkisi: haritanın tabloları hep okunur
            return True
        if self._power == "sysadmin":
            return "sysadmin" in self._sql
        if self._power == "db_owner":
            return "db_owner" in self._sql
        if self._power == "writer":
            return "'DATABASE'" in self._sql
        return False


def _served_dataset(lang: str | None = None) -> str:
    """``--dataset`` söylenmediğinde sunulacak dünya: ayardaki etkin küme, yoksa vitrin (R6-11, Run 8).

    Ayarın söylediği ad artık yüklenmiyorsa tek satırlık bir not düşer ve sıra aşağıdan devam eder:
    çip tanımadığı bir kümenin adını taşımaz, ekran da olmayan bir şemayı listelemez.
    """
    from nl2sql.web.datasets_api import ACTIVE_SETTING

    stored = UserStore(config.app_db_path()).get_setting(ACTIVE_SETTING)
    if not stored:
        return _demo_dataset()
    try:
        datasets.load_dataset(stored)
    except datasets.DatasetError:
        fallback = _demo_dataset()
        print(_t("cli.serve.stored_lost", lang, name=stored, default=fallback))
        return fallback
    return stored


def _demo_dataset() -> str:
    """Vitrin sırası (Run 8): ``wwi``, sonra indeksi kurulu ilk küme, en son ``DEFAULT_DATASET``.

    Sıra sentetik kümeye düşmesin diye kuruldu: model olmadan koşan inceleme de taze bir kurulum
    da gerçek tablo adlarını görsün. İndeksin varlığı sunulmanın koşuludur - indeksi olmayan bir
    kümenin aranacak bir şeyi yoktur, ekrana yalnız boş bir şema listesi taşırdı.
    """
    names = [DEMO_DATASET, *(name for name in datasets.list_datasets() if name != DEMO_DATASET)]
    for name in names:
        try:
            dataset = datasets.load_dataset(name)
        except datasets.DatasetError:
            continue
        if (dataset.index_dir / META_FILE).is_file():
            return name
    return config.DEFAULT_DATASET


def run_server(app, host: str, port: int) -> None:
    """uvicorn'ın tek kapısı: test burayı yerine koyar, sunucuyu gerçekten kimse açmaz."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)


def _step_lines(step: Step, lang: str = "tr") -> list[str]:
    """Adımın satırları: sıra, ✓/✗, araç, gecikme; reddedilen bir sorgu sebebini alt satırda taşır."""
    prose = t("cli.ask.prose", lang)
    head = f"  {step.n:>2} {'✓' if step.ok else '✗'} {step.tool or prose:<{TOOL_WIDTH}} {step.latency_ms:>5.0f} ms"
    if not step.ok:
        return [head, f"       ↳ {step.summary}"]
    if not step.tool:
        return [head, *(f"       {line}" for line in step.summary.splitlines())]
    if step.tool in SQL_TOOLS:
        # Şema adımı zaten okunan bir metindir, özetinin ilk satırı bir sonuç değil; sorgu adımları
        # kaç kolon döndürdüğünü söylemeyi hak eder.
        note = _first_line(step.summary)
        return [f"{head} · {note}"] if note else [head]
    notes = _search_notes(step.tool, step.summary, lang)
    return [head, *(f"       {line}" for line in notes)] if notes else [head]


def _search_notes(tool: str, summary: str, lang: str = "tr") -> list[str]:
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
        note = t("cli.ask.note_tables", lang, n=count) if count else ""
    elif tool == "find_join_path":
        joins = sum(1 for line in lines if JOIN_LINE.match(line))
        note = t("cli.ask.note_joins", lang, n=joins) if joins else ""
    elif tool == "search_rules":
        terms = [block.splitlines()[0].strip() for block in summary.split("\n\n") if block.strip()]
        note = f"→ {', '.join(terms)}" if terms else ""
    elif tool == "sample_values":
        found = VALUE_COUNT.search(summary)
        note = t("cli.ask.note_values", lang, n=found.group(1)) if found else ""
    else:
        return []
    warnings = [line for line in lines if line.startswith(WARNING_MARK)]
    if not note and lines:
        note = f"→ {lines[0]}"
    return [note, *warnings] if note else warnings


def _clarify_lines(question: str, clarification: dict, lang: str = "tr") -> list[str]:
    """R5-14: netleştirmenin satırları — soru, numaralı şıklar ve seçimin hazır komutu.

    Komut ilk şıkla kurulur: kopyalanıp yapıştırılınca çalışan bir satır, uydurma bir yer tutucudan
    iyidir. Soru da olduğu gibi yazılır, böylece şıkkın hangisine verildiği okunur.
    """
    options = clarification["options"]
    return [
        t("cli.ask.clarify_head", lang, question=clarification["question"]),
        *(CLARIFY_OPTION.format(n=n, option=option) for n, option in enumerate(options, 1)),
        "",
        t("cli.ask.clarify_hint", lang, question=question, option=options[0]),
    ]


def _cost(run: AgentRun, lang: str = "tr") -> None:
    """Koşunun maliyeti: toplam token (nasıl bölündüğüyle birlikte) ve geçen süre."""
    total = run.total_prompt_tokens + run.total_completion_tokens
    print(
        t(
            "cli.ask.token",
            lang,
            total=total,
            prompt=run.total_prompt_tokens,
            completion=run.total_completion_tokens,
        )
    )
    print(t("cli.ask.time", lang, seconds=f"{run.elapsed_s:.1f}"))


def _mapping_lines(mapping: dict, lang: str | None = None) -> list[str]:
    """R3-13: önerinin tablosu — sayfa ve başlık satırı başına her sütunun eşlenen alanları.

    Alan listesi kaydın kendi anahtarlarından gelir; eşlenmemiş sütun "hiçbir alan" ile görünür
    kalır, çünkü müşterinin haritasında tanınmayan bir başlık düzeltilmesi gereken bir bilgidir.
    """
    lines: list[str] = []
    for sheet in mapping.get("sheets") or []:
        columns = [item for item in sheet.get("columns") or [] if isinstance(item, dict)]
        lines.append(
            "\n"
            + _t(
                "cli.import_map.header_row",
                lang,
                sheet=sheet.get("sheet"),
                row=sheet.get("header_row"),
            )
        )
        width = max((len(str(item.get("column"))) for item in columns), default=0)
        for item in columns:
            fields = [
                name for name, value in item.items() if name != "column" and value is not None
            ]
            lines.append(
                f"  {str(item.get('column')):<{width}}  "
                f"{' · '.join(fields) or _t('cli.import_map.unmapped', lang)}"
            )
    return lines


def _proposal_file(source: Path, proposal_path: str | Path | None) -> Path:
    """Önerinin yazılacağı yol; adlandırma kuralı config'de, testler kendi tmp yolunu verir."""
    return Path(proposal_path) if proposal_path else config.mapping_path(source.stem)


def _read_mapping(path: str | Path, lang: str | None = None) -> dict | None:
    """Kullanıcının elle düzelttiği eşleme dosyası; okunamazsa ya da nesne değilse None."""
    head = _t("cli.import_map.bad_mapping", lang, path=path)
    try:
        chosen = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"{head}\n{exc}")
        return None
    if not isinstance(chosen, dict):
        print(f"{head}\n" + _t("cli.common.json_object", lang, shape='{"sheets": [...]}'))
        return None
    return chosen


def _read_schema(path: str | Path, lang: str | None = None) -> dict | None:
    """Şema/iskelet dosyası; okunamazsa ya da ``tables`` listesi taşımıyorsa None (yarı yolda düşmez).

    ``tables``sız bir dosya (yanlış yola verilmiş bir eşleme gibi) şema değildir: merge-map iskeleti
    tek başına birleştirip yazar, diff-map her tabloyu veritabanına özgü sayardı - ikisi de sessizce.
    """
    head = _t("cli.common.bad_schema", lang, path=path)
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"{head}\n{exc}")
        return None
    if not isinstance(data, dict) or not isinstance(data.get("tables"), list):
        print(f"{head}\n" + _t("cli.common.json_object", lang, shape='{"tables": [...]}'))
        return None
    return data


def _schema_file(value: str | Path) -> Path:
    """``--schema`` değeri: ``full`` ve ``skeleton`` config'in iki dosyasının adı, başkası yolun kendisi (R3-5).

    Yollar çağrı anında alınır; bir test ``config.SKELETON_PATH``ı kendi tmp kopyasına çevirebilir.
    """
    aliases = {FULL_SCHEMA: config.SCHEMA_PATH, "skeleton": config.SKELETON_PATH}
    return Path(aliases.get(str(value), value))


def _load_schema(path: str | Path, lang: str | None = None) -> dict | None:
    """``--schema`` dosyası sözleşme varsayılanlarıyla yüklenir; okunamazsa tek cümle ve None (Delight 3).

    Üst düzeyi nesne olmayan ya da ``tables`` taşımayan bir dosya da (yanlış yola verilmiş bir
    eşleme gibi) aynı cümleyle döner: kullanıcının düzelteceği bir eksik, iz dökümü değil.
    """
    try:
        return doc.load_schema(path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        head = _t("cli.common.bad_schema", lang, path=path)
        print(f"{head}\n{exc}")
        return None


def _write_json(path: str | Path, payload: dict) -> None:
    """Elle düzenlenecek dosya: Türkçe metin olduğu gibi, iki boşlukla girintili."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _context(
    mode: str,
    executor,
    schema: dict,
    rules: list[dict],
    index_dir: str | Path,
    ds: datasets.Dataset | None = None,
    clarify: bool = False,
    answer_lang: str = "tr",
):
    """Modun bağlamı: üçü de kuralları taşır, rag bir de diskteki indeksi ve join graphını ister.

    İndeks yoksa ya da bayatsa yükleyici yükseltir; R2-9 onun sessizce yeniden kurulmasını
    yasaklıyor, çünkü bayat vektörler bulunamayan tabloyu modelin hatası gibi gösterir.

    ``ds`` verildiğinde indeks o kümenin adıyla denetlenir (R4-8: başka bir dünyanın vektörleriyle
    aramak uydurma bir tabloyu modelin hatası gibi gösterirdi), join profili ve referans tarihi de
    kümenin tanımıdır (R4-4). ``clarify`` ilk soruya açık bir çalışmadır (R5-10); devamındaki bir
    tur onu istemez, yani açıklama döngüsü kurulmaz. ``answer_lang`` cevabın dilidir (R8-9); "tr"
    istemi bugünküyle bayt aynı bırakır.
    """
    search = graph = None
    if mode == "rag":
        search = load_search(index_dir, schema, rules, dataset=ds.name if ds else None)
        graph = build_graph(schema, load_profile(ds.profile_path if ds else config.PROFILE_PATH))
    return ToolContext(
        executor=executor,
        schema=schema,
        rules=rules,
        search=search,
        graph=graph,
        mode=mode,
        as_of=ds.as_of if ds else config.AS_OF,
        clarify=clarify,
        answer_lang=answer_lang,
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


def resolve_auto(
    schema: dict,
    rules: list[dict],
    index_dir: str | Path = config.INDEX_DIR,
    as_of: str = config.AS_OF,
    dataset: str | None = None,
    max_tokens: int | None = None,
    notify=print,
    lang: str = "tr",
) -> tuple[str, int]:
    """``--mode auto``nun çözümü (R3-10): tam kurallı istem bütçeye sığıyorsa full_rules, sığmıyorsa rag.

    Ölçüt tam kurallı sistem isteminin bağlam tahminidir: full_rules o istemi olduğu gibi bağlama
    koyar, sığmıyorsa rag arama araçlarına geçer. Rag'in taze bir indeksi yoksa ölçüm yapılamaz,
    tam nota full'a düşülür; tahmin her halükarda döner, ekrana yazılan satırın sağı solu olsun.
    ``as_of`` kümenin referans tarihidir (R4-4): tahmin, modelin gerçekten göreceği istem ölçülerek
    bulunur, yani o da aynı tarihle kurulur. ``dataset`` verildiğinde indeks de o kümenin indeksiyle
    denetlenir (R4-8): başka bir dünyanın vektörleri düşülecek bir indeks değildir, yani full'a
    düşülmez, cümlesiyle reddedilir.

    ``max_tokens`` eşiğin kendisidir (R4-12): ``--model`` profilin penceresinden gelir. Verilmediğinde
    config'in sabiti çağrı anında okunur - bir testin onu oynatması da, Run 3'ün davranışı da budur.

    ``notify`` düşüş notunu kime söyleyeceğini belirler (R5-1): CLI'de varsayılan ``print``,
    web oturumunda ``notes.append``; varsayılan davranış byte-eşdeğerdir.
    """
    limit = config.AUTO_FULL_MAX_TOKENS if max_tokens is None else max_tokens
    estimate = doc.estimate_tokens(prompt.full_rules_prompt(as_of, schema, rules))
    if estimate <= limit:
        return "full_rules", estimate
    try:
        load_search(index_dir, schema, rules, dataset)
    except ForeignIndexError:
        raise
    except (MissingIndexError, StaleIndexError):
        notify(t("cli.ask.no_index", lang))
        return "full", estimate
    return "rag", estimate


def _fingerprint(
    mode: str, kind: str, model: str, lines: list[dict], results, schema, rules, dataset=None,
    budget=None, clarify=False,
) -> dict:
    """Koşunun neyi ölçtüğünün imzası (R2-12); iki koşu ancak eşitse birbirinin devamı sayılır.

    İmza yalnız koşan soruları taşır; ``--only`` ile kısalan bir koşu hepsini ölçmüş gibi aynı
    imzayı verirse yeniden koşmak gerekip gerekmediği yanlış okunur.
    """
    ran = {result.id for result in results}
    return _mode_fingerprint(
        mode,
        kind,
        model,
        [line for line in lines if line["id"] in ran],
        schema,
        rules,
        dataset,
        budget,
        clarify,
    )


def _mode_fingerprint(
    mode: str,
    kind: str,
    model: str,
    lines: list[dict],
    schema: dict,
    rules: list[dict],
    dataset: str | None = None,
    budget: int | None = None,
    clarify: bool = False,
) -> dict:
    """İmza koşu öncesi de kurulabilir: compare bir modun ``latest``ini ancak bu imza eşitse yeniden koşar.

    ``budget`` yalnız ``--model`` verildiğinde yazılır (R4-10): aynı model 16K ile de 256K ile de
    ölçülebilir ve ikisi birbirinin devamı değildir. ``clarify`` de aynı kuraldadır (R5-12):
    kapalıyken hiç yazılmaz, yani Run 1-4'ün diskteki imzaları byte-eşit kalır.
    """
    return report.fingerprint(
        mode=mode,
        llm=kind,
        model=model,
        golden=lines,
        schema=schema,
        rules=rules,
        index_hash=content_hash(schema, rules) if mode == "rag" else "",
        max_tool_calls=get_mode(mode).max_tool_calls,
        dataset=dataset,
        budget=budget,
        clarify=clarify,
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


def _client_kind(llm, profile: ModelProfile | None = None) -> tuple[str, str]:
    """İstemcinin adı ve raporun model hanesi: fake kendinin adını, openai config'teki modeli taşır.

    ``--model`` verildiğinde hane profilin model idsidir (R4-10): koşum başka bir uç noktada
    yapılmışken config'in modelini yazmak raporu yanlış ölçmüş olurdu.
    """
    if isinstance(llm, fake.FakeLLM):
        return "fake", "fake"
    return "openai", profile.model if profile else config.llm_settings().model


def _narrator(llm):
    """``--narrate``ın anlatıcısı (R5-13): fake ölçümde altın kaydı anlatıcı değildir.

    Altın kaydı her soruya araç çağrılarıyla cevap veriyor; aynı istemciye anlatı cümlesi sorulunca
    o kaydı tekrar oynatırdı. Sahte anlatıcı bekçinin gördüğü olguyu söyler, yani ölçüm yine
    modelden bağımsızdır.
    """
    return fake.narration_client() if isinstance(llm, fake.FakeLLM) else llm


def _narrate_results(results, executor, narrator) -> dict:
    """Gönderilen her altın cevap yürütülüp anlatılır ve anlatıcının kaynağı sayılır (R5-13).

    Belirsiz satırlar anlatılmaz: cevapları bir okunuşun tahminidir, yani anlatılacak bir altın
    cevabı yok. Kaynak sorunun satırına da yazılır, böylece rapor tek tek de okunabilir; yürütme
    yeniden denetimden geçer, yani anlatı hiçbir yandan politika dışı bir sorgunun üstüne kurulmaz.
    """
    counts = {"llm": 0, "llm_retry": 0, "template": 0}
    for result in results:
        if result.kind != "golden" or not result.submitted or not result.sql:
            continue
        executed = executor.execute(result.sql, Budget(), result.id)
        if executed.error is not None:
            continue
        facts = compute_facts(executed.columns, executed.rows)
        narration = narrate(result.question, executed.columns, executed.rows, facts, narrator)
        result.narration_source = narration.source
        counts[narration.source] += 1
    total = sum(counts.values())
    return {**counts, "template_pct": round(counts["template"] / total, 4) if total else 0.0}


def _profile_block(profile: ModelProfile | None) -> dict | None:
    """report.json'ın ``profile`` bloğu (R4-14): koşunun hangi uç noktayla hangi pencerede ölçüldüğü."""
    if profile is None:
        return None
    return {
        "name": profile.name,
        "model": profile.model,
        "context_budget": profile.context_budget,
        "max_output_tokens": profile.max_output_tokens,
    }


def _model_line(profile: ModelProfile, lang: str = "tr") -> str:
    """``ask``ın hangi modelle koştuğunu söyleyen satırı (R4-14); bütçe pencerenin kendisidir."""
    return t(
        "cli.ask.model",
        lang,
        name=profile.name,
        model=profile.model,
        budget=_grouped(profile.context_budget),
    )


def _auto_line(mode: str, estimate: int, limit: int | None, lang: str = "tr") -> str:
    """auto çözümü: tahmin her halükarda söylenir, eşik yalnız ``--model`` ile bilinir (R4-12)."""
    budget = t("cli.ask.auto_budget", lang, budget=_grouped(limit)) if limit is not None else ""
    return t("cli.ask.auto", lang, mode=mode, tokens=_tokens(estimate), budget=budget)


def _auto_limit(profile: ModelProfile | None) -> int | None:
    """auto'nun eşiği profilin penceresinden gelir (R4-12): ya profil kendisi söyler ya yarısı.

    Yarının sebebi araç turları: full_rules istemi sığsa bile sonraki turlar ona eklenir. Profil
    söylenmediğinde ``None`` döner ve eşik ``resolve_auto``da config'in sabitidir.
    """
    if profile is None:
        return None
    if profile.auto_full_max_tokens:
        return profile.auto_full_max_tokens
    return math.floor(profile.context_budget * config.AUTO_FULL_SHARE)


def _grouped(value: int) -> str:
    """Token sayısı Türkçede binlik ayıracıyla okunur: 16384 -> 16.384."""
    return f"{value:,d}".replace(",", ".")


def _mode_report(out_dir: str | Path, mode: str) -> dict | None:
    """Modun ``latest`` raporu (R2-12); yoksa ya da okunamazsa None, yani yeniden koşulur."""
    return report._load(Path(out_dir) / mode / "latest" / report.REPORT_FILES[0])


def _compare_line(mode: str, summary: dict, lang: str = config.DEFAULT_LANG) -> str:
    """R2-14: mod başına tek satır — skor, tepe/medyan bağlam, ortalama araç, toplam süre, not.

    R3-11: tekrarlı koşuda skor hanesi ``ort/min/max`` okunur; tek ölçümde yine ``7/10``. Satırın
    etiketleri ``cli.eval.compare_line`` kataloğundan dilde gelir (R8-12).
    """
    context = summary["context"]
    note = f"  {t('compare.reused_note', lang)}" if summary["reused"] else ""
    return (
        t(
            "cli.eval.compare_line",
            lang,
            mode=f"{mode:<{TOOL_WIDTH}}",
            score=score_cell(summary),
            peak=_tokens(context["max_prompt_tokens"]),
            median=_tokens(context["median_prompt_tokens"]),
            tools=f"{summary['tool_calls']['mean']:.1f}",
            seconds=f"{summary['seconds']['total']:.1f}",
        )
        + note
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


def _no_db(db_path: str | Path, dataset: str | None = None, lang: str | None = None) -> int:
    """Eksik veritabanı bir sorgu hatası gibi düşmesin: tek cümle, ne yapılacağı, kod 2.

    ``dataset`` verildiğinde cümlenin söylediği ``build-db`` de o kümeyi kurar (R4-14).
    """
    print(_t("cli.ask.no_db", lang, path=db_path, ds=dataset_arg(dataset)))
    return EXIT_NO_DB


def _introspect_db(db_path: str | Path, lang: str | None = None) -> dict | None:
    """Canlı veritabanının iskeleti; yoklama yapılamıyorsa sebep ekrana, None döner (yarı yolda düşmez)."""
    if config.backend() == "mssql":
        try:
            return introspect.mssql_skeleton()
        except introspect.IntrospectError as exc:
            print(_t("cli.common.error", lang, reason=str(exc)))
            return None
    if _db_missing(db_path):
        _no_db(db_path, lang=lang)
        return None
    return introspect.sqlite_skeleton(db_path)


def _index_failed(reason: str) -> int:
    """Rag'in indeksi yok ya da bayat: cümleyi store kurar, içinde hangi komutun çözdüğü de durur."""
    print(reason)
    return EXIT_NO_INDEX


def _llm_failed(reason: str, lang: str = "tr") -> int:
    """Ölü uç nokta: adres ve sebep cümlesini llm.py üretir, eksik kalırsa öneri buradan eklenir."""
    print(t("cli.ask.error", lang, reason=reason))
    if ENV_URL not in reason:
        print(t("cli.ask.llm_hint", lang, url=ENV_URL))
    return EXIT_LLM


def _embed_failed(reason: str, lang: str | None = None) -> int:
    """Ölü embedding sunucusu: adresi ve çözümü embed.py söyler; indeks hiç yazılmadan çıkılır."""
    print(_t("cli.common.error", lang, reason=reason))
    if EMBED_ENV_URL not in reason:
        print(_t("cli.index.embed_hint", lang, url=EMBED_ENV_URL))
    return EXIT_EMBED


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _utf8_stdout() -> None:
    """Türkçe etiketler ve ✓/✗ Windows konsolunun kod sayfasına sığmaz; akış bir kez UTF-8'e döner."""
    sys.stdout.reconfigure(encoding="utf-8")
