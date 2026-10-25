"""Golden soruların niyet incelemesi: tek markdown belgesinde soru + golden SQL + doğrular.

Skor SQL'in neyi hesapladığını söyler; neyin *kastedildiğini* bir insan onaylaması gerekir. Bu belge
soru başına soruyu, etiketlerini, kurallarını, golden SQL'ini ve saf Python doğrulunun ilk beş
satırını yan yana koyar, alta işaretlenmemiş bir onay kutusu bırakır. Doğrular veritabanından değil
kümenin referans modülünden gelir, yani belge ile doğruluk kaynağı hiç ayrışamaz. Her küme kendi
belgesini kendi klasörüne yazar, örn. ``datasets/wwi/REVIEW.md``.

    python -m eval.review [--dataset AD] [--out YOL]
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

import sqlglot
from sqlglot import errors

from nl2sql import config, datasets
from nl2sql.cli.main import EXIT_BAD_INPUT
from nl2sql.cli.table import format_table
from nl2sql.engine.result import Result

Dataset = dict[str, list[dict]]

REVIEW_NAME = "REVIEW.md"
PREVIEW_ROWS = 5
CHECKBOX = "- [ ] niyet doğru"
DASH = "—"


def render(golden: Iterable[dict], dataset: Dataset, ds: datasets.Dataset | None = None) -> str:
    """The whole document: the tag counts, then one reviewable section per golden question.

    ``dataset`` doğrulayan satırlar, ``ds`` ise o satırların ve referansların ait olduğu küme;
    ``ds`` söylenmediğinde ``config.DEFAULT_DATASET`` kullanılır.
    """
    lines = list(golden)
    ds = ds or datasets.load_dataset(config.DEFAULT_DATASET)
    references = ds.references()
    seed = ds.seed
    out = [
        "# Golden sorular — niyet incelemesi",
        "",
        f"- Soru: {len(lines)}; her sorunun altında bir `[ ] niyet doğru` kutusu var.",
        f"- Doğrular `{_truth(ds)}` üzerinden `generate({seed})` verisiyle hesaplanır.",
        "",
        "## Etiket sayıları",
        "",
        "| Etiket | Soru |",
        "| --- | ---: |",
        *(f"| {tag} | {count} |" for tag, count in _tag_counts(lines)),
        "",
        "## Sorular",
        "",
    ]
    for line in lines:
        out += _section(line, dataset, references)
    return "\n".join(out) + "\n"


def default_out(ds: datasets.Dataset) -> Path:
    """``--out`` verilmediğinde belgenin yazılacağı yer: kümenin kendi klasöründeki ``REVIEW.md``."""
    return ds.root / REVIEW_NAME


def _tag_counts(golden: Sequence[dict]) -> list[tuple[str, int]]:
    """Her etiketin kaç soruda geçtiği; çok görüldüğü sırayla, eşitlikte ada göre."""
    counts = Counter(tag for line in golden for tag in _names_of(line, "tags"))
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))


def _truth(ds: datasets.Dataset) -> str:
    """Doğruların kaynağının okunur adı: modül noktalı, kümenin kendi dosyası depoya göreli yazılır."""
    target, _, attribute = ds.references_ref.partition(":")
    if not target.endswith(".py"):
        return f"{target}.{attribute}"
    return f"{_under_root(ds.root / target).as_posix()}:{attribute}"


def _under_root(path: Path) -> Path:
    """Yol depo kökünün altındaysa bağıl hali; belge her makinede aynı yolu saysın."""
    try:
        return path.relative_to(config.ROOT)
    except ValueError:
        return path


def _section(line: dict, dataset: Dataset, references: Mapping) -> list[str]:
    qid = str(line.get("id") or "")
    return [
        f"### {qid} — {line.get('question') or ''}",
        "",
        f"- Etiketler: {_joined(_names_of(line, 'tags'))}",
        f"- Kurallar: {_joined(_names_of(line, 'rules'))}",
        f"- Tablolar: {_joined(_names_of(line, 'requires_tables'))}",
        f"- Sıra: {'korunur' if line.get('ordered') else 'önemsiz'}",
        f"- Tuzak: {line.get('trap') or 'yok'}",
        f"- Not: {line.get('notes') or ''}",
        "",
        f"```sql\n{line.get('sql') or ''}\n```",
        "",
        *_preview(line, dataset, references),
        "",
        CHECKBOX,
        "",
    ]


def _preview(line: dict, dataset: Dataset, references: Mapping) -> list[str]:
    """The reference answer's first rows, drawn with the same table the CLI prints."""
    qid = str(line.get("id") or "")
    truth = references.get(qid)
    if truth is None:
        return [f"_{qid} için referans doğrulaması yok._"]
    rows = truth(dataset)
    if not rows:
        return ["_Doğru yanıt boş (0 satır)._"]
    total = len(rows)
    label = (
        f"Doğru yanıtın ilk {PREVIEW_ROWS} satırı (toplam {total} satır):"
        if total > PREVIEW_ROWS
        else f"Doğru yanıt ({total} satır):"
    )
    table = format_table(
        Result(columns=_columns(str(line.get("sql") or ""), len(rows[0])), rows=rows[:PREVIEW_ROWS])
    )
    return [label, "", f"```text\n{table}\n```"]


def _columns(sql: str, width: int) -> list[str]:
    """Select listesinin adları tablo başlığı olur; liste tanınmazsa numaralı başlık, sütun sayısı korunur."""
    try:
        names = [str(node.alias_or_name or node.sql()) for node in sqlglot.parse_one(sql, read="tsql").expressions]
    except errors.SqlglotError:
        names = []
    return names if len(names) == width else [f"sütun {index}" for index in range(1, width + 1)]


def _names_of(line: dict, field: str) -> list[str]:
    """Bir Run 2 liste alanı; golden satırında yoksa boş liste, değerler metne çevrilir."""
    return [str(value) for value in line.get(field) or []]


def _joined(values: list[str]) -> str:
    """Virgülle ayrılmış kod adları; boş liste tek çizgi, yoksa satır başta boş görünür."""
    return ", ".join(f"`{value}`" for value in values) or DASH


def main(argv: list[str] | None = None) -> int:
    """Belgeyi üretip ``--out`` dosyasına yazar; ekrana kaç soru yazıldığı söylenir."""
    parser = argparse.ArgumentParser(
        prog="python -m eval.review",
        description="Golden soruların niyet inceleme belgesini markdown olarak yazar.",
    )
    parser.add_argument(
        "--dataset",
        metavar="AD",
        default=config.DEFAULT_DATASET,
        help=f"veri kümesi adı (varsayılan: {config.DEFAULT_DATASET})",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Yazılacak markdown dosyası (varsayılan: kümenin kendi REVIEW.md'si).",
    )
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        ds = datasets.load_dataset(args.dataset)
    except datasets.DatasetError as exc:
        print(exc)  # cümleyi datasets kurar, bilinen kümeleri de sayar
        return EXIT_BAD_INPUT
    golden = ds.golden()
    text = render(golden, ds.generate(), ds)
    path = Path(args.out) if args.out else default_out(ds)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    print(f"{path}: {len(golden)} soru yazıldı.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
