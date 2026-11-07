# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

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
from nl2sql.i18n import t

COMPARE_OUT = config.EVAL_OUT / "compare"
# R8-12: satırlar kataloğun ``compare.*`` anahtarlarıdır; üç sabit yine adlarıyla durur - testler
# ve CLI onları buradan okur, değerleri tr'nindir.
REUSED_NOTE = t("compare.reused_note", config.DEFAULT_LANG)
NO_FLIPS = t("compare.no_flips", config.DEFAULT_LANG)
# R3-11: iki modun ortalaması kendi dalgalanmasından az farklıysa ölçülen fark kendi gürültüsünden
# küçük demektir; satır bunu adıyla söyler, çünkü "kaldı" da "yok" da o durumda uydurma olur.
NOISE = t("compare.noise", config.DEFAULT_LANG)


def verdict(mode_reports: dict, lang: str = config.DEFAULT_LANG) -> dict:
    """R2-13: RAG kalır iff rag en az full_rules kadar geçiyor **ve** tepe bağlamı ondan düşük.

    İki koşuldan hangisi düşüyorsa satır onu iki sayısıyla birlikte söyler; okuyan kararın nedenini
    tabloyu yeniden kurmadan anlasın. Koşulların sırası sabit: skor, sonra bağlam. R3-11: mod
    listesiyle çağrılırsa karar tekrarların ortalamasıyla kurulur ve fark herhangi bir modun
    yayılımından küçükse satır gürültüyü adıyla anar. ``lang`` (R8-12) satırın dilidir; kararın
    kendisi ``keep_rag``dir, iki dilde de aynı.
    """
    rules, rag = _runs(mode_reports.get("full_rules")), _runs(mode_reports.get("rag"))
    rag_mean, rule_mean = _mean(_passed(rag)), _mean(_passed(rules))
    rag_total, rule_total = _totals(rag), _totals(rules)
    rag_peak, rule_peak = _peaks(rag), _peaks(rules)
    noisy = abs(rag_mean - rule_mean) < max(_spread(rag), _spread(rules))
    if rag_mean < rule_mean:
        keep, text = False, t(
            "compare.verdict.no_score",
            lang,
            rag=_score_text(rag_mean, rag_total),
            rules=_score_text(rule_mean, rule_total),
        )
    elif rag_peak >= rule_peak:
        sign = "≥" if rag_peak == rule_peak else ">"
        keep, text = False, t(
            "compare.verdict.no_peak",
            lang,
            rag_peak=_tokens(rag_peak),
            sign=sign,
            rule_peak=_tokens(rule_peak),
        )
    else:
        keep, text = True, t(
            "compare.verdict.keep",
            lang,
            rag=_score_text(rag_mean, rag_total),
            rules=_score_text(rule_mean, rule_total),
            rag_peak=_tokens(rag_peak),
            rule_peak=_tokens(rule_peak),
        )
    noise = "; " + t("compare.noise", lang) if noisy else ""
    return {"keep_rag": keep, "line": f"{text}{noise}."}


def flips(mode_reports: dict) -> list[dict]:
    """Sonucu modlar arasında farklı olan sorular: {id, outcomes:{mod:outcome}}.

    Bir modda hiç koşmamış sorunun sonucu uydurulmaz; o mod ``outcomes``'ta hiç yoktur. Tek modda
    koşmuş bir soru karşılaştırılacak ikinci bir sonuca sahip olmadığı için dönme sayılmaz.
    Tekrarlı koşuda modlar kendi birincil ölçümüyle girer; bir modun kendi içindeki dönüşü
    ``flips_within_mode`` sayar, yoksa aynı soru iki yerde iki farklı şey gibi görünürdü.
    """
    seen: dict[str, dict[str, str]] = {}
    for mode, mode_report in mode_reports.items():
        for question in _questions(_primary(_runs(mode_report))):
            qid, outcome = str(question.get("id") or ""), str(question.get("outcome") or "")
            if qid and outcome:
                seen.setdefault(qid, {})[mode] = outcome
    return [
        {"id": qid, "outcomes": outcomes}
        for qid, outcomes in sorted(seen.items())
        if len(set(outcomes.values())) > 1
    ]


def flips_within_mode(mode_reports: dict) -> int:
    """R3-11: kendi tekrarları arasında sonucu değişen kaç soru var (aynı soru bir kez sayılır).

    Tek ölçümü olan mod dönecek bir şey ölçmemiştir, sayılmaz; yayılımı olmayan bir ölçüm gürültü
    kanıtı değildir.
    """
    unstable: set[str] = set()
    for mode_report in mode_reports.values():
        runs = _runs(mode_report)
        if len(runs) < 2:
            continue
        outcomes: dict[str, set[str]] = {}
        for run in runs:
            for question in _questions(run):
                qid = str(question.get("id") or "")
                if qid:
                    outcomes.setdefault(qid, set()).add(str(question.get("outcome") or ""))
        unstable.update(qid for qid, seen in outcomes.items() if len(seen) > 1)
    return len(unstable)


def build_compare(
    mode_reports: dict,
    schema_tokens: int,
    reused: Iterable[str] | None = None,
    lang: str = config.DEFAULT_LANG,
) -> dict:
    """Mod raporlarından karşılaştırma raporu: Contracts'ın compare report.json biçimi.

    ``reused`` hangi modların ``latest``ten alındığını söyler; ``schema_tokens`` şema metninin
    tahmini tokenı, yani full modun her soruya baştan yüklediği bağlam.

    R3-11: bir modun değeri liste ise o modun tekrarlarıdır ve rapora ``repeat``, mod başına
    ``scores`` ile etiket başına yayılım ve ``flips_within_mode`` eklenir. Tek ölçümde bu alanlar
    hiç yazılmaz — Contracts'ın ``"repeat":int=1`` satırı yokluğu 1 der, Run 2 raporu da böylece
    değişmeden kalır.

    ``lang`` (R8-12) karar satırının ve report.md'nin dilidir; diskteki rapor hangi dille
    yazıldığını ``lang`` alanıyla kendisi söyler. Türkçe varsayılanın dışına ancak ``en`` istendiğinde
    çıkılır, yani Run 2 raporu anahtar kümesini korur.
    """
    modes = _modes(mode_reports)
    taken = set(reused or ())
    repeat = max((len(_runs(value)) for value in mode_reports.values()), default=1)
    comparison = {
        "timestamp": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "model": _model(mode_reports),
        "questions": len(_ids(mode_reports)),
        "schema_tokens": int(schema_tokens or 0),
        **({"lang": lang} if lang != config.DEFAULT_LANG else {}),
        "modes": {
            mode: _summary(mode, mode_reports[mode], mode in taken) for mode in modes
        },
        "flips": flips(mode_reports),
        "verdict": verdict(mode_reports, lang),
    }
    if repeat > 1:
        comparison["repeat"] = repeat
        comparison["flips_within_mode"] = flips_within_mode(mode_reports)
    return comparison


def write_compare(report: dict, out_dir: str | Path = COMPARE_OUT) -> Path:
    """``<out_dir>/<timestamp>/`` + ``<out_dir>/latest`` içine report.json ve report.md yazar."""
    stamp = datetime.now()
    out = Path(out_dir)
    run_dir = out / stamp.strftime(STAMP)
    _write(run_dir, report)
    _write(out / "latest", report)
    return run_dir


def reusable(report_json: dict | None, fingerprint: dict, embedder: str | None = None) -> bool:
    """R2-12: bir modun ``latest``i ancak imzası bu koşunun imzasıyla birebir eşitse yeniden koşulmaz.

    İmza modu, modeli, altın kümenin ve şemanın özetini taşır; birinin bile değişmesi iki koşuyu
    kıyaslanamaz kılar, o yüzden burada yarım tolerans yok. ``embedder`` verildiyse rag'in vektör
    uzayı da kayıtlı koşununkiyle aynı olmalı: ``NL2SQL_EMBED_MODEL`` değişip indeks yeniden
    kurulunca içerik imzası aynı kalıyor, yani uzaysız karar bayat bir koşuyla kurulurdu.
    """
    if not isinstance(report_json, dict) or not isinstance(fingerprint, dict):
        return False
    settings = report_json.get("config") or {}
    stored = settings.get("fingerprint")
    if not (isinstance(stored, dict) and fingerprint) or stored != fingerprint:
        return False
    return embedder is None or settings.get("embedder", "") == embedder


# ------------------------------------------------------------------ parçalar


def _modes(mode_reports: dict) -> list[str]:
    """Modlar PLAN'ın sırasıyla yazılır; config.MODES dışındaki adlar alfabetik olarak sona gelir."""
    known = [mode for mode in config.MODES if mode in mode_reports]
    return known + sorted(set(mode_reports) - set(known))


def _ids(mode_reports: dict) -> list[str]:
    seen = {
        str(question.get("id") or "")
        for mode_report in mode_reports.values()
        for run in _runs(mode_report)
        for question in _questions(run)
        if question.get("id")
    }
    return sorted(seen)


def _model(mode_reports: dict) -> str:
    return next(
        (
            str(run["model"])
            for mode_report in mode_reports.values()
            for run in _runs(mode_report)
            if run.get("model")
        ),
        "",
    )


def _score_of(mode_report: dict) -> tuple[int, int]:
    score = (mode_report or {}).get("score") or {}
    return int(score.get("passed") or 0), int(score.get("total") or 0)


def _peak_of(mode_report: dict) -> int:
    context = (mode_report or {}).get("context") or {}
    return int(context.get("max_prompt_tokens") or 0)


def _summary(mode: str, mode_report: dict, reused: bool) -> dict:
    runs = _runs(mode_report)
    primary = _primary(runs)
    questions = _questions(primary)
    calls = [int(question.get("tool_calls") or 0) for question in questions]
    seconds = [float(question.get("seconds") or 0.0) for question in questions]
    score = (primary or {}).get("score") or {}
    context = (primary or {}).get("context") or {}
    return {
        "score": {
            "passed": int(score.get("passed") or 0),
            "total": int(score.get("total") or 0),
        },
        **({"scores": _stats(_passed(runs))} if len(runs) > 1 else {}),
        "tags": _tags(runs),
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


def _tags(runs: list[dict]) -> dict:
    """Etiket başına skor: birincil koşunun passed/total'ı, tekrarlıda yayılımı da (R3-11).

    Bir tekrarda etiket hiç yoksa o ölçüm yayılıma girmez; olmayan bir koşuyu 0 saymak etiketi
    olmayan bir modu kendisiyle çelişen iki ölçüm gibi gösterirdi.
    """
    tags = list(dict.fromkeys(tag for run in runs for tag in (run.get("tags") or {})))
    summary = {}
    for tag in tags:
        counts = [item for item in ((run.get("tags") or {}).get(tag) for run in runs) if item]
        first = counts[0] if counts else {}
        entry = {
            "passed": int(first.get("passed") or 0),
            "total": int(first.get("total") or 0),
        }
        if len(counts) > 1:
            entry["scores"] = _stats([int(item.get("passed") or 0) for item in counts])
        summary[tag] = entry
    return summary


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 1) if values else 0.0


def _stats(values: list[int]) -> dict:
    """Yayılımın üç sayısı: tek ölçümde üçü de aynıdır, yani spread 0 ve gürültü yok."""
    return {
        "mean": _mean([float(value) for value in values]),
        "min": min(values, default=0),
        "max": max(values, default=0),
    }


def _runs(mode_report) -> list[dict]:
    """Modun ölçümleri: tek rapor da tekrar listesi de aynı kapıdan geçer (R3-11)."""
    if isinstance(mode_report, list):
        return [run for run in mode_report if isinstance(run, dict)]
    return [mode_report] if isinstance(mode_report, dict) else []


def _primary(runs: list[dict]) -> dict:
    """Tek ölçüm okuyan alanların (skor, bağlam, araç, süre, modlar arası dönüş) referans koşusu.

    ASSUMPTION: R3-11 tekrarlar arasında birini "asıl" diye sıralamaz; hangisi önce yazıldıysa o
    okunur, tekrarların kendisi ``scores`` ve ``flips_within_mode`` olarak ayrıca durur.
    """
    return runs[0] if runs else {}


def _questions(mode_report: dict) -> list[dict]:
    return [
        question
        for question in (mode_report or {}).get("questions") or []
        if isinstance(question, dict)
    ]


def _passed(runs: list[dict]) -> list[int]:
    return [_score_of(run)[0] for run in runs]


def _totals(runs: list[dict]) -> int:
    return max((_score_of(run)[1] for run in runs), default=0)


def _peaks(runs: list[dict]) -> int:
    return max((_peak_of(run) for run in runs), default=0)


def _spread(runs: list[dict]) -> int:
    """Tekrarların yayılımı: en iyi ile en kötü koşul arasındaki fark; tek ölçümde 0."""
    passed = _passed(runs)
    return (max(passed) - min(passed)) if passed else 0


def _score_text(mean: float, total: int) -> str:
    return f"{_num(mean)}/{total}"


def _num(value: float) -> str:
    """Ortalama tam sayıya düşüyorsa ondalık yazılmaz: 2.0 -> 2, 2.33 -> 2.3."""
    return str(int(value)) if float(value).is_integer() else f"{value:.1f}"


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


def score_cell(summary: dict) -> str:
    """Skor hanesi: tek ölçümde ``7/10``, tekrarlıda ``6.7/6/7`` (ort/min/max) — CLI de bunu yazar."""
    spread = summary.get("scores")
    if spread:
        return f"{_num(spread['mean'])}/{spread['min']}/{spread['max']}"
    score = summary["score"]
    return f"{score['passed']}/{score['total']}"


def _markdown(report: dict) -> str:
    lang = report.get("lang", config.DEFAULT_LANG)
    modes = list(report["modes"])
    repeat = report.get("repeat", 1)
    score_column = (
        t("compare.md.col_score_spread", lang) if repeat > 1 else t("compare.md.col_score", lang)
    )
    lines = [
        t("compare.md.title", lang, model=report["model"] or t("compare.md.unnamed", lang)),
        "",
        t("compare.md.stamp", lang, timestamp=report["timestamp"]),
        t("compare.md.model", lang, model=report["model"] or "-"),
        t("compare.md.questions", lang, questions=report["questions"]),
        *(
            [
                t("compare.md.repeat", lang, repeat=repeat),
                t("compare.md.flips_within", lang, count=report.get("flips_within_mode", 0)),
            ]
            if repeat > 1
            else []
        ),
        t("compare.md.schema_tokens", lang, tokens=_tokens(report["schema_tokens"])),
        "",
        t("compare.md.modes_head", lang),
        "",
        f"| {t('compare.md.col_mode', lang)} | {score_column} "
        f"| {t('compare.md.col_context', lang)} | {t('compare.md.col_tools', lang)} "
        f"| {t('compare.md.col_seconds', lang)} | {t('compare.md.col_note', lang)} |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for mode in modes:
        summary = report["modes"][mode]
        context = summary["context"]
        calls, seconds = summary["tool_calls"], summary["seconds"]
        note = t("compare.reused_note", lang) if summary["reused"] else "-"
        elapsed = t(
            "compare.md.seconds_cell",
            lang,
            mean=f"{seconds['mean']:.1f}",
            total=f"{seconds['total']:.1f}",
        )
        lines.append(
            f"| {mode} | {score_cell(summary)} "
            f"| {_tokens(context['max_prompt_tokens'])} / {_tokens(context['median_prompt_tokens'])} "
            f"| {calls['mean']:.1f} / {calls['max']} "
            f"| {elapsed} "
            f"| {note} |"
        )
    lines += ["", f"**{report['verdict']['line']}**"]
    lines += _tag_lines(report, modes, lang)
    lines += _flip_lines(report, modes, lang)
    return "\n".join(lines) + "\n"


def _tag_lines(report: dict, modes: list[str], lang: str) -> list[str]:
    tags = sorted({tag for summary in report["modes"].values() for tag in summary["tags"]})
    if not tags:
        return []
    lines = [
        "",
        t("compare.md.tags_head", lang),
        "",
        f"| {t('compare.md.col_tag', lang)} | " + " | ".join(modes) + " |",
        "| --- | " + " | ".join("---:" for _ in modes) + " |",
    ]
    for tag in tags:
        cells = []
        for mode in modes:
            counts = report["modes"][mode]["tags"].get(tag)
            spread = (counts or {}).get("scores")
            cells.append(
                f"{_num(spread['mean'])}/{spread['min']}/{spread['max']}"
                if spread
                else (f"{counts['passed']}/{counts['total']}" if counts else "-")
            )
        lines.append(f"| {tag} | " + " | ".join(cells) + " |")
    return lines


def _flip_lines(report: dict, modes: list[str], lang: str) -> list[str]:
    lines = ["", t("compare.md.flips_head", lang), ""]
    if not report["flips"]:
        return lines + [t("compare.no_flips", lang)]
    lines += [
        f"| {t('compare.md.col_question', lang)} | " + " | ".join(modes) + " |",
        "| --- | " + " | ".join("---" for _ in modes) + " |",
    ]
    for flip in report["flips"]:
        cells = []
        for mode in modes:
            outcome = flip["outcomes"].get(mode)
            cells.append(f"{_mark(outcome)} {outcome}" if outcome else "-")
        lines.append(f"| {flip['id']} | " + " | ".join(cells) + " |")
    return lines
