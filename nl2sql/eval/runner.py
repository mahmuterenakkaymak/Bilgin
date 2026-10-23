"""One golden question, end to end: the agent runs, the answer is executed, the outcome is decided.

The runner is where a run becomes a number. It re-decides nothing about what the model meant: the
submitted SQL goes to the same executor the model talked to, under the comparison budget so neither
side loses rows, and the verdict comes from compare(). All eight outcomes are named here, which is
also why a run that never submitted is not automatically just ``no_submission`` - the query that
killed it (a policy reject, a missing column) says far more in the report than the absence of a
submit, so the model's last attempt is executed once more to name the blocker.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from nl2sql import config
from nl2sql.agent.loop import Step, run_agent
from nl2sql.agent.modes import ToolContext
from nl2sql.engine.result import Budget, Result
from nl2sql.eval.compare import compare
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
)

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
) -> list[QuestionResult]:
    """Ask every golden question of a fresh client and judge the answer; ``only`` keeps a few ids.

    ``tags`` keeps the questions carrying any of the listed tags, and the whole run happens in
    ``mode`` - with the ``context`` (index, graph, rules) that mode's tools need. ``on_progress`` is
    handed each question the moment it is judged, so a caller can stream the run to a screen instead
    of waiting for the whole set.
    """
    lines = load_golden() if golden is None else list(golden)
    if only:
        wanted = {str(name).strip().upper() for name in only}
        lines = [line for line in lines if str(line.get("id", "")).upper() in wanted]
    if tags:
        wanted = {str(tag).strip() for tag in tags}
        lines = [line for line in lines if wanted & set(line.get("tags") or [])]
    document = doc.load_schema() if schema is None else schema
    if context is None and mode == "full_rules":
        # The loop refuses a contextless full_rules run on purpose - an empty rules list makes its
        # prompt identical to full's - so the runner wires the rules a caller did not pass.
        context = ToolContext(executor=executor, schema=document, rules=load_rules(), mode=mode)
    truths = [_truth(line, executor) for line in lines]
    results = []
    for line, truth in zip(lines, truths):
        qid = str(line.get("id") or "")
        run = run_agent(
            str(line.get("question") or ""),
            llm_factory(),
            executor,
            document,
            qid,
            mode=mode,
            context=context,
        )
        result = _result(line, run, executor, truth, mode)
        results.append(result)
        if on_progress:
            on_progress(result)
    return results


def progress_line(result: QuestionResult) -> str:
    """The one live line a finished question earns (Delight 4): id, ✓/✗, outcome, tool calls, cost.

    The outcome column is padded to its widest name so a run of these lines reads as columns.
    """
    mark = "✓" if result.outcome == "pass" else "✗"
    return (
        f"{result.id} {mark} {result.outcome:<{OUTCOME_WIDTH}} {result.tool_calls} araç  "
        f"{result.seconds:.1f} sn  {_tokens(result.total_tokens)} token"
    )


def _truth(line: dict, executor) -> Result:
    """The golden answer, executed once up front so a broken ground truth stops the run early."""
    qid = str(line.get("id") or "")
    result = executor.execute(str(line.get("sql") or ""), COMPARE, qid)
    if result.error is not None:
        # ASSUMPTION: çalışmayan bir golden SQL ölçümün kendisinin bozuk olduğu anlamına gelir;
        # o soruyu yanlış sayıp devam etmek yerine koşuyu kırmak gerekir (PLAN Decision 13).
        raise RuntimeError(f"Golden SQL çalıştırılamadı ({qid}): {result.error.message}")
    return result


def _result(line: dict, run, executor, truth: Result, mode: str) -> QuestionResult:
    outcome, reason, sql = _outcome(line, run, executor, truth)
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
    )


def _outcome(line: dict, run, executor, truth: Result) -> tuple[str, str, str]:
    """AgentRun + the executed answer + compare -> one of the eight outcomes, with a reason."""
    qid = str(line.get("id") or "")
    if run.status in ("llm_error", "timeout"):
        return run.status, run.stop_reason, ""
    if run.status == "submitted":
        return _verdict(line, str(run.submitted_sql or ""), executor, truth, qid)
    # ASSUMPTION: submit etmemiş bir koşuda rapor için en işe yarar bilgi modelin üzerinde
    # kaldığı sorgudur; son deneme bir kez daha çalıştırılıp reddedilme sebebi outcome oluyor.
    attempt = _last_attempt(run)
    if attempt:
        error = executor.execute(attempt, COMPARE, qid).error
        if error is not None:
            return EXEC_OUTCOMES[error.kind], error.message, attempt
    return "no_submission", run.stop_reason or "submit_sql hiç çağrılmadı.", ""


def _verdict(line: dict, sql: str, executor, truth: Result, qid: str) -> tuple[str, str, str]:
    result = executor.execute(sql, COMPARE, qid)
    if result.error is not None:
        return EXEC_OUTCOMES[result.error.kind], result.error.message, sql
    comparison = compare(truth, result, bool(line.get("ordered")))
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
