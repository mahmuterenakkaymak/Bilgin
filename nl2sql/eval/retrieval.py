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
from nl2sql.index.search import METHODS

# ASSUMPTION: geri çağırma raporu eval/mod klasörlerinden ayrı durur; ölçülen şey model değil
# arama indeksi olduğu için kendi dizini var.
RETRIEVAL_OUT = config.EVAL_OUT / "retrieval"

STAMP = "%Y%m%d-%H%M%S"
REPORT_FILES = ("report.json", "report.md")
TABLE_PREFIX = "table:"
NOTHING_MISSING = "-"


def run_retrieval(search, golden: Iterable[dict], k: int = config.SEARCH_K) -> dict:
    """Altın soruların her biri için üç yöntemin recall@k'sı, ortalamalar ve etiket ortalamaları.

    ``search`` aramanın kendisidir (``HybridSearch`` ya da testte elle yazılmış bir eşdeğeri):
    yöntem başına bir kez, tablo koleksiyonu üzerinde ve istenen ``k`` ile çağrılır.
    """
    questions = [_question(search, line, k) for line in golden]
    return {
        "k": k,
        "embedder": search.embedder.id,
        "questions": questions,
        "mean": {method: _mean([item[method] for item in questions]) for method in METHODS},
        "by_tag": _by_tag(questions),
    }


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
    tags = _tag_lines(report)
    if tags:
        order = "/".join(METHODS)
        lines += ["", f"Etiket ortalamaları ({order}):", *tags]
    return lines


def _question(search, line: dict, k: int) -> dict:
    question = str(line.get("question") or "")
    requires = [str(table) for table in line.get("requires_tables") or []]
    entry: dict = {
        "id": str(line.get("id") or ""),
        "tags": [str(tag) for tag in line.get("tags") or []],
        "requires": requires,
        "missing": {},
    }
    for method in METHODS:
        found = _found(search, question, k, method)
        # ASSUMPTION: requires_tables boşsa bulunacak bir şey yoktur; 1.0 böyle bir sorunun
        # ortalamayı sıfıra çekmesini engeller.
        entry[method] = 1.0 if not requires else len(set(requires) & found) / len(requires)
        entry["missing"][method] = [table for table in requires if table not in found]
    return entry


def _found(search, question: str, k: int, method: str) -> set[str]:
    """İlk k tablo vuruşunun tablo adları; ad doküman kimliğinin ``table:<AD>`` önekinden çıkar."""
    hits = search.search(question, collection="tables", k=k, method=method)
    return {hit.doc_id.removeprefix(TABLE_PREFIX) for hit in hits}


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


def _tag_counts(report: dict) -> Counter:
    return Counter(tag for question in report["questions"] for tag in question["tags"])
