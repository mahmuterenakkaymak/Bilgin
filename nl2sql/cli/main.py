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
import getpass
import json
import math
import os
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
from nl2sql.auth.store import NOT_FOUND_MESSAGE, UserError, UserStore
from nl2sql.cli.table import format_table
from nl2sql.engine import checks, login_script
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget, Result
from nl2sql.eval import metrics, report, retrieval, runner
from nl2sql.eval import compare_models
from nl2sql.eval.compare_modes import (
    REUSED_NOTE,
    build_compare,
    reusable,
    score_cell,
    write_compare,
)
from nl2sql.eval.runner import _tokens
from nl2sql.graph.graph import build_graph
from nl2sql.graph.profile import load_profile
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
from nl2sql.schema_map import build, doc, excel, introspect, merge
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
BAD_EMBED = (
    "Embedder kaynağı anlaşılmadı: {value}\nGeçerli olanlar: fake, fake:<dim>, openai, "
    "openai:<model>; model adını --embed-model de verebilir."
)

AUDIT_SOURCE = "ask"
# R5-14: ``ask --json`` soruyu web ile aynı kapıdan koşar; günlük ve denetim satırları bu ada
# bağlanır, çıkış kodu ise durumun adıdır — anlatı gelen cevaplar da başarılıdır.
JSON_SOURCE = "cli"
JSON_OK = ("answered", "needs_clarification")
# R5-14/R5-15: adresin seçimi kullanıcıya bırakılmaz: kendi makinesinin dışına çıkmaz, çıkarsa
# hiçbir şey dinlemeye başlamaz. R6-7: kimlik doğrulama artık her zaman açık, yani cümlenin
# gerekçesi tek kullanıcı değil, TLS ve ağ erişiminin kapsam dışı kalması.
LOOPBACK_HOSTS = (config.SERVE_HOST, "localhost")
LOOPBACK_ONLY = "Bilgin yalnız 127.0.0.1 üzerinde çalışır (TLS ve ağ erişimi kapsam dışı)."
SERVE_LINE = "Bilgin: {url}  (veri kümesi {dataset}, model {model}, llm {llm})"
# R6-11: ayar artık yüklenmeyen bir küme söylüyorsa sunucu bunu tek satırda söyler ve düşer.
STORED_LOST = "Not: kayıtlı veri kümesi {name} artık yüklenmiyor; varsayılan {default} sunuluyor."
PROSE = "yanıt"
SQL_TOOLS = ("run_sql", "submit_sql")
NO_ANSWER = "Cevap gönderilmedi: {}"
# R4-11: kırpma görünmez bir olay değil; modelin hangi araç cevabını eksik gördüğü ekrandan okunmalı.
TRIMMED = "✂ bağlam: {trimmed} araç cevabı kısaltıldı"

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
RUNNING = "{mode} koşuluyor ..."
# R3-11: tekrarlı koşuda hangi denemede olduğu satırdan okunur; gürültü ölçümü uzun bir iş ve
# ekranın "kaçıncı koşu"yu söylememesi uzun bir bekleyişi sessizliğe çevirirdi.
RUNNING_REPEAT = "{mode} koşuluyor {attempt}/{repeat} ..."
REPEAT_LINE = "Tekrar: her mod {repeat} kez koşuluyor (gürültü ölçümü)"
BAD_REPEAT = "--repeat en az 1 olmalı."
NO_INDEX_NOTE = "İndeks yok/eski; full modda çalışılıyor."
# R3-10: auto modun çözümü ekrana hem seçilen modu hem onu doğuran bağlam tahmini yazılır; eval
# auto'yu kabul etmez, çünkü bir A/B ölçümünün hangi kolu ölçtüğü baştan belli olmalı. R4-12: eşiği
# profilin penceresi belirlediği için --model ile o eşik de satıra girer; söylenmediğinde config'in
# sabitidir, yani satır Run 3'te nasıl basılıyorsa öyledir.
AUTO_LINE = "Mod: auto -> {mode} (bağlam tahmini {tokens} token{budget})"
AUTO_BUDGET = " · bütçe {budget}"
EVAL_NO_AUTO = "eval auto modu kabul etmez; modu açıkça seçin: full, full_rules, rag."
# R5-12: --ambiguous iki durumda koşmaz — kümenin belirsiz seti yoksa sorulacak soru yoktur, ve
# --compare üç modu koşar, oysa belirsiz set bir modun netleştirme davranışının ölçümüdür.
NO_AMBIGUOUS = "Bu veri kümesinin belirsiz soru seti yok."
AMBIGUOUS_COMPARE = "--ambiguous tek mod eval'i içindir."
# R5-14: metrik bloğunun başlığı; satırlarını report.metrics_block kurar, yani ekran ile report.md
# aynı altı ölçüyü söyler.
METRICS_HEAD = "Metrikler:"
# R4-10/R4-14: --model hangi uç noktayla ve hangi pencereyle koşulduğunu ilk satırda söyler; bütçe
# pencerenin kendisidir, yani cevabın payı henüz düşülmemiş hali.
MODEL_LINE = "Model: {name} ({model}, bütçe {budget} token)"
# R4-13: kapalı bir uç nokta bütün modeli düşürür; sebep satırı hem ekranda hem raporun
# ``skipped``ında durur, yani okuyan hangi modelin neden ölçülmediğini rapordan da görür.
MODES_WITHOUT_MODELS = "--modes yalnız --models ile kullanılır."
MODEL_SKIPPED = "uç nokta yanıt vermiyor ({url}) — bu blok atlandı; GPU'da bu modeli açıp yeniden koşun."
# ASSUMPTION: hiçbir model koşmadıysa ortada ölçülen bir hücre yoktur; rapor yazılmadan çıkılır
# (ölü uç noktanın kod 3'ü gibi - koşulmamış bir karşılaştırmanın raporu kullanıcıyı yanıltır).
EXIT_NO_CELLS = 3

ENV_URL = "NL2SQL_LLM_BASE_URL"
EMBED_ENV_URL = "NL2SQL_EMBED_BASE_URL"
# R4-14: ``--dataset`` verilmişse kurulması söylenen veritabanı da o kümenindir; adsız hali
# sentetik dünyanın dosyasını kurar, yani ikinci bir dünyayla çalışana hiçbir şey kazandırmaz.
NO_DB = "Veritabanı yok: {path}\nÖnce `python -m nl2sql build-db{ds}` çalıştırın."
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

# R3-6: maskelenen kolonlar tablonun altında adlarıyla söylenir; hangi değerin maskeli olduğu
# okunabilsin diye, değerin kendisi asla ekrana çıkmadığı için.
MASKED = "Maskelendi: {cols}"
# R5-14: tablonun altındaki tek cümlelik cevap; sayıları bekçi onaylamış haliyle (R5-9).
ANSWER = "Cevap: {text}"
# R5-14: netleştirmenin ekranı — soru, numaralı şıklar ve seçimin hazır komutu; devamındaki tur
# seçimi tek başına söyler, çünkü sorunun kendisi zaten ekranda duruyor.
CLARIFY_HEAD = "Netleştirme: {question}"
CLARIFY_OPTION = "  {n}. {option}"
CLARIFY_HINT = 'Seçmek için: ask "{question}" --choice "{option}"'
CHOICE_LINE = "Seçilen anlam: {option}"
# R7-9: ``--new``/``--conversation`` ekranın son satırı: hangi konuşmanın kaçıncı turu olduğu.
CONV_LINE = "Konuşma: {id} · tur {n}"

# R3-5: eval hangi şema dosyasıyla ölçtüğünü canlı satırlardan önce söyler (imzanın başı, yani iki
# koşunun aynı şemayı ölçüp ölçmediği ekrandan okunur); merge-map birleşik şemanın nereye yazıldığını.
SCHEMA_LINE = "Şema: {path} ({hash8})"
MERGED_WRITTEN = "Birleşik şema yazıldı: {path} ({tables} tablo, {columns} kolon)"

# R4-14: ``--dataset`` verildiği anda ekran hangi dünyanın ölçüldüğünü ilk satırda söyler; iki
# kümenin tablo adları birbirine benzemediği için hangi klasörle çalışıldığı baştan okunmalı.
DATASET_LINE = "Veri kümesi: {display_name} ({name})"
# ``--schema``nın argparse varsayılanı: tek başına tam şemanın adı, ``--dataset`` ile birlikte
# "şema söylenmedi" demek, yani kümenin kendi şemasının önüne geçmez (R4-4).
FULL_SCHEMA = "full"

# R6-8: ``user`` komutunun satırları. Parola hiçbir zaman argüman değildir, iki kez sorulur ve
# uyuşmazsa hiçbir şey yazılmaz; ``list`` sözleşme "User (public)" alanlarını basar, yani karma
# ekranın hiçbir yerine girmez.
USER_COLUMNS = ("Kullanıcı", "Rol", "Durum", "Son giriş")
USER_ADDED = "✓ {username} eklendi (rol {role})."
USER_PASSWD = "✓ {username} parolası değişti."
USER_SET = "✓ {username}: rol {role}, {status}."
NO_USERS = (
    "Henüz kullanıcı yok: önce `python -m nl2sql user add <ad> --role admin` ile bir yönetici "
    "oluşturun."
)
PASSWORD_PROMPT = "Parola: "
PASSWORD_REPEAT = "Parola (tekrar): "
PASSWORD_MISMATCH = "Parolalar eşleşmiyor."
ACTIVE = "etkin"
INACTIVE = "pasif"


def build_database(
    seed: int | None = None,
    db_path: str | Path | None = None,
    sql_path: str | Path | None = None,
    dataset: str | None = None,
) -> int:
    """Sentetik veriyle SQLite dosyasını ve T-SQL kurulum betiğini üretir.

    Ekran ölçümün iki girdisini de söyler (R2-14): kaç tabloda gerçekten satır olduğu (distractor
    tabloların bir kısmı şemada öylece durur) ve ``full`` modun şema metninin bağlam maliyeti.
    ``dataset`` verildiğinde tohum, iki hedef yol ve şema metnine kadar her şey o kümenin
    tanımıdır (R4-14); açıkça verilen yol ya da tohum onun önüne geçer.
    """
    _utf8_stdout()
    ds, code = _dataset(dataset)
    if code:
        return code
    _dataset_line(ds)
    seed = _or(seed, ds.seed if ds else None, config.SEED)
    db_path = _or(db_path, ds.db_path if ds else None, config.DB_PATH)
    sql_path = _or(sql_path, ds.mssql_script if ds else None, config.MSSQL_SCRIPT)
    digest = ds.build_db(seed, db_path, sql_path) if ds else build.build_db(seed, db_path, sql_path)
    print(f"Tohum: {seed}")
    print(f"Veritabanı: {db_path}")
    print(f"T-SQL betiği: {sql_path}")
    toplam, dolu = _table_counts(db_path)
    print(f"Tablolar: {toplam} (veri {dolu}, şema-yalnız {toplam - dolu})")
    schema_text = doc.full_text(ds.schema() if ds else doc.load_schema())
    print(f"Şema metni (full mod): {len(schema_text)} karakter ≈ {doc.estimate_tokens(schema_text)} token")
    print(f"Sağlama (sha256): {digest[:12]}")
    return 0


def build_index(
    embed: str = DEFAULT_EMBED,
    index_dir: str | Path | None = None,
    schema_path: str | Path | None = None,
    rules_path: str | Path | None = None,
    dataset: str | None = None,
    dataset_name: str | None = None,
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
    verilirse ``dataset`` kazanır.
    """
    _utf8_stdout()
    ds, code = _dataset(dataset)
    if code:
        return code
    _dataset_line(ds)
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
        return _embed_failed(str(exc))
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
    out_dir: str | Path | None = None,
    schema_path: str | Path | None = None,
    rules_path: str | Path | None = None,
    golden_path: str | Path | None = None,
    profile_path: str | Path | None = None,
    dataset: str | None = None,
    summaries: bool = False,
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
    ds, code = _dataset(dataset)
    if code:
        return code
    _dataset_line(ds)
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
        return _embed_failed(str(exc))
    result = retrieval.run_variants(
        search, runner.load_golden(golden_path), k, graph, schema, summaries
    )
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
    """
    _utf8_stdout()
    ds, code = _dataset(dataset)
    if code:
        return code
    if dataset_line:
        _dataset_line(ds)
    if profile:
        print(_model_line(profile))
    budget = _or(budget, profile.prompt_limit if profile else None)
    db_path = _or(db_path, ds.db_path if ds else None, config.DB_PATH)
    index_dir = _or(index_dir, ds.index_dir if ds else None, config.INDEX_DIR)
    if _db_missing(db_path):
        return _no_db(db_path, ds.name if ds else None)
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
        context = _context(mode, executor, schema, rules, index_dir, ds, clarify=not choice)
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
        print(f"Mod: {mode}")
    else:
        print(_auto_line(mode, estimate, _auto_limit(profile)))
    print(f"Soru: {question}")
    if choice:
        print(CHOICE_LINE.format(option=choice))
    print()
    if run.steps:  # daha ilk turda düşen bir uç noktanın gösterecek adımı yok
        print("Adımlar:")
        for step in run.steps:
            for line in _step_lines(step):
                print(line)
        print()
    if run.trimmed:
        print(TRIMMED.format(trimmed=run.trimmed) + "\n")
    if run.status == "llm_error":
        return _llm_failed(run.stop_reason)
    if run.status == "needs_clarification":
        for line in _clarify_lines(question, run.clarification):
            print(line)
        _cost(run)
        if conversations is not None:
            _conversation_line(
                conversations, conversation_id, pending, question=question, choice=choice,
                status="needs_clarification", sql=None, columns=[], rows=[], facts=[],
                answer_text="", clarification=run.clarification,
            )
        return 0
    if not run.submitted_sql:
        print(NO_ANSWER.format(run.stop_reason or "submit_sql hiç çağrılmadı."))
        _cost(run)
        if conversations is not None:
            _conversation_line(
                conversations, conversation_id, pending, question=question, choice=choice,
                status="failed", sql=None, columns=[], rows=[], facts=[], answer_text="",
                clarification=None,
            )
        return 1

    print("Cevap SQL:")
    print(run.submitted_sql)
    print("\nSonuç:")
    result = executor.execute(run.submitted_sql, Budget(), AUDIT_SOURCE)
    print(format_table(result))
    if result.masked_columns:
        print(MASKED.format(cols=", ".join(result.masked_columns)))
    for warning in checks.post_checks(run.submitted_sql, result, executor):
        print(f"{WARNING_MARK} {warning.message}")
    facts = compute_facts(result.columns, result.rows)
    sentence = narrate(asked, result.columns, result.rows, facts, llm).text
    print(f"\n{ANSWER.format(text=sentence)}")
    print()
    _cost(run)
    if conversations is not None:
        _conversation_line(
            conversations, conversation_id, pending, question=question, choice=choice,
            status="answered", sql=run.submitted_sql, columns=result.columns, rows=result.rows,
            facts=[fact.to_dict() for fact in facts], answer_text=sentence, clarification=None,
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


def _conversation_line(conversations, conversation_id, pending, **turn) -> None:
    """Turu konuşmaya yazar ve son satırı basar: ``Konuşma: <id> · tur <n>`` (R7-9)."""
    n = _conversation_turn(conversations, conversation_id, pending, **turn)
    print(CONV_LINE.format(id=conversation_id, n=n))


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
    """
    _utf8_stdout()
    ds, code = _dataset(dataset)
    if code:
        return code
    _dataset_line(ds)
    # Belirsiz setin yokluğu veritabanından önce sorulur: eksik olan ölçümün tanımıdır, kurulu bir
    # dosya onu geri getirmez (R5-12).
    ambiguous_lines = ds.ambiguous() if ambiguous and ds else []
    if ambiguous and not ambiguous_lines:
        print(NO_AMBIGUOUS)
        return EXIT_BAD_INPUT
    budget = _or(budget, profile.prompt_limit if profile else None)
    db_path = _or(db_path, ds.db_path if ds else None, config.DB_PATH)
    index_dir = _or(index_dir, ds.index_dir if ds else None, config.INDEX_DIR)
    out_dir = _or(out_dir, ds.eval_out if ds else None, config.EVAL_OUT)
    if _db_missing(db_path):
        return _no_db(db_path, ds.name if ds else None)
    schema_file = _schema_file(_or(schema_path, ds.schema_path if ds else None, FULL_SCHEMA))
    schema = _load_schema(schema_file)
    if schema is None:
        return EXIT_BAD_INPUT
    lines = ds.golden() if ds else runner.load_golden()
    absent = _absent_tags(lines, tags)
    if absent:
        for tag in absent:
            print(NO_TAG.format(tag=tag))
        return EXIT_NO_TAG

    info = report.schema_info(schema_file, schema)
    print(f"Mod: {mode}")
    print(SCHEMA_LINE.format(path=info["path"], hash8=info["hash"][:8]) + "\n")
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
        on_progress=lambda result: print(runner.progress_line(result)),
        budget=budget,
        clarify=ambiguous,
        ambiguous=ambiguous_lines,
    )
    if results and all(result.outcome == "llm_error" for result in results):
        print(f"Uç nokta {len(results)} sorunun hiçbirini yanıtlamadı; rapor yazılmadı.\n")
        return _llm_failed(results[0].reason)
    narration = _narrate_results(results, executor, _narrator(llm)) if narrate else None
    # Ekrandaki skor report.json ile aynı paydayı taşır (R5-12): belirsiz satırlar altın setin
    # yerine geçmez, hemen altında basılan Doğruluk ile çelişmez.
    judged = runner.scored(results)
    passed = sum(1 for result in judged if result.outcome == "pass")
    kind, model = _client_kind(llm, profile)
    name = ds.name if ds else config.DEFAULT_DATASET
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
    )
    print(f"Skor: {passed}/{len(judged)}")
    if ambiguous:
        print(f"\n{METRICS_HEAD}")
        for line in report.metrics_block(metrics.compute_metrics(results)):
            print(line)
        print()
    print(f"Rapor: {run_dir / 'report.md'}")
    return 0


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
    ds, code = _dataset(dataset)
    if code:
        return code
    _dataset_line(ds)
    budget = profile.prompt_limit if profile else None
    db_path = _or(db_path, ds.db_path if ds else None, config.DB_PATH)
    index_dir = _or(index_dir, ds.index_dir if ds else None, config.INDEX_DIR)
    out_dir = _or(out_dir, ds.eval_out if ds else None, config.EVAL_OUT)
    if _db_missing(db_path):
        return _no_db(db_path, ds.name if ds else None)
    schema_file = _schema_file(_or(schema_path, ds.schema_path if ds else None, FULL_SCHEMA))
    schema = _load_schema(schema_file)
    if schema is None:
        return EXIT_BAD_INPUT
    lines = ds.golden() if ds else runner.load_golden()
    info = report.schema_info(schema_file, schema)
    print(SCHEMA_LINE.format(path=info["path"], hash8=info["hash"][:8]) + "\n")
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
        print(REPEAT_LINE.format(repeat=repeat) + "\n")

    reports = {mode: stored[mode] for mode in reused}
    for mode in config.MODES:
        if mode in reports:
            continue
        context = _context(mode, executor, schema, rules, index_dir, ds)
        runs = []
        for attempt in range(1, repeat + 1):
            print(
                RUNNING_REPEAT.format(mode=mode, attempt=attempt, repeat=repeat)
                if repeat > 1
                else RUNNING.format(mode=mode)
            )
            results = runner.run_eval(
                lambda: clients[mode],
                executor,
                golden=lines,
                schema=schema,
                mode=mode,
                context=context,
                budget=budget,
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
                dataset=name,
                profile=_profile_block(profile),
            )
            runs.append(_mode_report(out_dir, mode))
        reports[mode] = runs

    comparison = build_compare(reports, doc.estimate_tokens(doc.full_text(schema)), reused)
    run_dir = write_compare(comparison, Path(out_dir) / "compare")
    print()
    for mode in config.MODES:
        print(_compare_line(mode, comparison["modes"][mode]))
    print(f"\n{comparison['verdict']['line']}")
    print(f"Rapor: {run_dir / 'report.md'}")
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
    if repeat < 1:
        print(BAD_REPEAT)
        return EXIT_BAD_INPUT
    ds, code = _dataset(dataset)
    if code:
        return code
    _dataset_line(ds)
    modes = list(modes) if modes else list(config.COMPARE_MODEL_MODES)
    db_path = _or(db_path, ds.db_path if ds else None, config.DB_PATH)
    index_dir = _or(index_dir, ds.index_dir if ds else None, config.INDEX_DIR)
    out_dir = _or(out_dir, ds.eval_out if ds else None, config.EVAL_OUT)
    if _db_missing(db_path):
        return _no_db(db_path, ds.name if ds else None)
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
    lines = ds.golden() if ds else runner.load_golden()
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
                reason = MODEL_SKIPPED.format(url=profile.base_url)
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
                )
                for _ in range(repeat)
            ]

    if not cells:
        for model, reason in skipped.items():
            print(f"⚠ {model}: {reason}")
        return EXIT_NO_CELLS
    report_data = compare_models.build_model_compare(
        cells, profiles=used, dataset=ds.name if ds else config.DEFAULT_DATASET, skipped=skipped
    )
    path = compare_models.write_model_compare(report_data, out_dir)
    print()
    for line in compare_models.console_lines(report_data):
        print(line)
    print(f"\nRapor: {path}")
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
            db_path=db_path,
            audit_path=audit_path,
            allowlist=doc.allowlist(skeleton),
            pii_schema=skeleton,
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


def make_login_script(
    login: str = login_script.DEFAULT_LOGIN,
    schema_path: str | Path | None = None,
    out: str | Path = config.LOGIN_SCRIPT_PATH,
    dataset: str | None = None,
) -> int:
    """Salt okunur MSSQL giriş betiğini üretir ve ``out``a yazar (R3-8).

    Allowlist ve PII kolonları okunan şemadan gelir; betiğin kendisi ``readonly_login_sql``de
    kurulur. Ekran kaç tablonun allowlist'te, kaç PII kolonunun reddedildiğini ve nereye
    yazıldığını söyler — parolanın yer tutucusu olduğu için dosya repoda durabilir.
    ``dataset`` sınırın hangi kümenin şemasından kurulacağını söyler (R4-14).
    """
    _utf8_stdout()
    ds, code = _dataset(dataset)
    if code:
        return code
    _dataset_line(ds)
    schema_path = _or(schema_path, ds.schema_path if ds else None, config.SCHEMA_PATH)
    schema = doc.load_schema(schema_path)
    target = Path(out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(login_script.readonly_login_sql(schema, login), encoding="utf-8")
    print(f"Giriş: {login}")
    print(f"Allowlist: {len(doc.allowlist(schema))} tablo")
    print(f"PII kolonu reddedildi: {len(pii.column_map(schema))}")
    print(f"Betik: {out}")
    return 0


def user_add(name: str, role: str) -> int:
    """Yeni kullanıcı: parolayı iki kez sorar, uyuşmazsa hiçbir şey yazmadan çıkar (R6-8)."""
    _utf8_stdout()
    password = _ask_password()
    if password is None:
        return EXIT_BAD_INPUT
    try:
        user = UserStore(config.app_db_path()).add_user(name, password, role)
    except UserError as exc:
        print(exc.message)
        return EXIT_BAD_INPUT
    print(USER_ADDED.format(username=user["username"], role=user["role"]))
    return 0


def user_list() -> int:
    """Bütün kullanıcılar: ad, rol, durum, son giriş; hiç yoksa ne yapılacağı söylenir (R6-8)."""
    _utf8_stdout()
    users = UserStore(config.app_db_path()).list_users()
    if not users:
        print(NO_USERS)
        return 0
    print(
        format_table(
            Result(
                columns=list(USER_COLUMNS),
                rows=[
                    (
                        user["username"],
                        user["role"],
                        ACTIVE if user["active"] else INACTIVE,
                        user["last_login_at"],
                    )
                    for user in users
                ],
                row_count=len(users),
            )
        )
    )
    return 0


def user_passwd(name: str) -> int:
    """Kullanıcının parolasını değiştirir; eski oturumları store kendisi düşürür (R6-8)."""
    _utf8_stdout()
    store = UserStore(config.app_db_path())
    user = _user_by_name(store, name)
    if user is None:
        return EXIT_BAD_INPUT
    password = _ask_password()
    if password is None:
        return EXIT_BAD_INPUT
    try:
        store.update_user(user["id"], password=password)
    except UserError as exc:
        print(exc.message)
        return EXIT_BAD_INPUT
    print(USER_PASSWD.format(username=user["username"]))
    return 0


def user_set(name: str, role: str | None = None, active: bool | None = None) -> int:
    """Rolü ya da etkinliği değiştirir; son etkin yöneticiyi store'un kendisi korur (R6-8)."""
    _utf8_stdout()
    store = UserStore(config.app_db_path())
    user = _user_by_name(store, name)
    if user is None:
        return EXIT_BAD_INPUT
    try:
        updated = store.update_user(user["id"], **_given(role=role, active=active))
    except UserError as exc:
        print(exc.message)
        return EXIT_BAD_INPUT
    print(
        USER_SET.format(
            username=updated["username"],
            role=updated["role"],
            status=ACTIVE if updated["active"] else INACTIVE,
        )
    )
    return 0


def _ask_password() -> str | None:
    """Parolayı iki kez sorar; uyuşmazlık bir yazım hatasıdır, yani cümle ve None (R6-8)."""
    password = getpass.getpass(PASSWORD_PROMPT)
    if getpass.getpass(PASSWORD_REPEAT) != password:
        print(PASSWORD_MISMATCH)
        return None
    return password


def _user_by_name(store: UserStore, name: str) -> dict | None:
    """Adı kullanıcının ``id``sine çeviren okuma; yoksa store'un kendi cümlesi ekrana çıkar."""
    user = store.get_user(name)
    if user is None:
        print(NOT_FOUND_MESSAGE)
    return user


def make_client(kind: str, mode: str = config.DEFAULT_EVAL_MODE, dataset=None, profile=None):
    """``--llm`` değerini istemciye çevirir: fake altın kaydı oynatır, openai config'teki endpoint'e gider.

    Sahte istemci oynatacağı kaydı moddan alır: ``rag`` aramadan geçerek, diğerleri şemadan.
    ``dataset`` verildiğinde kayıtlar o kümenin altın sorularıdır ve eşleşmeyen bir sorunun
    cevabı da kümenin kendi sorgusudur (R4-4) - başka bir kümenin tablosunu uydurmasın. Belirsiz
    soruları da küme taşır (R5-11); kümenin böyle bir dosyası yoksa sahte hiçbir soruyu sormaz.
    Ardışık soru zincirleri de kümenin dosyasıdır (R7-13); olmayan kümede sahte zincir tanımaz.

    ``profile`` ``--model``in profilidir (R4-10): openai istemcisi onun uç noktasından, model
    adından ve anahtar değişkeninden kurulur; anahtar tanımsızsa ``LLMError`` burada yükseltir.
    Sahte istemci profil tanımaz - oynatacağı kayıt hangisinin olduğuyla değişmez, bütçe değişir.
    """
    if kind == "fake":
        return fake.for_golden(
            dataset.golden() if dataset else runner.load_golden(),
            dataset.fake_fallback_sql if dataset else fake.FALLBACK_SQL,
            mode=mode,
            ambiguous=dataset.ambiguous() if dataset else (),
            followups=dataset.followups() if dataset else (),
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


def _add_dataset_option(command: argparse.ArgumentParser) -> None:
    """``--dataset``: komutun hiçbir varsayılanı config'de kalmaz, hepsi o kümenin tanımıdır (R4-14)."""
    command.add_argument(
        "--dataset",
        metavar="AD",
        help=f"veri kümesi adı (varsayılan: {config.DEFAULT_DATASET})",
    )


def _add_model_options(command: argparse.ArgumentParser) -> None:
    """``--model`` bir profil seçer (R4-10): uç nokta, model adı, anahtar değişkeni ve pencere.

    Söylenmediğinde koşum Run 3'ün halidir - ``NL2SQL_LLM_*`` ile kurulan uç nokta, bütçe yok.
    ``--models-file`` aynı profilin başka bir dosyadan okunmasıdır; testler kendi tmp dosyasını
    verir, böylece gerçek ``config/models.json``a ve içindeki anahtar değişkenlerine dokunulmaz.
    """
    command.add_argument(
        "--model",
        metavar="PROFIL",
        help=f"config/models.json profili (varsayılan: {config.llm_settings().base_url})",
    )
    command.add_argument(
        "--models-file",
        metavar="DOSYA.json",
        help=f"--model için profil dosyası (varsayılan {config.MODELS_PATH})",
    )


def _add_embed_options(command: argparse.ArgumentParser) -> None:
    """``build-index`` ile ``eval-retrieval``ın ortak embedder bayrakları (R3-9).

    ``--embed-model`` model adını doğrudan söyler: aynı sunucuda duran iki modeli (embeddinggemma,
    bge-m3) ölçmek için ortam değişkeni değiştirmek yerine komutun kendisi yazılır.
    """
    command.add_argument(
        "--embed",
        default=DEFAULT_EMBED,
        help="embedder kaynağı: fake, fake:<dim>, openai (varsayılan %(default)s)",
    )
    command.add_argument(
        "--embed-model",
        metavar="AD",
        help="openai kaynağının model adı, örn. bge-m3 (varsayılan: NL2SQL_EMBED_MODEL)",
    )


def _embed_arg(args) -> str | None:
    """``--embed`` ile ``--embed-model`` tek embedder metnine döner: ``fake:64``, ``openai:bge-m3``.

    Model adı bir uç nokta kaynağı ister; ``fake``in soneki vektör genişliği olduğu için
    ``--embed fake --embed-model bge-m3``in anlatmak istediği bir şey yok.
    """
    value = f"{args.embed}:{args.embed_model}" if args.embed_model else str(args.embed)
    if not EMBED_ID.match(value):
        print(BAD_EMBED.format(value=value))
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


def _dataset_line(ds: datasets.Dataset | None) -> None:
    """Kümeyi kendisi seçen komut hangi dünyayla çalıştığını ilk satırda söyler (R4-14)."""
    if ds:
        print(DATASET_LINE.format(display_name=ds.display_name, name=ds.name))


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


def main(argv: list[str] | None = None) -> int:
    """argparse: ``build-db`` | ``ask`` | ``eval``; seçilen komutun işlevini çağırır."""
    parser = argparse.ArgumentParser(prog="python -m nl2sql", description="NL -> T-SQL ölçüm aracı.")
    commands = parser.add_subparsers(dest="command", required=True)

    build_cmd = commands.add_parser("build-db", help="sentetik veritabanını ve T-SQL betiğini kurar")
    build_cmd.add_argument(
        "--seed",
        type=int,
        help=f"üretici tohumu (varsayılan: veri kümesinin tohumu, {config.SEED})",
    )
    _add_dataset_option(build_cmd)

    index_cmd = commands.add_parser("build-index", help="şema ve kurallardan arama indeksini kurar")
    _add_embed_options(index_cmd)
    _add_dataset_option(index_cmd)

    retrieval_cmd = commands.add_parser(
        "eval-retrieval", help="altın sorularında aramanın geri çağırmasını ölçer"
    )
    _add_embed_options(retrieval_cmd)
    _add_dataset_option(retrieval_cmd)
    retrieval_cmd.add_argument(
        "--k", type=int, default=config.SEARCH_K, help="kaç tablo (varsayılan %(default)s)"
    )
    # Varsayılan bilinçli olarak None: verilmeyen bayrak ``eval_retrieval``in kendi varsayılanına
    # (off) düşer, yani ``--summaries`` yazılmayan bir koşumun raporu bugünkü raporun aynısıdır.
    retrieval_cmd.add_argument(
        "--summaries",
        choices=("on", "off"),
        default=None,
        help="tablo özetlerini aramaya kat: on, off (varsayılan off)",
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

    login_cmd = commands.add_parser(
        "make-login-script", help="salt okunur MSSQL giriş betiğini üretir ve yazar"
    )
    login_cmd.add_argument(
        "--login",
        default=login_script.DEFAULT_LOGIN,
        help="giriş ve kullanıcı adı (varsayılan %(default)s)",
    )
    _add_dataset_option(login_cmd)

    ask_cmd = commands.add_parser("ask", help="tek bir soruyu modelden geçirip cevabı gösterir")
    ask_cmd.add_argument("question", help='Türkçe soru, örn. "Geçen ayın cirosu ne kadar?"')
    ask_cmd.add_argument(
        "--llm", choices=LLMS, default=DEFAULT_LLM, help="istem kaynağı (varsayılan %(default)s)"
    )
    ask_cmd.add_argument(
        "--mode",
        choices=(*config.MODES, "auto"),
        default="auto",
        help="bağlam modu (varsayılan %(default)s)",
    )
    ask_cmd.add_argument(
        "--json",
        action="store_true",
        help="yalnız cevabın JSON'unu yazdır (web API ile aynı tek kapı)",
    )
    ask_cmd.add_argument(
        "--choice",
        metavar="SEÇENEK",
        help="netleştirme şıkkı: soruyu seçilen anlamıyla koşar, yeniden sormaz",
    )
    conversation = ask_cmd.add_mutually_exclusive_group()
    conversation.add_argument(
        "--conversation",
        metavar="ID",
        help="soruyu bu konuşmanın devamı olarak sor (önceki turlar bağlama girer)",
    )
    conversation.add_argument(
        "--new",
        action="store_true",
        help="yeni bir konuşma aç ve kimliğini son satırda söyle",
    )
    _add_model_options(ask_cmd)
    _add_dataset_option(ask_cmd)

    serve_cmd = commands.add_parser(
        "serve", help="web API'sini ve arayüzü kendi makinesine bağlı çalıştırır"
    )
    serve_cmd.add_argument(
        "--host",
        default=config.SERVE_HOST,
        help=f"bağlanılacak adres (yalnız {', '.join(LOOPBACK_HOSTS)})",
    )
    serve_cmd.add_argument(
        "--port", type=int, default=config.SERVE_PORT, help="bağlanılacak port (varsayılan %(default)s)"
    )
    serve_cmd.add_argument(
        "--llm", choices=LLMS, default=DEFAULT_LLM, help="istem kaynağı (varsayılan %(default)s)"
    )
    _add_model_options(serve_cmd)
    _add_dataset_option(serve_cmd)

    # R6-8: kullanıcı hesapları parolayı asla komut satırından almaz — iki kez sorulur, yani
    # kabuk geçmişine düşmez. Komut login istemez: kendi makinesinin dosyasını kendi yönetir.
    user_cmd = commands.add_parser("user", help="kullanıcı hesaplarını listeler, açar, değiştirir")
    user_sub = user_cmd.add_subparsers(dest="user_command", required=True)
    user_add_cmd = user_sub.add_parser("add", help="yeni kullanıcı açar, parolayı iki kez sorar")
    user_add_cmd.add_argument("name", metavar="AD")
    user_add_cmd.add_argument(
        "--role",
        choices=("admin", "user"),
        default="user",
        help="rol (varsayılan %(default)s)",
    )
    user_sub.add_parser("list", help="kullanıcıları, rollerini ve son girişleri listeler")
    user_passwd_cmd = user_sub.add_parser("passwd", help="parolayı değiştirir")
    user_passwd_cmd.add_argument("name", metavar="AD")
    user_set_cmd = user_sub.add_parser("set", help="rolü ya da etkinliği değiştirir")
    user_set_cmd.add_argument("name", metavar="AD")
    user_change = user_set_cmd.add_mutually_exclusive_group(required=True)
    user_change.add_argument("--role", choices=("admin", "user"), help="yeni rol")
    user_change.add_argument(
        "--deactivate", action="store_true", help="kullanıcıyı pasifleştirir"
    )
    user_change.add_argument("--activate", action="store_true", help="kullanıcıyı etkinleştirir")

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
        choices=(*config.MODES, "auto"),
        default=config.DEFAULT_EVAL_MODE,
        help="bağlam modu (varsayılan %(default)s); auto yalnız ask'ta",
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
        "--models",
        metavar="A,B",
        help="--compare ile model x mod karşılaştırması: virgülle ayrılmış profil adları",
    )
    eval_cmd.add_argument(
        "--modes",
        metavar="M1,M2",
        help=f"--models ile koşulacak modlar (varsayılan {','.join(config.COMPARE_MODEL_MODES)})",
    )
    eval_cmd.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="--compare ile her modu N kez koşar ve gürültüyü ölçer (varsayılan %(default)s)",
    )
    eval_cmd.add_argument(
        "--schema",
        default=FULL_SCHEMA,
        metavar="DOSYA|full|skeleton",
        help="ölçümün şeması: tam ad ya da yol (varsayılan %(default)s)",
    )
    eval_cmd.add_argument(
        "--ambiguous",
        action="store_true",
        help="altın sorulara kümenin belirsiz setini de katıp netleştirme metriklerini ölçer",
    )
    eval_cmd.add_argument(
        "--narrate",
        action="store_true",
        help="gönderilen her altın cevabı anlatıp anlatıcının kaynağını sayar",
    )
    _add_model_options(eval_cmd)
    _add_dataset_option(eval_cmd)

    args = parser.parse_args(argv)
    if args.command == "build-db":
        return build_database(**_given(seed=args.seed, dataset=args.dataset))
    if args.command == "build-index":
        embed = _embed_arg(args)
        return build_index(embed=embed, **_given(dataset=args.dataset)) if embed else EXIT_BAD_INPUT
    if args.command == "eval-retrieval":
        embed = _embed_arg(args)
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
    if args.command == "ask":
        from nl2sql.app.conversations import ConversationNotFound

        if args.json:
            try:
                return _ask_json(args)
            except ConversationNotFound as exc:
                print(exc)
                return EXIT_BAD_INPUT
        ds, code = _dataset(args.dataset)
        if code:
            return code
        profile, code = _profile_arg(args)
        if code:
            return code
        # R4-14: küme satırı her halükarda ilk satırdır; auto çözümü NO_INDEX_NOTE basabildiği için
        # buraya alındı ve ask() kendisinin basmadığını ``dataset_line`` ile öğreniyor.
        _dataset_line(ds)
        # ASSUMPTION: "ask'ın varsayılanı auto" komutun varsayılanıdır (argparse default); buradaki
        # çözümleme istemciye de çözülmüş modu vermek için — sahte kayıt rag ile diğerlerinde farklı
        # oynar. ask() fonksiyonunun kendi varsayılanı "full" kalır, doğrudan çağıranı etkilemesin.
        mode, estimate = args.mode, None
        try:
            if mode == "auto":
                mode, estimate = resolve_auto(
                    *_auto_inputs(ds), max_tokens=_auto_limit(profile)
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
        except ConversationNotFound as exc:
            # R7-9: --conversation bilinmeyen bir kimlik söylüyorsa düzeltmesi kullanıcının elinde:
            # konuşma yok, başkasının ya da başka bir kümede - tek cümle ve kod 2.
            print(exc)
            return EXIT_BAD_INPUT
    if args.command == "serve":
        return serve(
            host=args.host,
            port=args.port,
            llm_kind=args.llm,
            **_given(dataset=args.dataset, model=args.model, models_file=args.models_file),
        )
    if args.command == "user":
        if args.user_command == "list":
            return user_list()
        if args.user_command == "add":
            return user_add(args.name, args.role)
        if args.user_command == "passwd":
            return user_passwd(args.name)
        return user_set(
            args.name,
            role=args.role,
            active=None if not (args.activate or args.deactivate) else args.activate,
        )
    if args.modes and not args.models:
        print(MODES_WITHOUT_MODELS)
        return EXIT_BAD_INPUT
    if args.mode == "auto":
        print(EVAL_NO_AUTO)
        return EXIT_BAD_INPUT
    if args.compare and args.ambiguous:
        print(AMBIGUOUS_COMPARE)
        return EXIT_BAD_INPUT
    # ASSUMPTION: --ambiguous belirsiz seti bir veri kümesinden okur; --dataset söylenmemişse ölçülen
    # dünya adıyla da söylenir, yani config'in sabitleriyle aynı değerleri taşıyan sentetik ERP
    # (R5-12) — sahte kayıt belirsiz soruları ancak küme tanınırsa oynatır.
    dataset = args.dataset or (config.DEFAULT_DATASET if args.ambiguous else None)
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
                print(BAD_REPEAT)
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
    ayardaki ``active_dataset``; ``--dataset`` her zaman onu da yener.
    """
    # R5-1: web ve app içe yalnız burada girilir; cli'yi çağıran katmanlar döngü kurmasın.
    from nl2sql.app.session import SessionError, open_session
    from nl2sql.web.app import create_app

    _utf8_stdout()
    try:
        session = open_session(
            dataset=dataset or _served_dataset(),
            model=model,
            llm=llm_kind,
            models_file=models_file,
            audit_path=config.AUDIT_LOG,
            ask_log=config.ASK_LOG,
        )
    except SessionError as exc:
        print(exc)
        return exc.exit_code
    if host not in LOOPBACK_HOSTS:
        print(LOOPBACK_ONLY)
        return EXIT_BAD_INPUT
    # R6-7: oturumun sorulacağı bir depo olmadan dinlenmez; boş tabloda sıra bootstrapte.
    users = UserStore(config.app_db_path())
    if not users.count_users() and not dev_admin(users, os.environ):
        print(NO_USERS)
        return EXIT_BAD_INPUT
    ds = session.dataset
    print(
        SERVE_LINE.format(
            url=f"http://{host}:{port}",
            dataset=ds.name if ds else config.DEFAULT_DATASET,
            model=session.profile.name if session.profile else session.llm_kind,
            llm=session.llm_kind,
        )
    )
    # R6-9: kayıtlar kullanıcıyla aynı dosyadadır; ``saved_path`` söylenmezse kapı import anının
    # ``config.APP_DB_PATH``ine düşer ve ``NL2SQL_APP_DB``i aşarak ``data/bilgin.db``yi açar.
    run_server(create_app(session, saved_path=users.path, users=users), host, port)
    return 0


def _served_dataset() -> str:
    """``--dataset`` söylenmediğinde sunulacak dünya: ayardaki etkin küme, yoksa varsayılan (R6-11).

    Ayarın söylediği ad artık yüklenmiyorsa tek satırlık bir not düşer ve varsayılan sunulur:
    çip tanımadığı bir kümenin adını taşımaz, ekran da olmayan bir şemayı listelemez.
    """
    from nl2sql.web.datasets_api import ACTIVE_SETTING

    stored = UserStore(config.app_db_path()).get_setting(ACTIVE_SETTING)
    if not stored:
        return config.DEFAULT_DATASET
    try:
        datasets.load_dataset(stored)
    except datasets.DatasetError:
        print(STORED_LOST.format(name=stored, default=config.DEFAULT_DATASET))
        return config.DEFAULT_DATASET
    return stored


def run_server(app, host: str, port: int) -> None:
    """uvicorn'ın tek kapısı: test burayı yerine koyar, sunucuyu gerçekten kimse açmaz."""
    import uvicorn

    uvicorn.run(app, host=host, port=port)


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


def _clarify_lines(question: str, clarification: dict) -> list[str]:
    """R5-14: netleştirmenin satırları — soru, numaralı şıklar ve seçimin hazır komutu.

    Komut ilk şıkla kurulur: kopyalanıp yapıştırılınca çalışan bir satır, uydurma bir yer tutucudan
    iyidir. Soru da olduğu gibi yazılır, böylece şıkkın hangisine verildiği okunur.
    """
    options = clarification["options"]
    return [
        CLARIFY_HEAD.format(question=clarification["question"]),
        *(CLARIFY_OPTION.format(n=n, option=option) for n, option in enumerate(options, 1)),
        "",
        CLARIFY_HINT.format(question=question, option=options[0]),
    ]


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
    """Şema/iskelet dosyası; okunamazsa ya da ``tables`` listesi taşımıyorsa None (yarı yolda düşmez).

    ``tables``sız bir dosya (yanlış yola verilmiş bir eşleme gibi) şema değildir: merge-map iskeleti
    tek başına birleştirip yazar, diff-map her tabloyu veritabanına özgü sayardı - ikisi de sessizce.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"{BAD_SCHEMA.format(path=path)}\n{exc}")
        return None
    if not isinstance(data, dict) or not isinstance(data.get("tables"), list):
        print(f'{BAD_SCHEMA.format(path=path)}\nÜst düzey bir JSON nesnesi olmalı: {{"tables": [...]}}.')
        return None
    return data


def _schema_file(value: str | Path) -> Path:
    """``--schema`` değeri: ``full`` ve ``skeleton`` config'in iki dosyasının adı, başkası yolun kendisi (R3-5).

    Yollar çağrı anında alınır; bir test ``config.SKELETON_PATH``ı kendi tmp kopyasına çevirebilir.
    """
    aliases = {FULL_SCHEMA: config.SCHEMA_PATH, "skeleton": config.SKELETON_PATH}
    return Path(aliases.get(str(value), value))


def _load_schema(path: str | Path) -> dict | None:
    """``--schema`` dosyası sözleşme varsayılanlarıyla yüklenir; okunamazsa tek cümle ve None (Delight 3).

    Üst düzeyi nesne olmayan ya da ``tables`` taşımayan bir dosya da (yanlış yola verilmiş bir
    eşleme gibi) aynı cümleyle döner: kullanıcının düzelteceği bir eksik, iz dökümü değil.
    """
    try:
        return doc.load_schema(path)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        print(f"{BAD_SCHEMA.format(path=path)}\n{exc}")
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
):
    """Modun bağlamı: üçü de kuralları taşır, rag bir de diskteki indeksi ve join graphını ister.

    İndeks yoksa ya da bayatsa yükleyici yükseltir; R2-9 onun sessizce yeniden kurulmasını
    yasaklıyor, çünkü bayat vektörler bulunamayan tabloyu modelin hatası gibi gösterir.

    ``ds`` verildiğinde indeks o kümenin adıyla denetlenir (R4-8: başka bir dünyanın vektörleriyle
    aramak uydurma bir tabloyu modelin hatası gibi gösterirdi), join profili ve referans tarihi de
    kümenin tanımıdır (R4-4). ``clarify`` ilk soruya açık bir çalışmadır (R5-10); devamındaki bir
    tur onu istemez, yani açıklama döngüsü kurulmaz.
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
        notify(NO_INDEX_NOTE)
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


def _model_line(profile: ModelProfile) -> str:
    """``ask``ın hangi modelle koştuğunu söyleyen satırı (R4-14); bütçe pencerenin kendisidir."""
    return MODEL_LINE.format(
        name=profile.name,
        model=profile.model,
        budget=_grouped(profile.context_budget),
    )


def _auto_line(mode: str, estimate: int, limit: int | None) -> str:
    """auto çözümü: tahmin her halükarda söylenir, eşik yalnız ``--model`` ile bilinir (R4-12)."""
    budget = AUTO_BUDGET.format(budget=_grouped(limit)) if limit is not None else ""
    return AUTO_LINE.format(mode=mode, tokens=_tokens(estimate), budget=budget)


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


def _compare_line(mode: str, summary: dict) -> str:
    """R2-14: mod başına tek satır — skor, tepe/medyan bağlam, ortalama araç, toplam süre, not.

    R3-11: tekrarlı koşuda skor hanesi ``ort/min/max`` okunur; tek ölçümde yine ``7/10``.
    """
    context = summary["context"]
    note = f"  {REUSED_NOTE}" if summary["reused"] else ""
    return (
        f"{mode:<{TOOL_WIDTH}} {score_cell(summary)}"
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


def _no_db(db_path: str | Path, dataset: str | None = None) -> int:
    """Eksik veritabanı bir sorgu hatası gibi düşmesin: tek cümle, ne yapılacağı, kod 2.

    ``dataset`` verildiğinde cümlenin söylediği ``build-db`` de o kümeyi kurar (R4-14).
    """
    print(NO_DB.format(path=db_path, ds=dataset_arg(dataset)))
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
