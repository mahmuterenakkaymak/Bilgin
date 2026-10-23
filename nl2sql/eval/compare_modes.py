"""The same questions run in two modes, lined up: the verdict PLAN R2-13 asks for and what it rests on.

A comparison re-measures nothing. It takes the report each mode already committed and reads the two
numbers the rule turns on, so a reader never has to re-derive by eye a decision the plan wrote down
as arithmetic. The markdown is the same numbers as the json, and the json is what the CLI prints
from, which is the only reason the two can never disagree.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from nl2sql import config
from nl2sql.eval.report import REPORT_FILES, STAMP, _mark
from nl2sql.eval.runner import _tokens

COMPARE_OUT = config.EVAL_OUT / "compare"
REUSED_NOTE = "(önceki koşu)"
NO_FLIPS = "Hiçbir sorunun sonucu modlar arasında değişmedi."


def verdict(mode_reports: dict) -> dict:
    """R2-13: RAG kalır iff rag en az full_rules kadar geçiyor **ve** tepe bağlamı ondan düşük.

    İki koşuldan hangisi düşüyorsa satır onu iki sayısıyla birlikte söyler; okuyan kararın nedenini
    tabloyu yeniden kurmadan anlasın. Koşulların sırası sabit: skor, sonra bağlam.
    """
    rules = mode_reports.get("full_rules") or {}
    rag = mode_reports.get("rag") or {}
    rag_passed, rag_total = _score_of(rag)
    rule_passed, rule_total = _score_of(rules)
    rag_peak, rule_peak = _peak_of(rag), _peak_of(rules)
    if rag_passed < rule_passed:
        return {
            "keep_rag": False,
            "line": f"Karar: RAG yok — rag {rag_passed}/{rag_total} < full_rules {rule_passed}/{rule_total}.",
        }
    if rag_peak >= rule_peak:
        sign = "≥" if rag_peak == rule_peak else ">"
        return {
            "keep_rag": False,
            "line": (
                f"Karar: RAG yok — tepe bağlam {_tokens(rag_peak)} {sign} "
                f"{_tokens(rule_peak)} token."
            ),
        }
    return {
        "keep_rag": True,
        "line": (
            f"Karar: RAG kalır — rag {rag_passed}/{rag_total} ≥ full_rules {rule_passed}/{rule_total} "
            f"ve tepe bağlam {_tokens(rag_peak)} < {_tokens(rule_peak)} token."
        ),
    }


def flips(mode_reports: dict) -> list[dict]:
    """Sonucu modlar arasında farklı olan sorular: {id, outcomes:{mod:outcome}}.

    Bir modda hiç koşmamış sorunun sonucu uydurulmaz; o mod ``outcomes``'ta hiç yoktur. Tek modda
    koşmuş bir soru karşılaştırılacak ikinci bir sonuca sahip olmadığı için dönme sayılmaz.
    """
    seen: dict[str, dict[str, str]] = {}
    for mode, mode_report in mode_reports.items():
        for question in (mode_report or {}).get("questions") or []:
            if not isinstance(question, dict):
                continue
            qid, outcome = str(question.get("id") or ""), str(question.get("outcome") or "")
            if qid and outcome:
                seen.setdefault(qid, {})[mode] = outcome
    return [
        {"id": qid, "outcomes": outcomes}
        for qid, outcomes in sorted(seen.items())
        if len(set(outcomes.values())) > 1
    ]


def build_compare(
    mode_reports: dict, schema_tokens: int, reused: Iterable[str] | None = None
) -> dict:
    """Mod raporlarından karşılaştırma raporu: Contracts'ın compare report.json biçimi.

    ``reused`` hangi modların ``latest``ten alındığını söyler; ``schema_tokens`` şema metninin
    tahmini tokenı, yani full modun her soruya baştan yüklediği bağlam.
    """
    modes = _modes(mode_reports)
    taken = set(reused or ())
    return {
        "timestamp": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "model": _model(mode_reports),
        "questions": len(_ids(mode_reports)),
        "schema_tokens": int(schema_tokens or 0),
        "modes": {
            mode: _summary(mode, mode_reports[mode], mode in taken) for mode in modes
        },
        "flips": flips(mode_reports),
        "verdict": verdict(mode_reports),
    }


def write_compare(report: dict, out_dir: str | Path = COMPARE_OUT) -> Path:
    """``<out_dir>/<timestamp>/`` + ``<out_dir>/latest`` içine report.json ve report.md yazar."""
    stamp = datetime.now()
    out = Path(out_dir)
    run_dir = out / stamp.strftime(STAMP)
    _write(run_dir, report)
    _write(out / "latest", report)
    return run_dir


def reusable(report_json: dict | None, fingerprint: dict) -> bool:
    """R2-12: bir modun ``latest``i ancak imzası bu koşunun imzasıyla birebir eşitse yeniden koşulmaz.

    İmza modu, modeli, altın kümenin ve şemanın özetini taşır; birinin bile değişmesi iki koşuyu
    kıyaslanamaz kılar, o yüzden burada yarım tolerans yok.
    """
    if not isinstance(report_json, dict) or not isinstance(fingerprint, dict):
        return False
    stored = (report_json.get("config") or {}).get("fingerprint")
    return isinstance(stored, dict) and bool(fingerprint) and stored == fingerprint


# ------------------------------------------------------------------ parçalar


def _modes(mode_reports: dict) -> list[str]:
    """Modlar PLAN'ın sırasıyla yazılır; config.MODES dışındaki adlar alfabetik olarak sona gelir."""
    known = [mode for mode in config.MODES if mode in mode_reports]
    return known + sorted(set(mode_reports) - set(known))


def _ids(mode_reports: dict) -> list[str]:
    seen = {
        str(question.get("id") or "")
        for mode_report in mode_reports.values()
        for question in (mode_report or {}).get("questions") or []
        if isinstance(question, dict) and question.get("id")
    }
    return sorted(seen)


def _model(mode_reports: dict) -> str:
    return next(
        (str(report.get("model") or "") for report in mode_reports.values() if report.get("model")),
        "",
    )


def _score_of(mode_report: dict) -> tuple[int, int]:
    score = (mode_report or {}).get("score") or {}
    return int(score.get("passed") or 0), int(score.get("total") or 0)


def _peak_of(mode_report: dict) -> int:
    context = (mode_report or {}).get("context") or {}
    return int(context.get("max_prompt_tokens") or 0)


def _summary(mode: str, mode_report: dict, reused: bool) -> dict:
    questions = [
        question
        for question in (mode_report or {}).get("questions") or []
        if isinstance(question, dict)
    ]
    calls = [int(question.get("tool_calls") or 0) for question in questions]
    seconds = [float(question.get("seconds") or 0.0) for question in questions]
    score = (mode_report or {}).get("score") or {}
    context = (mode_report or {}).get("context") or {}
    return {
        "score": {
            "passed": int(score.get("passed") or 0),
            "total": int(score.get("total") or 0),
        },
        "tags": {
            tag: dict(counts) for tag, counts in ((mode_report or {}).get("tags") or {}).items()
        },
        "context": {
            "max_prompt_tokens": int(context.get("max_prompt_tokens") or 0),
            "median_prompt_tokens": int(context.get("median_prompt_tokens") or 0),
        },
        "tool_calls": {"mean": _mean(calls), "max": max(calls, default=0)},
        "seconds": {"mean": _mean(seconds), "total": round(sum(seconds), 1)},
        # ASSUMPTION: R2-12 modun rapor yolunu sabitler; build_compare'ın out_dir argümanı yok, o
        # yüzden yol config.EVAL_OUT'tan kurulur — koşan CLI da aynı yazar.
        "report": str(config.EVAL_OUT / mode / "latest" / REPORT_FILES[0]),
        "reused": reused,
    }


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 1) if values else 0.0


# ------------------------------------------------------------------ markdown


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
    modes = list(report["modes"])
    lines = [
        f"# Mod karşılaştırması — {report['model'] or 'model adı verilmemiş koşum'}",
        "",
        f"- Koşum: {report['timestamp']}",
        f"- Model: `{report['model'] or '-'}`",
        f"- Soru: {report['questions']}",
        f"- Şema tahmini: {_tokens(report['schema_tokens'])} token",
        "",
        "## Modlar",
        "",
        "| Mod | Skor | Bağlam (tepe/medyan) | Araç (ort/max) | Süre (ort/toplam) | Not |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for mode in modes:
        summary = report["modes"][mode]
        score, context = summary["score"], summary["context"]
        calls, seconds = summary["tool_calls"], summary["seconds"]
        lines.append(
            f"| {mode} | {score['passed']}/{score['total']} "
            f"| {_tokens(context['max_prompt_tokens'])} / {_tokens(context['median_prompt_tokens'])} "
            f"| {calls['mean']:.1f} / {calls['max']} "
            f"| {seconds['mean']:.1f} / {seconds['total']:.1f} sn "
            f"| {REUSED_NOTE if summary['reused'] else '-'} |"
        )
    lines += ["", f"**{report['verdict']['line']}**"]
    lines += _tag_lines(report, modes)
    lines += _flip_lines(report, modes)
    return "\n".join(lines) + "\n"


def _tag_lines(report: dict, modes: list[str]) -> list[str]:
    tags = sorted({tag for summary in report["modes"].values() for tag in summary["tags"]})
    if not tags:
        return []
    lines = [
        "",
        "## Etiket skorları",
        "",
        "| Etiket | " + " | ".join(modes) + " |",
        "| --- | " + " | ".join("---:" for _ in modes) + " |",
    ]
    for tag in tags:
        cells = []
        for mode in modes:
            counts = report["modes"][mode]["tags"].get(tag)
            cells.append(f"{counts['passed']}/{counts['total']}" if counts else "-")
        lines.append(f"| {tag} | " + " | ".join(cells) + " |")
    return lines


def _flip_lines(report: dict, modes: list[str]) -> list[str]:
    lines = ["", "## Dönen sorular", ""]
    if not report["flips"]:
        return lines + [NO_FLIPS]
    lines += [
        "| Soru | " + " | ".join(modes) + " |",
        "| --- | " + " | ".join("---" for _ in modes) + " |",
    ]
    for flip in report["flips"]:
        cells = []
        for mode in modes:
            outcome = flip["outcomes"].get(mode)
            cells.append(f"{_mark(outcome)} {outcome}" if outcome else "-")
        lines.append(f"| {flip['id']} | " + " | ".join(cells) + " |")
    return lines
