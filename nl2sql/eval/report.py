# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""What an eval run leaves on disk: report.json for the next run, report.md for the reader.

The markdown is the artifact a person actually reads, so it opens with the score and the decision
that score implies, then one line per question, then a section each with the SQL that was answered
and why it did or did not match the golden one. ``latest`` is written from the same numbers as the
timestamped run, so a reader never finds a half-copied report.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import statistics
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from nl2sql import config
from nl2sql.eval.metrics import compute_metrics
from nl2sql.eval.runner import QuestionResult, scored
from nl2sql.i18n import t
from nl2sql.report import fmt

STAMP = "%Y%m%d-%H%M%S"
REPORT_FILES = ("report.json", "report.md")

# Karar 10 soru üzerinden verilir: 7+ devam, 5-6 yeniden kur, altında baştan düşün. Koşumun kararı
# ``_decision``dan dilde gelir; ``DECISIONS`` ve ``NO_QUESTIONS`` aynı kararların Türkçe halidir -
# eşiği ve boş koşumu adıyla okuyan testler oradan bakar (R8-11).
DECISION_KEYS = (
    (7.0, "eval.decision.go"),
    (5.0, "eval.decision.rebuild"),
    (0.0, "eval.decision.redesign"),
)
DECISIONS = tuple((floor, t(key, config.DEFAULT_LANG)) for floor, key in DECISION_KEYS)
NO_QUESTIONS = t("eval.no_questions", config.DEFAULT_LANG)

# Metrik bloğunun satır sırası ve adlarının kataloğa giden anahtarları (PLAN R5-14, R8-11): ekran
# ile report.md aynı listeyi okur, yani iki yerde iki ayrı ad uydurulamaz. Paydası olmayan oran
# ``–`` ile durur (R5-12).
METRIC_ROWS = (
    ("accuracy", "eval.metric.accuracy"),
    ("answered_pct", "eval.metric.answered"),
    ("accuracy_when_answered", "eval.metric.accuracy_when_answered"),
    ("wrong_answer_rate", "eval.metric.wrong_answer"),
    ("clarify_precision", "eval.metric.clarify_precision"),
    ("clarify_recall", "eval.metric.clarify_recall"),
)


def write_report(
    results: list[QuestionResult],
    out_dir: str | Path = config.EVAL_OUT,
    model: str = "",
    config: dict | None = None,
    mode: str = "full",
    schema_info: dict | None = None,
    dataset: str = config.DEFAULT_DATASET,
    profile: dict | None = None,
    narration: dict | None = None,
    followups: dict | None = None,
    followup_chains: list | None = None,
    lang: str = config.DEFAULT_LANG,
) -> Path:
    """Write ``<out_dir>/<timestamp>/report.json`` + ``report.md``, copy them to ``<out_dir>/latest``.

    ``latest`` holds the previous run, so it is read before it is replaced: that is the only place
    the run-to-run delta can come from. Since the delta is only honest between equal measurements,
    the caller hands in the mode's own directory (``eval_out/<mode>``, PLAN R2-12) and ``out_dir``
    itself keeps the plain ``<ts>`` + ``latest`` shape.

    ``schema_info`` (``schema_info()`` below) is what the run was measured against; a caller that
    does not name one leaves the field out rather than writing an empty schema nobody loaded.
    ``dataset`` names the world the run measured (PLAN R4-4), so two datasets' reports never read
    as each other's continuation. ``profile`` is the model profile the run was measured with
    (PLAN R4-14) - the same rule as ``schema_info``: no profile, no field. ``narration`` is the
    narrator's own count (PLAN R5-13) and stays null for a run that never narrated; the metrics
    block is not a caller's choice at all - every run has answered/wrong/clarification numbers.

    ``followups`` is the ``eval --followups`` block (PLAN R7-14, Contracts "followups report") and
    stays out of the report when the run measured no chains; ``followup_chains`` carries the chain
    questions the markdown table shows but the json block does not repeat.

    ``lang`` (PLAN R8-11) is the language the markdown is written in; it is recorded in report.json
    as ``lang`` so a reader knows which language a stored report speaks. Numbers and outcome codes
    are not translated - only the sentences around them.
    """
    stamp = datetime.now()
    out = Path(out_dir)
    previous = _load(out / "latest" / REPORT_FILES[0])
    report = _report(
        results, model, config, stamp, previous, mode, schema_info, dataset, profile, narration,
        followups, lang,
    )
    run_dir = out / stamp.strftime(STAMP)
    _write(run_dir, report, followup_chains)
    _write(out / "latest", report, followup_chains)
    return run_dir


def fingerprint(
    mode: str,
    llm: str,
    model: str,
    golden: Iterable[dict],
    schema: dict,
    rules: list[dict],
    index_hash: str,
    max_tool_calls: int,
    dataset: str | None = None,
    budget: int | None = None,
    clarify: bool = False,
) -> dict:
    """Bir koşunun neyi ölçtüğünün imzası: iki koşun farkı ancak imzaları eşitse kıyaslanabilir.

    ``golden`` sorunun kimliği, metni, SQL'i ve sıralı bayrağıyla girer; inceleme notu gibi ölçümü
    değiştirmeyen bir alanın iki koşuyu kıyaslanamaz kılması yanlış olurdu. ``index_hash`` rag'e
    aittir, diğer modlar boş verir. ``dataset`` yalnız varsayılanın adı değilse yazılır (R4-4):
    iki kümenin imzaları birbirine karışmasın, ama varsayılanla ölçmüş Run 3 koşuları kendi
    imzalarını korusun, yoksa diskteki ``latest``leri bir daha hiç yeniden kullanılamazdı.
    ``budget`` de aynı kuraldadır (R4-10): yalnız ``--model`` bir bütçe verdiğinde yazılır, çünkü
    aynı model iki farklı pencerede iki farklı ölçümdür. ``clarify`` de öyledir (R5-12): belirsiz
    seti koşan bir ölçüm, altın seti koşanla aynı değildir, çünkü cevap sayılan şeyler değişir.
    """
    lines = list(golden)
    return {
        "mode": mode,
        "llm": llm,
        "model": model,
        "question_ids": [str(line.get("id") or "") for line in lines],
        "golden_hash": _digest(
            [
                {
                    "id": str(line.get("id") or ""),
                    "question": str(line.get("question") or ""),
                    "sql": str(line.get("sql") or ""),
                    "ordered": bool(line.get("ordered")),
                }
                for line in lines
            ]
        ),
        "schema_hash": _digest(schema),
        "rules_hash": _digest(rules),
        "index_hash": index_hash,
        "max_tool_calls": max_tool_calls,
        **({"dataset": dataset} if dataset and dataset != config.DEFAULT_DATASET else {}),
        **({"budget": budget} if budget is not None else {}),
        **({"clarify": True} if clarify else {}),
    }


def schema_info(path: str | Path, schema: dict) -> dict:
    """The ``schema`` field of report.json (PLAN R3-5): which file the run measured, and its digest.

    The hash is over the schema document as loaded, so two copies of the same content agree and a
    merged or introspected schema never reads as if ``schema.json`` had been used.
    """
    return {"path": str(path), "hash": _digest(schema)}


def _digest(value) -> str:
    """Kanonik JSON'un sha256'sı; anahtar sırası ve biçim imzayı değiştirmez."""
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _load(path: Path) -> dict | None:
    """Önceki koşunun raporu; okunamazsa (yok, yarı yazılmış, bozuk) None - delta bölümü yazılmaz."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _report(
    results: list[QuestionResult],
    model: str,
    settings: dict | None,
    stamp: datetime,
    previous: dict | None = None,
    mode: str = "full",
    schema_info: dict | None = None,
    dataset: str = config.DEFAULT_DATASET,
    profile: dict | None = None,
    narration: dict | None = None,
    followups: dict | None = None,
    lang: str = config.DEFAULT_LANG,
) -> dict:
    # Kill-gate skoru altın setin sayısıdır (R5-12): belirsiz satırlar netleştirmeyi ölçer, altın
    # cevabın yerine geçmez. Metrik bloğunun hemen üstünde başka bir paydaya bölünmüş bir skor,
    # aynı koşunun iki ayrı ölçümü gibi okunur ve karar eşiklerini aşağı çeker.
    judged = scored(results)
    passed = sum(1 for result in judged if result.outcome == "pass")
    peaks = [result.max_prompt_tokens for result in results]
    # R4-11: bütçenin iki sayısı. Koşuda ne tepe tahmin ne taşma varsa hiç yazılmazlar (``schema``
    # gibi) - ikisi de sıfırken okuyana hiçbir şey söylemeyen bir satır, diskteki eski raporların
    # context sözlüğünü de kendi haliyle okunamaz kılardı.
    budget = {
        "peak_estimate": max((result.peak_estimate for result in results), default=0),
        "overflows": sum(1 for result in results if result.overflows),
    }
    return {
        "timestamp": stamp.isoformat(sep=" ", timespec="seconds"),
        "model": model,
        "mode": mode,
        "dataset": dataset,
        # Raporun dili (R8-11): diske yazılan report.md hangi dilde okunacağını kendisi söyler.
        "lang": lang,
        **({"profile": profile} if profile else {}),
        **({"schema": schema_info} if schema_info else {}),
        "config": dict(settings or {}),
        "score": {"passed": passed, "total": len(judged)},
        "tags": _tags(results),
        "decision": _decision(len(judged), passed, lang),
        "context": {
            "max_prompt_tokens": max(peaks, default=0),
            "median_prompt_tokens": round(statistics.median(peaks)) if peaks else 0,
            **(budget if budget["peak_estimate"] or budget["overflows"] else {}),
        },
        # Metrikler her koşunun sayısıdır (R5-12): belirsiz set koşulmamışsa netleştirme oranları
        # null'dır, yani "ölçülmedi" ile "hiç netleştirme olmadı" ayrımı diskte de durur.
        "metrics": compute_metrics(results),
        "narration": narration,
        # Ardışık sorular yalnız ``--followups`` koşumunda ölçülür (R7-14): ölçmeyen koşumda anahtar
        # hiç yoktur, yani "zincir yok" ile "zincir koşulmadı" ayrımı diskte de durur.
        **({"followups": followups} if followups else {}),
        "questions": [dataclasses.asdict(result) for result in results],
        "previous": _delta(previous, results),
    }


def _delta(previous: dict | None, results: list[QuestionResult]) -> dict | None:
    """Önceki koşuya göre değişim: skor farkı ve sonucu dönen sorular.

    Önceki rapor yoksa ya da skor satırı yarım/bozuksa None döner; uydurma bir fark göstermektense
    bölüm hiç yazılmaz. ``--only`` ile kısalan koşuda iki tarafta da olan sorular karşılaştırılır
    ve ``delta`` yalnız o ortak sorular üzerinden hesaplanır; diğer koşunun toplamı değildir.
    """
    score = (previous or {}).get("score")
    score = score if isinstance(score, dict) else {}
    passed, total = score.get("passed"), score.get("total")
    if not isinstance(passed, int) or not isinstance(total, int):
        return None
    before = {
        question["id"]: question.get("outcome", "")
        for question in previous.get("questions") or []
        if isinstance(question, dict) and question.get("id")
    }
    shared = {result.id for result in results if result.id in before}
    now = sum(1 for result in results if result.id in shared and result.outcome == "pass")
    was = sum(1 for qid in shared if before[qid] == "pass")
    return {
        "timestamp": previous.get("timestamp") or "",
        "model": previous.get("model") or "",
        "score": {"passed": passed, "total": total},
        "shared": len(shared),
        "delta": now - was,
        "flipped": [
            {"id": result.id, "from": before[result.id], "to": result.outcome}
            for result in results
            if result.id in before and before[result.id] != result.outcome
        ],
    }


def _tags(results: list[QuestionResult]) -> dict:
    """Etiket başına skor: o etiketi taşıyan kaç soru koştu, kaçı geçti; etiketler sıralı yazılır."""
    groups: dict[str, list[QuestionResult]] = {}
    for result in results:
        for tag in result.tags:
            groups.setdefault(tag, []).append(result)
    return {
        tag: {
            "passed": sum(1 for result in group if result.outcome == "pass"),
            "total": len(group),
        }
        for tag, group in sorted(groups.items())
    }


def _decision(total: int, passed: int, lang: str = config.DEFAULT_LANG) -> str:
    """Karar satırı; eşikler 10 soru için verilmiştir, ``--only`` ile kısalan koşu orana göre ölçeklenir."""
    if not total:
        return t("eval.no_questions", lang)
    points = 10 * passed / total
    return t(next(key for floor, key in DECISION_KEYS if points >= floor), lang)


def _write(directory: Path, report: dict, followup_chains: list | None = None) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for name in REPORT_FILES:
        text = (
            json.dumps(report, ensure_ascii=False, indent=2)
            if name.endswith(".json")
            else _markdown(report, followup_chains)
        )
        (directory / name).write_text(text, encoding="utf-8")


def metric_percent(value: float | None, lang: str = config.DEFAULT_LANG) -> str:
    """Oran dilin okunuşuyla yüzde (``0.8333`` -> ``%83,33`` / ``83.33%``); paydasız oran ölçülmedi."""
    return fmt.format_percent(None if value is None else 100 * value, lang, 2)


def metrics_block(metrics: dict, lang: str = config.DEFAULT_LANG) -> list[str]:
    """Konsolun metrik bloğu (R5-14): report.md ile aynı satırlar, girintili ve hizalı."""
    rows = [(key, t(label, lang)) for key, label in METRIC_ROWS]
    width = max(len(label) for _, label in rows)
    return [
        f"  {label:<{width}}  {metric_percent(metrics[key], lang)}" for key, label in rows
    ]


def _markdown(report: dict, followup_chains: list | None = None) -> str:
    lang = report["lang"]
    score, context, metrics = report["score"], report["context"], report["metrics"]
    lines = [
        t("eval.md.title", lang, model=report["model"] or t("eval.md.unnamed", lang)),
        "",
        t("eval.md.stamp", lang, timestamp=report["timestamp"]),
        t("eval.md.model", lang, model=report["model"] or "-"),
        t("eval.md.mode", lang, mode=report["mode"]),
    ]
    if report.get("profile"):
        lines.append(f"- {_profile_note(report, lang)}")
    if report.get("schema"):
        lines.append(t("eval.md.schema", lang, note=_schema_note(report["schema"])))
    if report["config"]:
        settings = ", ".join(f"`{key}={value}`" for key, value in report["config"].items())
        lines.append(t("eval.md.config", lang, settings=settings))
    lines += [
        "",
        t("eval.md.score", lang, passed=score["passed"], total=score["total"]),
        "",
        f"**{report['decision']}**",
        "",
        t(
            "eval.md.context",
            lang,
            peak=context["max_prompt_tokens"],
            median=context["median_prompt_tokens"],
        ),
    ]
    if context.get("peak_estimate") or context.get("overflows"):
        lines.append(
            t(
                "eval.md.budget",
                lang,
                peak=context.get("peak_estimate", 0),
                over=context.get("overflows", 0),
            )
        )
    lines += ["", t("eval.md.metrics", lang), "", t("eval.md.metrics_head", lang), "| --- | ---: |"]
    lines += [
        f"| {t(label, lang)} | {metric_percent(metrics[key], lang)} |"
        for key, label in METRIC_ROWS
    ]
    if report.get("narration"):
        lines += ["", _narration_note(report["narration"], lang)]
    if report.get("followups"):
        lines += ["", *_followups_section(report["followups"], followup_chains, lang)]
    if report["previous"]:
        lines += ["", t("eval.md.previous", lang), ""] + _delta_lines(report, lang)
    if report["tags"]:
        lines += [
            "",
            t("eval.md.tags", lang),
            "",
            t("eval.md.tags_head", lang),
            "| --- | ---: |",
            *(
                f"| {tag} | {counts['passed']}/{counts['total']} |"
                for tag, counts in report["tags"].items()
            ),
        ]
    lines += ["", t("eval.md.questions_head", lang), "| --- | --- | ---: | ---: | ---: |"]
    for question in report["questions"]:
        lines.append(_question_row(question, lang))
    lines += ["", t("eval.md.questions", lang), ""]
    for question in report["questions"]:
        lines += [
            t(
                "eval.md.question_head",
                lang,
                id=question["id"],
                mark=_mark(question["outcome"]),
                outcome=question["outcome"],
            ),
            "",
            question["question"],
            "",
        ]
        if question["reason"]:
            lines += [t("eval.md.reason", lang, reason=question["reason"]), ""]
        lines += [t("eval.md.submitted", lang), "", _sql(question["sql"], lang), ""]
        if question["golden_sql"] and question["golden_sql"] != question["sql"]:
            lines += ["Golden SQL:", "", _sql(question["golden_sql"], lang), ""]
    return "\n".join(lines) + "\n"


def _question_row(question: dict, lang: str) -> str:
    """Sorunun tablo satırı: sonuç kodu çevrilmez, yalnız başındaki im ve sütun başlıkları dilde."""
    return t(
        "eval.md.question_row",
        lang,
        id=question["id"],
        mark=_mark(question["outcome"]),
        outcome=question["outcome"],
        tools=question["tool_calls"],
        tokens=question["total_tokens"],
        seconds=f"{question['seconds']:.1f}",
    )


def _delta_lines(report: dict, lang: str) -> list[str]:
    previous, score = report["previous"], report["score"]
    was = f"{previous['score']['passed']}/{previous['score']['total']}"
    now = f"{score['passed']}/{score['total']}"
    origin = " — ".join(
        str(part)
        for part in (was, previous["model"], previous["timestamp"])
        if part
    )
    delta = previous["delta"]
    change = (
        t("eval.md.delta", lang, delta=f"{delta:+d}", was=was, now=now)
        if delta
        else t("eval.md.unchanged", lang, now=now)
    )
    change += _shared_note(previous, score, lang)
    flipped = [
        f"- {item['id']} {_mark(item['from'])} {item['from']} → {_mark(item['to'])} {item['to']}"
        for item in previous["flipped"]
    ]
    return [
        t("eval.md.prev_run", lang, origin=origin),
        t("eval.md.score_change", lang, change=change),
        *(flipped or [t("eval.md.same", lang)]),
    ]


def _shared_note(previous: dict, score: dict, lang: str) -> str:
    """Fark iki koşunun tamamı üzerinden değilse kaç soru kıyaslandığını söyle; yoksa hiçbir şey."""
    shared = previous["shared"]
    if shared == previous["score"]["total"] and shared == score["total"]:
        return ""
    return t("eval.md.shared", lang, shared=shared)


def _profile_note(report: dict, lang: str) -> str:
    """Model profilinin satırı (R4-14): hangi pencereyle ölçüldüğü ve o bütçenin iki sayısı.

    Sayılar ``context``ten gelir; bütçe hiç aşmadıysa ikisi de 0'dır ve satır yine de okuyana
    koşunun hangi window ile ölçüldüğünü söyler.
    """
    profile, context = report["profile"], report["context"]
    return t(
        "eval.md.profile",
        lang,
        name=profile.get("name") or "-",
        budget=profile.get("context_budget") or 0,
        peak=context.get("peak_estimate") or 0,
        over=context.get("overflows") or 0,
    )


def _narration_note(narration: dict, lang: str) -> str:
    """Anlatının satırı (R5-13): cümleyi kimin kurduğu, yani kaçı bekçiyi ilk geçirdi.

    Sayılar anlatının kendisinden gelir; ``template_pct`` paydasız kaldığında 0.0'dır, çünkü
    anlatılacak cevap olmayan bir koşuda şablon da konuşmamıştır.
    """
    return t(
        "eval.md.narration",
        lang,
        llm=narration["llm"],
        retry=narration["llm_retry"],
        template=narration["template"],
        pct=metric_percent(narration["template_pct"], lang),
    )


FOLLOWUP_RULE = "| --- | ---: | --- | --- | --- |"


def _followups_section(followups: dict, chains: list | None, lang: str) -> list[str]:
    """Ardışık sorular bölümü (R7-14): üç doğruluğun üstüne zincir başına bir tablo.

    Doğruluklar ``followups`` bloğundan (Contracts "followups report"), sorunun kendisi
    ``chains``den gelir - ölçüm satırı soruyu tekrar taşımaz, zincirin satırı taşır.
    """
    lines = [
        f"## {t('eval.followups.head', lang)}",
        "",
        t(
            "eval.followups.turn",
            lang,
            pct=metric_percent(followups["turn_accuracy"], lang),
            turns=followups["turns"],
        ),
        t(
            "eval.followups.chain",
            lang,
            pct=metric_percent(followups["chain_accuracy"], lang),
            chains=followups["chains"],
        ),
        t("eval.followups.context", lang, pct=metric_percent(followups["context_accuracy"], lang)),
    ]
    questions = _followup_questions(chains)
    grouped: dict[str, list[dict]] = {}
    for item in followups["items"]:
        grouped.setdefault(item["id"], []).append(item)
    for chain_id, items in grouped.items():
        lines += ["", f"### {chain_id}", "", t("eval.followups.columns", lang), FOLLOWUP_RULE]
        for item in items:
            lines.append(
                f"| {chain_id} | {item['turn']} | {questions.get((chain_id, item['turn']), '')} "
                f"| {_mark(item['outcome'])} {item['outcome']} "
                f"| {'✓' if item['context_ok'] else '✗'} |"
            )
    return lines


def _followup_questions(chains: list | None) -> dict:
    """``(zincir, tur) -> soru``: zincirin kendi sırası, tabloya soruyu oradan okumak için."""
    return {
        (str(chain.get("id") or ""), n): str(turn.get("question") or "")
        for chain in chains or ()
        for n, turn in enumerate(chain.get("turns") or (), start=1)
    }


def _schema_note(info: dict) -> str:
    """Şema hanesi tek satırda: koşan dosya ve imzasının başı; eksik alan satırı kırmaz."""
    digest = str(info.get("hash") or "")[:8]
    path = f"`{info.get('path') or '-'}`"
    return f"{path} ({digest})" if digest else path


def _mark(outcome: str) -> str:
    return "✓" if outcome == "pass" else "✗"


def _sql(sql: str, lang: str = config.DEFAULT_LANG) -> str:
    return f"```sql\n{sql or t('eval.md.no_sql', lang)}\n```"
