"""What an eval run leaves on disk: report.json for the next run, report.md for the reader.

The markdown is the artifact a person actually reads, so it opens with the score and the decision
that score implies, then one line per question, then a section each with the SQL that was answered
and why it did or did not match the golden one. ``latest`` is written from the same numbers as the
timestamped run, so a reader never finds a half-copied report.
"""

from __future__ import annotations

import dataclasses
import json
import statistics
from datetime import datetime
from pathlib import Path

from nl2sql import config
from nl2sql.eval.runner import QuestionResult

STAMP = "%Y%m%d-%H%M%S"
REPORT_FILES = ("report.json", "report.md")

# Karar 10 soru üzerinden verilir: 7+ devam, 5-6 yeniden kur, altında baştan düşün.
DECISIONS = (
    (7.0, "Devam — ölçüm bu yönde ilerlemeyi haklı çıkarıyor."),
    (5.0, "Yeniden kur — yaklaşımı gözden geçirmedikçe skor kendiliğinden yükselmeyecek."),
    (0.0, "Baştan düşün — bu sonuçlarla yola devam edilmez."),
)
NO_QUESTIONS = "Kararsız — koşulmuş soru yok, ölçüm boş."


def write_report(
    results: list[QuestionResult],
    out_dir: str | Path = config.EVAL_OUT,
    model: str = "",
    config: dict | None = None,
) -> Path:
    """Write ``eval_out/<timestamp>/report.json`` + ``report.md``, copy them to ``eval_out/latest``."""
    stamp = datetime.now()
    report = _report(results, model, config, stamp)
    out = Path(out_dir)
    run_dir = out / stamp.strftime(STAMP)
    _write(run_dir, report)
    _write(out / "latest", report)
    return run_dir


def _report(results: list[QuestionResult], model: str, settings: dict | None, stamp: datetime) -> dict:
    passed = sum(1 for result in results if result.outcome == "pass")
    peaks = [result.max_prompt_tokens for result in results]
    return {
        "timestamp": stamp.isoformat(sep=" ", timespec="seconds"),
        "model": model,
        "config": dict(settings or {}),
        "score": {"passed": passed, "total": len(results)},
        "decision": _decision(len(results), passed),
        "context": {
            "max_prompt_tokens": max(peaks, default=0),
            "median_prompt_tokens": round(statistics.median(peaks)) if peaks else 0,
        },
        "questions": [dataclasses.asdict(result) for result in results],
        "previous": None,
    }


def _decision(total: int, passed: int) -> str:
    """Karar satırı; eşikler 10 soru için verilmiştir, ``--only`` ile kısalan koşu orana göre ölçeklenir."""
    if not total:
        return NO_QUESTIONS
    points = 10 * passed / total
    return next(text for floor, text in DECISIONS if points >= floor)


def _write(directory: Path, report: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in REPORT_FILES:
        text = (
            json.dumps(report, ensure_ascii=False, indent=2)
            if name.endswith(".json")
            else _markdown(report)
        )
        (directory / name).write_text(text, encoding="utf-8")


def _markdown(report: dict) -> str:
    score, context = report["score"], report["context"]
    lines = [
        f"# Değerlendirme raporu — {report['model'] or 'model adı verilmemiş koşum'}",
        "",
        f"- Koşum: {report['timestamp']}",
        f"- Model: `{report['model'] or '-'}`",
    ]
    if report["config"]:
        settings = ", ".join(f"`{key}={value}`" for key, value in report["config"].items())
        lines.append(f"- Ayar: {settings}")
    lines += [
        "",
        f"## Skor: {score['passed']}/{score['total']}",
        "",
        f"**{report['decision']}**",
        "",
        f"Bağlam: tepe {context['max_prompt_tokens']} istem tokenı, medyan "
        f"{context['median_prompt_tokens']} istem tokenı.",
        "",
        "| Soru | Sonuç | Araç | Token | Süre |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for question in report["questions"]:
        lines.append(
            f"| {question['id']} | {_mark(question['outcome'])} {question['outcome']} "
            f"| {question['tool_calls']} | {question['total_tokens']} | {question['seconds']:.1f} sn |"
        )
    lines += ["", "## Sorular", ""]
    for question in report["questions"]:
        outcome = f"{question['id']} — {_mark(question['outcome'])} {question['outcome']}"
        lines += [f"### {outcome}", "", question["question"], ""]
        if question["reason"]:
            lines += [f"**Sebep:** {question['reason']}", ""]
        lines += ["Gönderilen SQL:", "", _sql(question["sql"]), ""]
        if question["golden_sql"] and question["golden_sql"] != question["sql"]:
            lines += ["Golden SQL:", "", _sql(question["golden_sql"]), ""]
    return "\n".join(lines) + "\n"


def _mark(outcome: str) -> str:
    return "✓" if outcome == "pass" else "✗"


def _sql(sql: str) -> str:
    return f"```sql\n{sql or '_cevap gönderilmedi_'}\n```"
