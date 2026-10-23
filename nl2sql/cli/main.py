"""Komut satırı: veritabanını kur, indeksi kur, geri çağırmayı ölç, tek bir soru sor, altın soruları koş.

Komutlar aynı parçaları kullanır ve hiçbir yola sahip çıkmaz: SQLite dosyası, audit kaydı,
rapor klasörü ve indeks klasörü parametredir, varsayılanı config'den gelir, testler kendi tmp
yolunu verir. ``ask``
koşuyu adım adım dökerek ekrana yazdırır (Delight 6), ``eval`` raporu yazıp skoru söyler; skor veri
olduğu için çıkış koduna geçmez, yalnız cevap gönderilmeyen bir soru 1 döner. Kullanıcının
düzeltebileceği üç arıza iz dökümüyle değil tek cümleyle çıkar (Delight 3): veritabanı dosyası
yoksa kod 2 ve "önce kur", uç nokta ya da embedding sunucusu hiç çalışmıyorsa kod 3 ve hangi
adresin patladığı.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.agent.llm import OpenAIClient
from nl2sql.agent.loop import AgentRun, Step, run_agent
from nl2sql.cli.table import format_table
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.eval import report, retrieval, runner
from nl2sql.index.docs import COLLECTIONS, build_documents
from nl2sql.index.embed import EmbedError, make_embedder
from nl2sql.index.search import build_search
from nl2sql.index.store import FileStore, content_hash
from nl2sql.schema_map import build, doc
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

ENV_URL = "NL2SQL_LLM_BASE_URL"
EMBED_ENV_URL = "NL2SQL_EMBED_BASE_URL"
NO_DB = "Veritabanı yok: {path}\nÖnce `python -m nl2sql build-db` çalıştırın."
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


def ask(question: str, llm, db_path: str = config.DB_PATH, audit_path: str = config.AUDIT_LOG) -> int:
    """Bir soru: adımları işaretle ve gecikmesiyle dök, gönderilen SQL'i ve tabloyu göster.

    ``llm`` hazır bir istemcidir; tablo için gönderilen SQL bir kez daha yürütülür, çünkü döngü
    yanıtı metin olarak görür, satırları ekrana basacak biçimde elinde tutmaz.
    """
    _utf8_stdout()
    if _db_missing(db_path):
        return _no_db(db_path)
    executor = LocalExecutor(db_path=db_path, audit_path=audit_path)
    run = run_agent(question, llm, executor, doc.load_schema(), AUDIT_SOURCE)

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
    db_path: str = config.DB_PATH,
    audit_path: str = config.AUDIT_LOG,
    out_dir: str = config.EVAL_OUT,
) -> int:
    """Altın soruları koşar, her soru biter bitmez tek satır dökerek (Delight 4) ilerler,
    raporu yazar, skoru söyler; koşu tamamlandıysa kod 0'dır."""
    _utf8_stdout()
    if _db_missing(db_path):
        return _no_db(db_path)
    results = runner.run_eval(
        lambda: llm,
        LocalExecutor(db_path=db_path, audit_path=audit_path),
        only=only,
        on_progress=lambda result: print(runner.progress_line(result)),
    )
    if results and all(result.outcome == "llm_error" for result in results):
        print(f"Uç nokta {len(results)} sorunun hiçbirini yanıtlamadı; rapor yazılmadı.\n")
        return _llm_failed(results[0].reason)
    passed = sum(1 for result in results if result.outcome == "pass")
    model = "fake" if isinstance(llm, fake.FakeLLM) else config.llm_settings().model
    run_dir = report.write_report(
        results, out_dir, model=model, config={"backend": config.backend(), "llm": model}
    )
    print(f"Skor: {passed}/{len(results)}")
    print(f"Rapor: {run_dir / 'report.md'}")
    return 0


def make_client(kind: str):
    """``--llm`` değerini istemciye çevirir: fake altın kaydı oynatır, openai config'teki endpoint'e gider."""
    if kind == "fake":
        return fake.for_golden(runner.load_golden())
    settings = config.llm_settings()
    return OpenAIClient(settings.base_url, settings.model, settings.api_key)


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

    ask_cmd = commands.add_parser("ask", help="tek bir soruyu modelden geçirip cevabı gösterir")
    ask_cmd.add_argument("question", help='Türkçe soru, örn. "Geçen ayın cirosu ne kadar?"')
    ask_cmd.add_argument(
        "--llm", choices=LLMS, default=DEFAULT_LLM, help="istem kaynağı (varsayılan %(default)s)"
    )

    eval_cmd = commands.add_parser("eval", help="altın soruları koşar ve raporu yazar")
    eval_cmd.add_argument(
        "--llm", choices=LLMS, default=DEFAULT_LLM, help="istem kaynağı (varsayılan %(default)s)"
    )
    eval_cmd.add_argument(
        "--only", nargs="+", metavar="Q03", help="yalnız bu soru kimlikleri (boşlukla ayrılır)"
    )

    args = parser.parse_args(argv)
    if args.command == "build-db":
        return build_database(seed=args.seed)
    if args.command == "build-index":
        return build_index(embed=args.embed)
    if args.command == "eval-retrieval":
        return eval_retrieval(embed=args.embed, k=args.k)
    if args.command == "ask":
        return ask(question=args.question, llm=make_client(args.llm))
    return evaluate(llm=make_client(args.llm), only=args.only)


def _step_lines(step: Step) -> list[str]:
    """Adımın satırları: sıra, ✓/✗, araç, gecikme; reddedilen bir sorgu sebebini alt satırda taşır."""
    head = f"  {step.n:>2} {'✓' if step.ok else '✗'} {step.tool or PROSE:<11} {step.latency_ms:>5.0f} ms"
    if not step.ok:
        return [head, f"       ↳ {step.summary}"]
    if not step.tool:
        return [head, *(f"       {line}" for line in step.summary.splitlines())]
    # Şema adımı zaten okunan bir metindir, özetinin ilk satırı bir sonuç değil; sorgu adımları
    # kaç kolon döndürdüğünü söylemeyi hak eder.
    note = _first_line(step.summary) if step.tool in SQL_TOOLS else ""
    return [f"{head} · {note}" if note else head]


def _cost(run: AgentRun) -> None:
    """Koşunun maliyeti: toplam token (nasıl bölündüğüyle birlikte) ve geçen süre."""
    total = run.total_prompt_tokens + run.total_completion_tokens
    print(f"Token: {total} (istem {run.total_prompt_tokens} + cevap {run.total_completion_tokens})")
    print(f"Süre: {run.elapsed_s:.1f} sn")


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
