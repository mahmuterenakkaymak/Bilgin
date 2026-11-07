# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Niyet inceleme belgesi: her golden sorusu doğrularıyla birlikte yazılır, diskteki dosya bayatlamaz."""

from collections import Counter

import pytest

from eval import reference, review
from nl2sql import config
from nl2sql.eval.runner import load_golden
from nl2sql.schema_map import generator

GOLDEN = load_golden()
IDS = [line["id"] for line in GOLDEN]
BY_ID = {line["id"]: line for line in GOLDEN}


@pytest.fixture(scope="module")
def dataset():
    return generator.generate(config.SEED)


@pytest.fixture(scope="module")
def text(dataset):
    return review.render(GOLDEN, dataset)


def section(text, qid):
    """Bir sorunun başlığından bir sonraki başlığa (veya belgenin sonuna) kadar olan parça."""
    rest = text[text.index(f"### {qid} ") + len(f"### {qid} ") :]
    end = rest.find("\n### ")
    return rest[:end] if end >= 0 else rest


def table_rows(body):
    """```text``` bloğundaki tablonun veri satırları; başlık ve ayraç satırı düşülmüş."""
    block = body.split("```text\n")[1].split("\n```")[0]
    return block.splitlines()[2:]


def test_every_golden_question_has_its_own_section_and_a_checkbox(text):
    for qid in IDS:
        assert f"### {qid} — " in text, qid
    assert text.count(review.CHECKBOX) == len(IDS)


def test_the_header_counts_every_tag(text):
    counts = Counter(tag for line in GOLDEN for tag in line["tags"])
    assert counts, "golden satırlarında etiket yok"
    for tag, count in counts.items():
        assert f"| {tag} | {count} |" in text, tag


@pytest.mark.parametrize("qid", IDS)
def test_the_section_lists_what_the_golden_line_says(qid, text):
    line = BY_ID[qid]
    body = section(text, qid)
    assert line["question"] in body
    for field in ("tags", "rules", "requires_tables"):
        for value in line[field]:
            assert f"`{value}`" in body, (qid, field, value)
    assert f"- Tuzak: {line['trap'] or 'yok'}" in body
    assert f"- Sıra: {'korunur' if line['ordered'] else 'önemsiz'}" in body


@pytest.mark.parametrize("qid", IDS)
def test_the_section_shows_the_reference_rows(qid, text, dataset):
    rows = reference.REFERENCES[qid](dataset)
    body = section(text, qid)
    shown = table_rows(body)
    assert len(shown) == min(review.PREVIEW_ROWS, len(rows))
    assert f"{len(rows)} satır" in body
    for line in shown:
        assert len(line.split(" | ")) == len(rows[0])
    for row in rows[: review.PREVIEW_ROWS]:
        for cell in row:
            if isinstance(cell, str) and cell.strip():
                assert cell in body, f"{qid} doğrusunun {cell!r} değeri belgede yok"


def test_the_document_on_disk_is_not_stale(text):
    assert review.DEFAULT_OUT.read_text(encoding="utf-8") == text, (
        "eval/REVIEW.md bayat; `python -m eval.review` ile yeniden yazın."
    )
