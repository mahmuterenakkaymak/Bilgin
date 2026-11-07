# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Geri çağırma ölçümü: altın sorunun tablosu aramanın ilk k vuruşunun içinde mi?

Fazın kuralı "ölçülen kazanç yoksa RAG yok"; bu modül o ölçümün arama tarafıdır. Üç yöntem yan
yana ve aynı sorular üzerinde ölçülür, çünkü iddia hibridin diğerlerini yenmesi. Ölçüt F1 değil
geri çağırmadır: modelin aracı ilgili tabloyu ilk k'da *görmeli*, sırası değil. Ölçütün kendisi
altın satırının ``requires_tables`` alanı — golden SQL'in gerçekten dokunduğu tablolar, yani
aramanın bulmayı borçlu olduğu liste.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path

from nl2sql import config
from nl2sql.index.search import METHODS, expanded_hits

# ASSUMPTION: geri çağırma raporu eval/mod klasörlerinden ayrı durur; ölçülen şey model değil
# arama indeksi olduğu için kendi dizini var.
RETRIEVAL_OUT = config.EVAL_OUT / "retrieval"

STAMP = "%Y%m%d-%H%M%S"
REPORT_FILES = ("report.json", "report.md")
TABLE_PREFIX = "table:"
NOTHING_MISSING = "-"

# R3-9 varyantları: iki düğme ayrı ayrı ölçülür; adlar raporda, etiketler ekran ve markdown'da.
VARIANTS = {"base": (False, False), "neighbours": (True, False), "synonyms": (False, True)}
# R5-20: özet düğmesi taban ayarlarıyla koşar, o yüzden VARIANTSın (expand, rewrite) hali yok.
SUMMARIES = "summaries"
VARIANT_LABELS = {"base": "taban", "neighbours": "+komşu", "synonyms": "+eşanlam", SUMMARIES: "+özet"}


def run_retrieval(
    search,
    golden: Iterable[dict],
    k: int = config.SEARCH_K,
    expand: bool = False,
    rewrite: bool = False,
    graph=None,
    schema: dict | None = None,
    summaries: bool = False,
) -> dict:
    """Altın soruların her biri için üç yöntemin recall@k'sı, ortalamalar ve etiket ortalamaları.

    ``search`` aramanın kendisidir (``HybridSearch`` ya da testte elle yazılmış bir eşdeğeri):
    yöntem başına bir kez, tablo koleksiyonu üzerinde ve istenen ``k`` ile çağrılır. ``expand`` ve
    ``rewrite`` R3-9'un iki düğmesidir; ikisi kapalıyken ölçülen tabandır, hangi yapılandırmanın
    ölçüldüğünü ``variants`` söyler. ``summaries`` R5-20'nin üçüncü düğmesidir: vuruşlar
    ``search_tables``dan gelir, yani tablo sırası tablo özetlerinin sırasıyla kaynaşır.
    """
    # ASSUMPTION: komşu genişletmesi graph ve şema olmadan ölçülemez; sessizce taban ölçümüne
    # düşmesin diye ikisi de açıkça isteniyor.
    if expand and (graph is None or schema is None):
        raise ValueError("Komşu genişletmesi ölçümü join graphı ve şema ister.")
    hits = _hits(search, expand, rewrite, graph, schema, summaries)
    questions = [_question(line, k, hits) for line in golden]
    mean = _means(questions)
    by_tag = _by_tag(questions)
    return {
        "k": k,
        "embedder": search.embedder.id,
        "summaries": summaries,
        "questions": questions,
        "mean": mean,
        "by_tag": by_tag,
        "variants": {_variant(expand, rewrite, summaries): {"mean": mean, "by_tag": by_tag}},
    }


def run_variants(
    search,
    golden: Iterable[dict],
    k: int = config.SEARCH_K,
    graph=None,
    schema: dict | None = None,
    summaries: bool = False,
) -> dict:
    """R3-9: taban, +komşu ve +eşanlam aynı sorular üzerinde koşar; rapor üçünün birden raporu.

    Gövde taban ölçümüdür, yani ekran ve rapor bugünkü haliyle okunur; ``variants`` her varyantın
    metod metod ortalamasını, etiket ortalamalarını ve soru başına sayısını taşır. ``summaries``
    açıkken dördüncü satır +özet'tir (R5-20): tabanın yanına özet koleksiyonu da girer.
    """
    lines = list(golden)
    reports = {
        name: run_retrieval(search, lines, k, expand, rewrite, graph, schema)
        for name, (expand, rewrite) in VARIANTS.items()
    }
    if summaries:
        reports[SUMMARIES] = run_retrieval(
            search, lines, k, graph=graph, schema=schema, summaries=True
        )
    report = reports["base"]
    report["summaries"] = summaries
    report["variants"] = {
        name: {
            "mean": variant["mean"],
            "by_tag": variant["by_tag"],
            # ASSUMPTION: soru satırının tek sayısı hibrit geri çağırmasıdır - modelin gördüğü
            # yöntem o; metodların tamamı ``mean`` içinde duruyor.
            "questions": {item["id"]: item["hybrid"] for item in variant["questions"]},
        }
        for name, variant in reports.items()
    }
    return report


def write_retrieval(report: dict, out_dir: str | Path = RETRIEVAL_OUT) -> Path:
    """``<out>/<timestamp>/report.json`` + ``report.md`` yazar, aynısını ``<out>/latest``'e koyar.

    İki kopya aynı sözlükten üretildiği için okuyucu yarım bir raporla karşılaşmaz; ``latest``
    bir sonraki koşunun kıyaslayacağı şeydir.
    """
    stamp = datetime.now()
    out = Path(out_dir)
    data = {"timestamp": stamp.isoformat(sep=" ", timespec="seconds"), **report}
    run_dir = out / stamp.strftime(STAMP)
    _write(run_dir, data)
    _write(out / "latest", data)
    return run_dir


def console_lines(report: dict) -> list[str]:
    """Ekranın kendisi (R2-14): soru başına bir satır, metod ortalamaları, etiket ortalamaları."""
    header = f"{'Soru':<6}" + "".join(f"{method:>8}" for method in METHODS) + "  eksik"
    lines = [header]
    for question in report["questions"]:
        lines.append(
            f"{question['id']:<6}"
            + "".join(f"{value:>8}" for value in _recalls(question))
            + f"  {_missing_text(question)}"
        )
    lines += ["", _means_line(report)]
    variants = _variant_lines(report)
    if variants:
        lines += ["", *variants]
    tags = _tag_lines(report)
    if tags:
        order = "/".join(METHODS)
        lines += ["", f"Etiket ortalamaları ({order}):", *tags]
    return lines


def _hits(search, expand: bool, rewrite: bool, graph, schema, summaries: bool):
    """Varyantın vuruş üreteni: ``(soru, yöntem, k)`` ile çağrılınca tablo vuruşlarını döndürür.

    Eş anlamlı genişletmesi aramanın kendi düğmesidir; komşu genişletmesi aramanın değil şemanın
    söylediği bir bağlantı olduğu için graph ve schema ile ``expanded_hits``e devredilir. Özet
    bacağı aramanın kendi içinde kaynaştığı için ``search_tables``a devredilir; o düğme yöntemi
    değil aramanın varsayılanını (hybrid) ölçtüğünden üç metod sütunu aynı sayıyı taşır.
    """

    def hits(question: str, method: str, k: int):
        if expand:
            return expanded_hits(_Leg(search, method, rewrite), question, graph, schema, k, expand=True)
        if summaries:
            return search.search_tables(question, k=k, summaries=True)
        return _ask(search, question, k, method, rewrite)

    return hits


class _Leg:
    """``expanded_hits``in beklediği arama kalıbı: koleksiyonu ve yöntemi bağlanmış tek bacak."""

    def __init__(self, search, method: str, rewrite: bool) -> None:
        self._search = search
        self._method = method
        self._rewrite = rewrite

    def search(self, query, collection: str = "tables", k: int = config.SEARCH_K):
        return _ask(self._search, query, k, self._method, self._rewrite)


def _ask(search, question: str, k: int, method: str, rewrite: bool):
    """Aramanın kendi çağrısı; ``rewrite`` her iki durumda da açıkça geçirilir.

    Aramanın kendi varsayılanı eş anlamlı genişletmesini açık tutuyor (``config.SYNONYM_REWRITE``)
    ve kurallar aramanın yanında duruyor; geçirilmezse taban varyantı da genişletilmiş sorguyla
    ölçülür, yani tabanla +eşanlam aynı sayıyı verirdi.
    """
    return search.search(question, collection="tables", k=k, method=method, rewrite=rewrite)


def _variant(expand: bool, rewrite: bool, summaries: bool = False) -> str:
    """Ölçülen yapılandırmanın adı; düğmeler ayrı ayrı ölçülür, ikisi birden bir varyant değil."""
    if expand:
        return "neighbours"
    if rewrite:
        return "synonyms"
    return SUMMARIES if summaries else "base"


def _question(line: dict, k: int, hits) -> dict:
    question = str(line.get("question") or "")
    requires = [str(table) for table in line.get("requires_tables") or []]
    entry: dict = {
        "id": str(line.get("id") or ""),
        "tags": [str(tag) for tag in line.get("tags") or []],
        "requires": requires,
        "missing": {},
    }
    for method in METHODS:
        found = _found(hits, question, k, method)
        # ASSUMPTION: requires_tables boşsa bulunacak bir şey yoktur; 1.0 böyle bir sorunun
        # ortalamayı sıfıra çekmesini engeller.
        entry[method] = 1.0 if not requires else len(set(requires) & found) / len(requires)
        entry["missing"][method] = [table for table in requires if table not in found]
    return entry


def _found(hits, question: str, k: int, method: str) -> set[str]:
    """Vuruşların tablo adları; ad doküman kimliğinin ``table:<AD>`` önekinden çıkar.

    Genişletmede liste ``k``yı aşar ve aşması da ölçümdür: model aracı kullandığında komşuları da
    görüyor, geri çağırma onun gördüğü kümenin kendisi.
    """
    return {hit.doc_id.removeprefix(TABLE_PREFIX) for hit in hits(question, method, k)}


def _by_tag(questions: list[dict]) -> dict:
    """Etiket başına yöntem ortalaması; etiketler sıralı yazılır ki iki koşu aynı tabloyu versin."""
    groups: dict[str, list[dict]] = {}
    for question in questions:
        for tag in question["tags"]:
            groups.setdefault(tag, []).append(question)
    return {
        tag: {method: _mean([item[method] for item in group]) for method in METHODS}
        for tag, group in sorted(groups.items())
    }


def _means(questions: list[dict]) -> dict:
    return {method: _mean([item[method] for item in questions]) for method in METHODS}


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _recalls(question: dict) -> list[str]:
    return [f"{question[method]:.2f}" for method in METHODS]


def _missing_text(question: dict) -> str:
    """Eksik sütunu: hangi tablonun hangi yöntemde bulunamadığı; üçü de bulduysa tek çizgi."""
    parts = []
    for method in METHODS:
        tables = question["missing"].get(method) or []
        if tables:
            parts.append(f"{method}: {', '.join(tables)}")
    return "; ".join(parts) or NOTHING_MISSING


def _means_line(report: dict) -> str:
    values = " · ".join(f"{method} {report['mean'][method]:.2f}" for method in METHODS)
    return (
        f"Ortalama: {values}  "
        f"(k={report['k']}, {len(report['questions'])} soru, {report['embedder']})"
    )


def _variant_lines(report: dict) -> list[str]:
    """R3-9 ekranı: soru başına üç varyantın sayısı, alta metod metod varyant ortalamaları.

    Tek varyantlı ölçüm (``run_retrieval``ın kendi koşumu) karşılaştırılacak bir şey olmadığı için
    gösterilmez; ekranın gövdesi zaten o ölçümün metod metod halidir.
    """
    variants = report.get("variants") or {}
    if len(variants) < 2:
        return []
    return [
        f"{'Soru':<6}" + "".join(f"{VARIANT_LABELS[name]:>10}" for name in variants),
        *(
            f"{question['id']:<6}"
            + "".join(
                f"{entry['questions'].get(question['id'], 0.0):>10.2f}"
                for entry in variants.values()
            )
            for question in report["questions"]
        ),
        "",
        f"Varyant ortalamaları ({'/'.join(METHODS)}):",
        *(
            f"  {VARIANT_LABELS[name]:<10}"
            + "".join(f"{entry['mean'][method]:>8.2f}" for method in METHODS)
            for name, entry in variants.items()
        ),
    ]


def _tag_lines(report: dict) -> list[str]:
    counts = _tag_counts(report)
    width = max((len(tag) for tag in report["by_tag"]), default=0)
    return [
        f"  {tag:<{width}}{counts[tag]:>3} soru "
        + "".join(f"{report['by_tag'][tag][method]:>8.2f}" for method in METHODS)
        for tag in report["by_tag"]
    ]


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
    lines = [
        f"# Geri çağırma raporu — {report['embedder'] or 'embedder adı yok'}",
        "",
        f"- Koşum: {report['timestamp']}",
        f"- k: {report['k']} · Soru: {len(report['questions'])}",
        "",
        "## Metod ortalamaları",
        "",
        "| Metod | Geri çağırma |",
        "| --- | ---: |",
        *(f"| {method} | {report['mean'][method]:.2f} |" for method in METHODS),
        "",
        "## Sorular",
        "",
        "| Soru | " + " | ".join(METHODS) + " | eksik |",
        "| --- | " + " | ".join("---:" for _ in METHODS) + " | --- |",
    ]
    for question in report["questions"]:
        lines.append(
            f"| {question['id']} | "
            + " | ".join(_recalls(question))
            + f" | {_missing_text(question)} |"
        )
    lines += _variant_section(report)
    lines += ["", "## Etiket ortalamaları", ""]
    if not report["by_tag"]:
        return "\n".join([*lines, "Soru etiketi yok."]) + "\n"
    counts = _tag_counts(report)
    lines += [
        "| Etiket | Soru | " + " | ".join(METHODS) + " |",
        "| --- | ---: | " + " | ".join("---:" for _ in METHODS) + " |",
    ]
    for tag, means in report["by_tag"].items():
        lines.append(
            f"| {tag} | {counts[tag]} | "
            + " | ".join(f"{means[method]:.2f}" for method in METHODS)
            + " |"
        )
    return "\n".join(lines) + "\n"


def _variant_section(report: dict) -> list[str]:
    """Markdown'ın R3-9 bölümü: soru başına üç varyant, alta varyant başına üç metod."""
    variants = report.get("variants") or {}
    if len(variants) < 2:
        return []
    names = list(variants)
    lines = [
        "",
        "## Varyantlar",
        "",
        "| Soru | " + " | ".join(VARIANT_LABELS[name] for name in names) + " |",
        "| --- | " + " | ".join("---:" for _ in names) + " |",
    ]
    for question in report["questions"]:
        lines.append(
            f"| {question['id']} | "
            + " | ".join(
                f"{variants[name]['questions'].get(question['id'], 0.0):.2f}" for name in names
            )
            + " |"
        )
    lines += [
        "",
        "| Varyant | " + " | ".join(METHODS) + " |",
        "| --- | " + " | ".join("---:" for _ in METHODS) + " |",
    ]
    for name, entry in variants.items():
        lines.append(
            f"| {VARIANT_LABELS[name]} | "
            + " | ".join(f"{entry['mean'][method]:.2f}" for method in METHODS)
            + " |"
        )
    return lines


def _tag_counts(report: dict) -> Counter:
    return Counter(tag for question in report["questions"] for tag in question["tags"])
