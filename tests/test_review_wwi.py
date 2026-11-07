# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""WWI niyet inceleme belgesi: her soru kendi doğrularıyla yazılır, diskteki dosya bayatlamaz."""

from __future__ import annotations

import pytest

from eval import review
from bilgin.datasets import load_dataset

DATASET = load_dataset("wwi")
GOLDEN = DATASET.golden()
IDS = [line["id"] for line in GOLDEN]
BY_ID = {line["id"]: line for line in GOLDEN}
REFERENCES = DATASET.references()


@pytest.fixture(scope="module")
def rows():
    return DATASET.generate()


@pytest.fixture(scope="module")
def text(rows):
    return review.render(GOLDEN, rows, DATASET)


def section(text, qid):
    """Bir sorunun başlığından bir sonraki başlığa (veya belgenin sonuna) kadar olan parça."""
    rest = text[text.index(f"### {qid} ") + len(f"### {qid} ") :]
    end = rest.find("\n### ")
    return rest[:end] if end >= 0 else rest


def table_rows(body):
    """```text``` bloğundaki tablonun veri satırları; başlık ve ayraç satırı düşülmüş."""
    block = body.split("```text\n")[1].split("\n```")[0]
    return block.splitlines()[2:]


def test_the_header_names_this_datasets_own_truth_source(text):
    assert f"`datasets/wwi/reference.py:REFERENCES` üzerinden `generate({DATASET.seed})`" in text


@pytest.mark.parametrize("qid", IDS)
def test_every_question_is_reviewable_with_its_reference_rows(qid, text, rows):
    body = section(text, qid)
    assert BY_ID[qid]["question"] in body
    assert review.CHECKBOX in body
    truth = REFERENCES[qid](rows)
    shown = table_rows(body)
    assert len(shown) == min(review.PREVIEW_ROWS, len(truth))
    assert f"{len(truth)} satır" in body
    for row in truth[: review.PREVIEW_ROWS]:
        for cell in row:
            if isinstance(cell, str) and cell.strip():
                assert cell in body, f"{qid} doğrusunun {cell!r} değeri belgede yok"


def test_the_document_on_disk_is_not_stale(text):
    assert review.default_out(DATASET).read_text(encoding="utf-8") == text, (
        "datasets/wwi/REVIEW.md bayat; `python -m eval.review --dataset wwi` ile yeniden yazın."
    )
