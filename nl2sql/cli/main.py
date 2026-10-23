"""Komut satırı: veritabanını kur, tek bir soru sor, altın soruları koş.

Üç komut da aynı parçaları kullanır ve hiçbir yola sahip çıkmaz: SQLite dosyası, audit kaydı ve
rapor klasörü parametredir, varsayılanı config'den gelir, testler kendi tmp yolunu verir. ``ask``
koşuyu adım adım dökerek ekrana yazdırır (Delight 6), ``eval`` raporu yazıp skoru söyler; skor veri
olduğu için çıkış koduna geçmez, yalnız cevap gönderilmeyen bir soru 1 döner.
"""

from __future__ import annotations

import argparse
import sys

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.agent.llm import OpenAIClient
from nl2sql.agent.loop import AgentRun, Step, run_agent
from nl2sql.cli.table import format_table
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.eval import report, runner
from nl2sql.schema_map import build, doc

LLMS = ("fake", "openai")
# ASSUMPTION: ölçüm aracının varsayılanı gerçek endpoint'tir; --llm fake model istemeyen ölçüm
# yolu olduğu için kendisi söylenerek seçilir.
DEFAULT_LLM = "openai"

AUDIT_SOURCE = "ask"
PROSE = "yanıt"
SQL_TOOLS = ("run_sql", "submit_sql")
NO_ANSWER = "Cevap gönderilmedi: {}"


def build_database(
    seed: int = config.SEED,
    db_path: str = config.DB_PATH,
    sql_path: str = config.MSSQL_SCRIPT,
) -> int:
    """Sentetik veriyle SQLite dosyasını ve T-SQL kurulum betiğini üretir."""
    _utf8_stdout()
    digest = build.build_db(seed, db_path, sql_path)
    print(f"Tohum: {seed}")
    print(f"Veritabanı: {db_path}")
    print(f"T-SQL betiği: {sql_path}")
    print(f"Sağlama (sha256): {digest[:12]}")
    return 0


def ask(question: str, llm, db_path: str = config.DB_PATH, audit_path: str = config.AUDIT_LOG) -> int:
    """Bir soru: adımları işaretle ve gecikmesiyle dök, gönderilen SQL'i ve tabloyu göster.

    ``llm`` hazır bir istemcidir; tablo için gönderilen SQL bir kez daha yürütülür, çünkü döngü
    yanıtı metin olarak görür, satırları ekrana basacak biçimde elinde tutmaz.
    """
    _utf8_stdout()
    executor = LocalExecutor(db_path=db_path, audit_path=audit_path)
    run = run_agent(question, llm, executor, doc.load_schema(), AUDIT_SOURCE)

    print(f"Soru: {question}\n")
    print("Adımlar:")
    for step in run.steps:
        for line in _step_lines(step):
            print(line)
    print()
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
    """Altın soruları koşar, raporu yazar, skoru söyler; koşu tamamlandıysa kod 0'dır."""
    _utf8_stdout()
    results = runner.run_eval(
        lambda: llm, LocalExecutor(db_path=db_path, audit_path=audit_path), only=only
    )
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


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _utf8_stdout() -> None:
    """Türkçe etiketler ve ✓/✗ Windows konsolunun kod sayfasına sığmaz; akış bir kez UTF-8'e döner."""
    sys.stdout.reconfigure(encoding="utf-8")
