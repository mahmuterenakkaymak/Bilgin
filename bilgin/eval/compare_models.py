# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Model x mod hücreleri yan yana: hangi pencere hangi moda sığıyor (PLAN R4-13).

Karşılaştırma kendi başına hiçbir şey ölçmez; her hücre ``run_eval``in bıraktığı
``QuestionResult`` listeleridir ve raporun tek sayısı bile o listelerden yeniden kurulur. Konsol
satırı ile markdown aynı hücre sözlüğünden çıktığı için ikisi birbirini tutmazlık üretemez;
json ise ikisinin okuduğu kaynaktır. Bir modelin bloğu uç nokta kapalı diye hiç koşmadıysa
hücre uydurulmaz - ``skipped``'ta sebebiyle durur.
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime
from pathlib import Path

from bilgin import config
from bilgin.eval.compare_modes import _num, _stats
from bilgin.eval.report import STAMP
from bilgin.eval.runner import QuestionResult, _tokens
from bilgin.i18n import t

PASS = "pass"


def build_model_compare(
    cells: dict,
    profiles: dict | None = None,
    dataset=None,
    skipped: dict | None = None,
    lang: str = config.DEFAULT_LANG,
) -> dict:
    """``{model: {mod: [tekrar başına QuestionResult listesi]}}`` -> Contracts'ın compare raporu.

    ``profiles`` model adını o koşunun ölçüldüğü ``ModelProfile``a bağlar; olmadığı modelin
    hanesi sıfırla yazar, yoksa okuyan boş bir bütçeyi gerçek bir sınır sanır. ``dataset`` ya
    bir ``Dataset``tır ya da adının kendisi. ``skipped`` hiç koşmayan modellerin sebebidir.

    ``lang`` (R8-12) markdown ve konsolun dilidir; rapor hangi dille yazıldığını ``lang`` alanıyla
    kendisi söyler. Türkçe varsayılanın dışına ancak ``en`` istendiğinde çıkılır.
    """
    known = profiles or {}
    modes = _modes(cells)
    repeats = [len(runs) for runs_by_mode in cells.values() for runs in runs_by_mode.values()]
    return {
        "timestamp": datetime.now().isoformat(sep=" ", timespec="seconds"),
        "dataset": _dataset_name(dataset),
        **({"lang": lang} if lang != config.DEFAULT_LANG else {}),
        "questions": len(_ids(cells)),
        "repeat": max(repeats, default=1),
        "models": list(cells),
        "modes": modes,
        "cells": {
            model: {
                mode: _cell(cells[model][mode], known.get(model))
                for mode in modes
                if mode in cells[model]
            }
            for model in cells
        },
        "skipped": dict(skipped or {}),
    }


def render_model_compare(report: dict) -> str:
    """Raporun okunur hali: model x mod tablosu, etiket tablosu, atlananların listesi."""
    lang = report.get("lang", config.DEFAULT_LANG)
    lines = [
        t(
            "compare.models.title",
            lang,
            dataset=report["dataset"] or t("compare.models.unnamed", lang),
        ),
        "",
        t("compare.models.stamp", lang, timestamp=report["timestamp"]),
        t("compare.models.dataset", lang, dataset=report["dataset"] or "-"),
        t("compare.models.questions", lang, questions=report["questions"]),
        t("compare.models.repeat", lang, repeat=report["repeat"]),
        t("compare.models.modes", lang, modes=", ".join(report["modes"]) or "-"),
        "",
        t("compare.models.cells_head", lang),
        "",
        f"| {t('compare.models.col_model', lang)} | {t('compare.models.col_mode', lang)} "
        f"| {t('compare.models.col_score', lang)} | {t('compare.models.col_answered', lang)} "
        f"| {t('compare.models.col_peak', lang)} | {t('compare.models.col_overflow', lang)} "
        f"| {t('compare.models.col_seconds', lang)} | {t('compare.models.col_server_peak', lang)} "
        f"| {t('compare.models.col_trimmed', lang)} |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model, mode, cell in _cells(report):
        # Satırın gövdesi R4-14'ün hali; json'daki iki bağlam sayısı son iki sütunda durur.
        lines.append(
            f"| {_cell_line(model, mode, cell, report['questions'], lang)}"
            f" | {_tokens(cell['peak_reported'])} | {cell['trimmed']} |"
        )
    lines += _tag_lines(report, lang)
    lines += _skipped_lines(report, lang)
    return "\n".join(lines) + "\n"


def console_lines(report: dict) -> list[str]:
    """Ekranın kendisi (R4-14): hücre başına bir satır, sonra hiç koşmayanların sebebi."""
    lang = report.get("lang", config.DEFAULT_LANG)
    lines = [
        _cell_line(model, mode, cell, report["questions"], lang)
        for model, mode, cell in _cells(report)
    ]
    lines += [f"⚠ {model}: {reason}" for model, reason in (report.get("skipped") or {}).items()]
    return lines


def write_model_compare(report: dict, out_dir: str | Path = config.EVAL_OUT) -> Path:
    """``<out>/compare_<dataset>_<ts>.json`` + ``.md``; dönen yol markdown dosyası (CLI onu yazar).

    R4-13 dosyayı ``eval_out``un doğrudan altına koyar: iki dosya aynı sözlükten yazıldığı için
    okuyan hiçbiri yarım kalmış bir raporla karşılaşmaz.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"compare_{report['dataset'] or 'dataset'}_{datetime.now().strftime(STAMP)}"
    texts = {
        ".json": json.dumps(report, ensure_ascii=False, indent=2),
        ".md": render_model_compare(report),
    }
    for suffix, text in texts.items():
        (out / f"{stem}{suffix}").write_text(text, encoding="utf-8")
    return out / f"{stem}.md"


# ------------------------------------------------------------------ parçalar


def _cell(runs: list[list[QuestionResult]], profile) -> dict:
    """Bir model x mod hücresi: tekrarların üzerinden geçen yedi ölçüm ve soru soru sonuçlar."""
    results = [result for run in runs for result in run]
    return {
        "profile": _profile(profile),
        "scores": _stats([_passed(run) for run in runs]),
        "answered_pct": round(100 * sum(1 for r in results if r.submitted) / len(results))
        if results
        else 0,
        "peak_estimate": max((r.peak_estimate for r in results), default=0),
        "peak_reported": max((r.max_prompt_tokens for r in results), default=0),
        "overflows": sum(r.overflows for r in results),
        "trimmed": sum(r.trimmed for r in results),
        "seconds_per_question": _mean([r.seconds for r in results]),
        "tags": _tags(runs),
        "outcomes": _outcomes(runs),
    }


def _profile(profile) -> dict:
    """Hücrenin ölçüldüğü pencere; profili olmayan model üç sayıyı da boş bırakır, null değil."""
    return {
        "model": str(getattr(profile, "model", "") or ""),
        "context_budget": int(getattr(profile, "context_budget", 0) or 0),
        "prompt_limit": int(getattr(profile, "prompt_limit", 0) or 0),
    }


def _tags(runs: list[list[QuestionResult]]) -> dict:
    """Etiket başına geçen soru sayısının yayılımı; her tekrar aynı altın kümeyi koşar."""
    tags = list(dict.fromkeys(tag for run in runs for result in run for tag in result.tags))
    return {
        tag: _stats([_passed([result for result in run if tag in result.tags]) for run in runs])
        for tag in tags
    }


def _outcomes(runs: list[list[QuestionResult]]) -> dict:
    """Soru soru, tekrar sırasıyla sonuçlar; o tekrarda koşmamış sorunun sonucu boş metindir."""
    ids = sorted({result.id for run in runs for result in run})
    return {
        qid: [
            next((result.outcome for result in run if result.id == qid), "") for run in runs
        ]
        for qid in ids
    }


def _passed(run) -> int:
    return sum(1 for result in run if result.outcome == PASS)


def _cell_line(
    model: str, mode: str, cell: dict, total: int, lang: str = config.DEFAULT_LANG
) -> str:
    """R4-14'ün tek satırı: skor, cevap yüzdesi, tepe tahmin/bütçe, taşma, soru başına süre."""
    scores = cell["scores"]
    return t(
        "compare.models.cell",
        lang,
        model=model,
        mode=mode,
        score=_num(scores["mean"]),
        total=total,
        ort=t("compare.models.ort", lang),
        answered=cell["answered_pct"],
        peak_est=_tokens(cell["peak_estimate"]),
        peak_limit=_tokens(cell["profile"]["prompt_limit"]),
        overflows=cell["overflows"],
        seconds=f"{cell['seconds_per_question']:.1f}",
    )


def _cells(report: dict):
    """Hücrelerin dolaşım sırası: raporun yazdığı model ve mod sırası, iki çıktının da kaynağı."""
    for model in report["models"]:
        for mode in report["modes"]:
            cell = (report["cells"].get(model) or {}).get(mode)
            if cell:
                yield model, mode, cell


def _tag_lines(report: dict, lang: str = config.DEFAULT_LANG) -> list[str]:
    columns = [(model, mode) for model, mode, _ in _cells(report)]
    tags = sorted({tag for _, _, cell in _cells(report) for tag in cell["tags"]})
    if not tags:
        return []
    lines = [
        "",
        t("compare.models.tags_head", lang),
        "",
        f"| {t('compare.models.col_tag', lang)} | "
        + " | ".join(f"{model}/{mode}" for model, mode in columns)
        + " |",
        "| --- | " + " | ".join("---:" for _ in columns) + " |",
    ]
    for tag in tags:
        cells = [
            _score(cell["tags"][tag]) if tag in cell["tags"] else "-" for _, _, cell in _cells(report)
        ]
        lines.append(f"| {tag} | " + " | ".join(cells) + " |")
    return lines


def _skipped_lines(report: dict, lang: str = config.DEFAULT_LANG) -> list[str]:
    skipped = report.get("skipped") or {}
    if not skipped:
        return []
    return [
        "",
        t("compare.models.skipped_head", lang),
        "",
        *(f"- `{model}`: {reason}" for model, reason in skipped.items()),
    ]


def _score(stats: dict) -> str:
    """Yayılımın üç sayısı: ``6.7/6/7`` (ort/min/max)."""
    return f"{_num(stats['mean'])}/{stats['min']}/{stats['max']}"


def _modes(cells: dict) -> list[str]:
    """Modlar PLAN'ın sırasıyla; config.MODES dışındakiler alfabetik olarak sona gelir."""
    known = [mode for mode in config.MODES if any(mode in modes for modes in cells.values())]
    extra = sorted({mode for modes in cells.values() for mode in modes} - set(known))
    return known + extra


def _ids(cells: dict) -> set[str]:
    return {
        result.id
        for modes in cells.values()
        for runs in modes.values()
        for run in runs
        for result in run
    }


def _dataset_name(dataset) -> str:
    """Veri kümesinin adı: ``Dataset`` nesnesi de adının kendisi de aynı kapıdan geçer."""
    return str(getattr(dataset, "name", None) or dataset or "")


def _mean(values: list[float]) -> float:
    return round(statistics.mean(values), 1) if values else 0.0
