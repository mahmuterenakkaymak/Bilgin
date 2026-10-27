"""One golden question, end to end: the agent runs, the answer is executed, the outcome is decided.

The runner is where a run becomes a number. It re-decides nothing about what the model meant: the
submitted SQL goes to the same executor the model talked to, under the comparison budget so neither
side loses rows, and the verdict comes from compare(). All ten outcomes are named here, which is
also why a run that never submitted is not automatically just ``no_submission`` - the query that
killed it (a policy reject, a missing column) says far more in the report than the absence of a
submit, so the model's last attempt is executed once more to name the blocker.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from pathlib import Path

from nl2sql import config
from nl2sql.agent.loop import Step, run_agent
from nl2sql.agent.modes import ToolContext
from nl2sql.engine.result import Budget, Result
from nl2sql.eval.compare import compare
from nl2sql.i18n import t
from nl2sql.schema_map import doc
from nl2sql.schema_map.rules import load_rules

OUTCOMES = (
    "pass",
    "wrong_result",
    "sql_error",
    "policy_reject",
    "transpile_error",
    "no_submission",
    "timeout",
    "llm_error",
    "context_overflow",
    # Golden bir soruyu cevaplamak yerine netleştirme sorusu sormak (R5-12): brief kuralı, cevaplanmamış.
    "needs_clarification",
)

# Belirsiz soru satırlarının outcome'ları (PLAN R5-12): sormak doğru davranış, tahmin etmek değil.
# Bir belirsiz soru başarısız olduysa yukarıdaki hata outcome'lardan birini alır.
AMBIGUOUS_OUTCOMES = ("clarified", "guessed")

# Satırda ✓'yi hak edenler: doğru cevap ve belirsiz soruyu tahmin etmek yerine sormak.
CHECKED_OUTCOMES = ("pass", "clarified")

# Outcome sütunu bu genişliğe yazılır, yani canlı satırlar birbirinin üstünde hizalı durur.
OUTCOME_WIDTH = max(len(name) for name in OUTCOMES)

# ExecError.kind -> the outcome for a query that never reached the data.
EXEC_OUTCOMES = {
    "policy": "policy_reject",
    "transpile": "transpile_error",
    "sql": "sql_error",
    "timeout": "timeout",
}

# PLAN Decision 8: neither the golden nor the predicted answer may lose rows to the model's budget.
COMPARE = Budget(max_rows=config.COMPARE_MAX_ROWS)

SQL_TOOLS = ("run_sql", "submit_sql")


@dataclass
class QuestionResult:
    """What one question came to: the outcome, the SQL behind it, and what the run cost."""

    id: str
    question: str
    outcome: str
    sql: str = ""  # the answer, or the attempt that explains the failure
    golden_sql: str = ""
    reason: str = ""
    tool_calls: int = 0
    steps: list[Step] = field(default_factory=list)
    max_prompt_tokens: int = 0
    total_tokens: int = 0
    seconds: float = 0.0
    mode: str = "full"
    tags: list[str] = field(default_factory=list)
    # Bağlam bütçesinin üç sayısı ve submit edilip edilmediği (PLAN R4-11, R4-14).
    peak_estimate: int = 0
    trimmed: int = 0
    overflows: int = 0
    submitted: bool = False
    # Run 5 alanları (PLAN R5-12, Contracts): satırın hangi soru setinden geldiği, sorulduysa netleştirme.
    kind: str = "golden"
    clarification: dict | None = None
    narration_source: str | None = None


# Run 2 alanları (PLAN R2 Contracts): bir golden satırı bunları hiç yazmadıysa boş liste anlaşılır.
GOLDEN_LIST_FIELDS = ("tags", "requires_tables", "rules")


def load_golden(path: str | Path = config.GOLDEN_PATH) -> list[dict]:
    """The golden lines, blank lines skipped; the Run 2 list fields default to empty."""
    with open(path, encoding="utf-8") as handle:
        return [_with_defaults(json.loads(line)) for line in handle if line.strip()]


def _with_defaults(line: dict) -> dict:
    for name in GOLDEN_LIST_FIELDS:
        line.setdefault(name, [])
    return line


def run_eval(
    llm_factory,
    executor,
    golden: Iterable[dict] | None = None,
    only: Iterable[str] | None = None,
    *,
    schema: dict | None = None,
    mode: str = "full",
    tags: Iterable[str] | None = None,
    context: ToolContext | None = None,
    on_progress: Callable[[QuestionResult], None] | None = None,
    budget: int | None = None,
    clarify: bool = False,
    ambiguous: Iterable[dict] | None = None,
    lang: str = config.DEFAULT_LANG,
) -> list[QuestionResult]:
    """Ask every golden question of a fresh client and judge the answer; ``only`` keeps a few ids.

    ``tags`` keeps the questions carrying any of the listed tags, and the whole run happens in
    ``mode`` - with the ``context`` (index, graph, rules) that mode's tools need. ``on_progress`` is
    handed each question the moment it is judged, so a caller can stream the run to a screen instead
    of waiting for the whole set. ``budget`` is the per-request prompt budget the loop enforces
    (R4-11); a question that cannot fit it ends as ``context_overflow``.

    ``clarify`` opens the ask_clarification tool (R5-10) and ``ambiguous`` adds the ambiguous set
    after the golden ones: those lines have no golden answer to compare to, so asking is
    ``clarified``, submitting a guess is ``guessed``, anything else is its failure outcome.
    ``only``/``tags`` select from the golden set; the ambiguous lines are run as given.

    ``lang`` (R8-11) is the language of the sentences the runner writes itself - the reasons a
    verdict carries. Outcome codes are the report's own vocabulary and stay English in both.
    """
    lines = load_golden() if golden is None else list(golden)
    if only:
        wanted = {str(name).strip().upper() for name in only}
        lines = [line for line in lines if str(line.get("id", "")).upper() in wanted]
    if tags:
        wanted = {str(tag).strip() for tag in tags}
        lines = [line for line in lines if wanted & set(line.get("tags") or [])]
    document = doc.load_schema() if schema is None else schema
    if mode == "full_rules" and not (context and context.rules):
        # The loop refuses a contextless full_rules run on purpose - an empty rules list makes its
        # prompt identical to full's - so the runner wires the rules a caller did not pass. A
        # context that carries its own rules (a dataset's, R4-4) is left alone.
        rules = load_rules()
        context = (
            replace(context, rules=rules)
            if context is not None
            else ToolContext(executor=executor, schema=document, rules=rules, mode=mode)
        )
    if clarify:
        # R5-10: ask_clarification yalnız açık bağlamda görünen bir araç; kapalıyken araç listesi de
        # sistem istemi de Run 1-4 ile bayt aynı, o yüzden bağlama yalnız açınca dokunuyoruz.
        context = (
            replace(context, clarify=True)
            if context is not None
            else ToolContext(executor=executor, schema=document, mode=mode, clarify=True)
        )
    truths = [_truth(line, executor, lang) for line in lines]
    questions = [(line, "golden", truth) for line, truth in zip(lines, truths)]
    questions += [(line, "ambiguous", None) for line in list(ambiguous or ())]
    results = []
    for line, kind, truth in questions:
        qid = str(line.get("id") or "")
        run = run_agent(
            str(line.get("question") or ""),
            llm_factory(),
            executor,
            document,
            qid,
            mode=mode,
            context=context,
            budget=budget,
        )
        result = _result(line, run, executor, truth, mode, kind, lang)
        results.append(result)
        if on_progress:
            on_progress(result)
    return results


def progress_line(result: QuestionResult, lang: str = config.DEFAULT_LANG) -> str:
    """The one live line a finished question earns (Delight 4): id, ✓/✗, outcome, tool calls, cost.

    The outcome column is padded to its widest name so a run of these lines reads as columns. A
    clarified ambiguous question earns the check too: asking was the right thing to do (R5-12). The
    labels come from the catalog (R8-11); the outcome code between the mark and them does not.
    """
    return t(
        "eval.progress",
        lang,
        id=result.id,
        mark="✓" if result.outcome in CHECKED_OUTCOMES else "✗",
        outcome=f"{result.outcome:<{OUTCOME_WIDTH}}",
        tools=result.tool_calls,
        seconds=f"{result.seconds:.1f}",
        tokens=_tokens(result.total_tokens),
    )


def scored(results: Iterable[QuestionResult]) -> list[QuestionResult]:
    """Skoru taşıyan satırlar: belirsiz set netleştirmeyi ölçer, altın cevabın yerine geçmez (R5-12).

    Skorun üç göründüğü yer (report.json, report.md, konsol) aynı sayıyı saysın diye tek yerde
    durur. Altın satır yoksa boş döner - belirsiz satırların kendi skoru yoktur, kill-gate'i onlar
    vermez.
    """
    return [result for result in results if result.kind == "golden"]


def _truth(line: dict, executor, lang: str = config.DEFAULT_LANG) -> Result:
    """The golden answer, executed once up front so a broken ground truth stops the run early."""
    qid = str(line.get("id") or "")
    result = executor.execute(str(line.get("sql") or ""), COMPARE, qid)
    if result.error is not None:
        # ASSUMPTION: çalışmayan bir golden SQL ölçümün kendisinin bozuk olduğu anlamına gelir;
        # o soruyu yanlış sayıp devam etmek yerine koşuyu kırmak gerekir (PLAN Decision 13).
        raise RuntimeError(
            t("eval.golden_sql_failed", lang, qid=qid, reason=result.error.message)
        )
    return result


def _result(
    line: dict, run, executor, truth: Result | None, mode: str, kind: str, lang: str
) -> QuestionResult:
    outcome, reason, sql = _outcome(line, run, executor, truth, kind, lang)
    return QuestionResult(
        id=str(line.get("id") or ""),
        question=str(line.get("question") or ""),
        outcome=outcome,
        sql=sql,
        golden_sql=str(line.get("sql") or ""),
        reason=reason,
        tool_calls=sum(1 for step in run.steps if step.tool),
        steps=run.steps,
        max_prompt_tokens=run.max_prompt_tokens,
        total_tokens=run.total_prompt_tokens + run.total_completion_tokens,
        seconds=run.elapsed_s,
        mode=mode,
        tags=[str(tag) for tag in line.get("tags") or []],
        peak_estimate=run.peak_estimate,
        trimmed=run.trimmed,
        overflows=run.overflows,
        submitted=run.status == "submitted",
        kind=kind,
        clarification=run.clarification,
    )


def _outcome(
    line: dict, run, executor, truth: Result | None, kind: str, lang: str
) -> tuple[str, str, str]:
    """AgentRun + the executed answer + compare -> one of the outcomes, with a reason.

    A golden question is judged against its golden answer. An ambiguous line has no answer to
    compare to - every reading is a different number - so its verdict is about behaviour: the run
    that asked is ``clarified``, the one that committed to a reading is ``guessed`` (R5-12).

    Three of the reasons are the runner's own sentences; the rest are quoted from underneath - the
    executor's error, the comparator's difference, the loop's stop reason - and stay their language.
    """
    qid = str(line.get("id") or "")
    if run.status in ("llm_error", "timeout", "context_overflow"):
        return run.status, run.stop_reason, ""
    if run.status == "needs_clarification":
        asked = str((run.clarification or {}).get("question") or "")
        outcome = "clarified" if kind == "ambiguous" else "needs_clarification"
        return outcome, t("eval.reason.asked", lang, asked=asked), ""
    if run.status == "submitted":
        if kind == "ambiguous":
            # ASSUMPTION: hangi okunuşun "doğru" olduğu ölçülmez; belirsiz bir soruyu sormadan
            # cevaplamak brief'in guessed'ıdır, okunan sayıya bakılmaz (PLAN R5-12).
            return "guessed", t("eval.reason.guessed", lang), str(run.submitted_sql or "")
        return _verdict(line, str(run.submitted_sql or ""), executor, truth, qid, lang)
    # ASSUMPTION: submit etmemiş bir koşuda rapor için en işe yarar bilgi modelin üzerinde
    # kaldığı sorgudur; son deneme bir kez daha çalıştırılıp reddedilme sebebi outcome oluyor.
    attempt = _last_attempt(run)
    if attempt:
        error = executor.execute(attempt, COMPARE, qid).error
        if error is not None:
            return EXEC_OUTCOMES[error.kind], error.message, attempt
    return "no_submission", run.stop_reason or t("eval.reason.no_submit", lang), ""


def _verdict(
    line: dict, sql: str, executor, truth: Result, qid: str, lang: str = config.DEFAULT_LANG
) -> tuple[str, str, str]:
    result = executor.execute(sql, COMPARE, qid)
    if result.error is not None:
        return EXEC_OUTCOMES[result.error.kind], result.error.message, sql
    comparison = compare(truth, result, bool(line.get("ordered")), lang)
    if comparison.match:
        return "pass", "", sql
    return "wrong_result", comparison.reason, sql


def _last_attempt(run) -> str:
    """The SQL of the last query the model asked for; empty when it never asked for one."""
    for step in reversed(run.steps):
        if step.tool in SQL_TOOLS:
            return str(step.args.get("sql") or "")
    return ""


def _tokens(total: int) -> str:
    """A thousand and above reads short on a console (8123 -> 8.1K); below it the plain number."""
    return f"{total / 1000:.1f}K" if total >= 1000 else str(total)
