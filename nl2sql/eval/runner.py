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
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from nl2sql import config
from nl2sql.agent.loop import Step, run_agent
from nl2sql.engine.result import Budget, Result
from nl2sql.eval.compare import compare
from nl2sql.schema_map import doc

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


def load_golden(path: str | Path = config.GOLDEN_PATH) -> list[dict]:
    """The golden lines, blank lines skipped."""
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def run_eval(
    llm_factory,
    executor,
    golden: Iterable[dict] | None = None,
    only: Iterable[str] | None = None,
    *,
    schema: dict | None = None,
) -> list[QuestionResult]:
    """Ask every golden question of a fresh client and judge the answer; ``only`` keeps a few ids."""
    lines = load_golden() if golden is None else list(golden)
    if only:
        wanted = {str(name).strip().upper() for name in only}
        lines = [line for line in lines if str(line.get("id", "")).upper() in wanted]
    document = doc.load_schema() if schema is None else schema
    truths = [_truth(line, executor) for line in lines]
    results = []
    for line, truth in zip(lines, truths):
        qid = str(line.get("id") or "")
        run = run_agent(str(line.get("question") or ""), llm_factory(), executor, document, qid)
        results.append(_result(line, run, executor, truth))
    return results


def _truth(line: dict, executor) -> Result:
    """The golden answer, executed once up front so a broken ground truth stops the run early."""
    qid = str(line.get("id") or "")
    result = executor.execute(str(line.get("sql") or ""), COMPARE, qid)
    if result.error is not None:
        # ASSUMPTION: çalışmayan bir golden SQL ölçümün kendisinin bozuk olduğu anlamına gelir;
        # o soruyu yanlış sayıp devam etmek yerine koşuyu kırmak gerekir (PLAN Decision 13).
        raise RuntimeError(f"Golden SQL çalıştırılamadı ({qid}): {result.error.message}")
    return result


def _result(line: dict, run, executor, truth: Result) -> QuestionResult:
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
