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
    mode: str = "full",
) -> Path:
    """Write ``<out_dir>/<timestamp>/report.json`` + ``report.md``, copy them to ``<out_dir>/latest``.

    ``latest`` holds the previous run, so it is read before it is replaced: that is the only place
    the run-to-run delta can come from. Since the delta is only honest between equal measurements,
    the caller hands in the mode's own directory (``eval_out/<mode>``, PLAN R2-12) and ``out_dir``
    itself keeps the plain ``<ts>`` + ``latest`` shape.
    """
    stamp = datetime.now()
    out = Path(out_dir)
    previous = _load(out / "latest" / REPORT_FILES[0])
    report = _report(results, model, config, stamp, previous, mode)
    run_dir = out / stamp.strftime(STAMP)
    _write(run_dir, report)
    _write(out / "latest", report)
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
) -> dict:
    """Bir koşunun neyi ölçtüğünün imzası: iki koşun farkı ancak imzaları eşitse kıyaslanabilir.

    ``golden`` sorunun kimliği, metni, SQL'i ve sıralı bayrağıyla girer; inceleme notu gibi ölçümü
    değiştirmeyen bir alanın iki koşuyu kıyaslanamaz kılması yanlış olurdu. ``index_hash`` rag'e
    aittir, diğer modlar boş verir.
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
    }


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
) -> dict:
    passed = sum(1 for result in results if result.outcome == "pass")
    peaks = [result.max_prompt_tokens for result in results]
    return {
        "timestamp": stamp.isoformat(sep=" ", timespec="seconds"),
        "model": model,
        "mode": mode,
        "config": dict(settings or {}),
        "score": {"passed": passed, "total": len(results)},
        "tags": _tags(results),
        "decision": _decision(len(results), passed),
        "context": {
            "max_prompt_tokens": max(peaks, default=0),
            "median_prompt_tokens": round(statistics.median(peaks)) if peaks else 0,
        },
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
        f"- Mod: {report['mode']}",
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
    ]
    if report["previous"]:
        lines += ["", "## Önceki koşuya göre", ""] + _delta_lines(report)
    if report["tags"]:
        lines += [
            "",
            "## Etiket skorları",
            "",
            "| Etiket | Skor |",
            "| --- | ---: |",
            *(
                f"| {tag} | {counts['passed']}/{counts['total']} |"
                for tag, counts in report["tags"].items()
            ),
        ]
    lines += [
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


def _delta_lines(report: dict) -> list[str]:
    previous, score = report["previous"], report["score"]
    was = f"{previous['score']['passed']}/{previous['score']['total']}"
    now = f"{score['passed']}/{score['total']}"
    origin = " — ".join(
        str(part)
        for part in (was, previous["model"], previous["timestamp"])
        if part
    )
    delta = previous["delta"]
    change = f"**{delta:+d}** soru ({was} → {now})" if delta else f"değişmedi ({now})"
    change += _shared_note(previous, score)
    flipped = [
        f"- {item['id']} {_mark(item['from'])} {item['from']} → {_mark(item['to'])} {item['to']}"
        for item in previous["flipped"]
    ]
    return [
        f"- Önceki koşu: {origin}",
        f"- Skor değişimi: {change}",
        *(flipped or ["- Soru sonuçları aynı."]),
    ]


def _shared_note(previous: dict, score: dict) -> str:
    """Fark iki koşunun tamamı üzerinden değilse kaç soru kıyaslandığını söyle; yoksa hiçbir şey."""
    shared = previous["shared"]
    if shared == previous["score"]["total"] and shared == score["total"]:
        return ""
    return f" — {shared} ortak soru üzerinden"


def _mark(outcome: str) -> str:
    return "✓" if outcome == "pass" else "✗"


def _sql(sql: str) -> str:
    return f"```sql\n{sql or '_cevap gönderilmedi_'}\n```"
