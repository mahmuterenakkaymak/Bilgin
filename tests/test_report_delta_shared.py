# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``eval --only Q03`` sonrası tam koşu: ``latest``te tek soru varken fark o bir sorudur.

İki sahte koşu aynı dizinde: ilki yalnız Q03 (1/1), ikincisi dört soruluk tam koşu. Önceki
raporda olmayan sorular dönüş sayılamaz, yani delta iki koşunun toplam farkı değil ortak soru
kadardır; report.md de hangi sayının ne üzerinden söylendiğini yazar.
"""

import json

from bilgin.eval import report
from bilgin.eval.runner import QuestionResult

ONLY = {"Q03": "pass"}
FULL = {"Q01": "pass", "Q02": "pass", "Q03": "pass", "Q04": "wrong_result"}


def made(outcomes: dict[str, str]) -> list[QuestionResult]:
    """Sahte koşu: raporun farkı okuduğu alanlar, yani id ile outcome."""
    return [
        QuestionResult(
            id=qid,
            question="Soru?",
            outcome=outcome,
            sql="SELECT 1",
            golden_sql="SELECT 1",
            reason="" if outcome == "pass" else "Satırlar farklı: 1 satır karşı tarafta yok.",
            tool_calls=3,
            max_prompt_tokens=1000,
            total_tokens=2000,
            seconds=1.0,
        )
        for qid, outcome in outcomes.items()
    ]


def twice(tmp_path, first, second):
    """Aynı dizinde iki ardışık koşu; ikinci rapor döner."""
    report.write_report(made(first), tmp_path, model="fake-a")
    return report.write_report(made(second), tmp_path, model="fake-b")


def previous_of(tmp_path, first, second) -> dict:
    run_dir = twice(tmp_path, first, second)
    return json.loads((run_dir / "report.json").read_text(encoding="utf-8"))["previous"]


def test_a_full_run_after_a_single_question_run_counts_that_question(tmp_path):
    """Q03 iki koşuda da geçiyor: delta 0, diğer üç soru yeni sayılmaz."""
    previous = previous_of(tmp_path, ONLY, ONLY)
    assert previous["delta"] == 0

    previous = previous_of(tmp_path, ONLY, {"Q01": "pass", "Q02": "pass", "Q03": "pass"})
    assert previous["score"] == {"passed": 1, "total": 1}
    assert previous["delta"] == 0
    assert previous["flipped"] == []


def test_the_shared_question_moving_is_the_whole_delta(tmp_path):
    """Q03 bu koşuda geçti; delta +1 — 1/1'den 4/4'e çıkışın 3'ü değil."""
    previous = previous_of(tmp_path, {"Q03": "wrong_result"}, FULL)
    assert previous["delta"] == 1
    assert previous["flipped"] == [{"id": "Q03", "from": "wrong_result", "to": "pass"}]


def test_the_markdown_says_what_the_delta_was_counted_over(tmp_path):
    text = (twice(tmp_path, {"Q03": "wrong_result"}, FULL) / "report.md").read_text(encoding="utf-8")
    assert "**+1** soru (0/1 → 3/4) — 1 ortak soru üzerinden" in text
    assert "- Q03 ✗ wrong_result → ✓ pass" in text


def test_a_full_run_against_a_full_run_needs_no_note(tmp_path):
    text = (twice(tmp_path, FULL, FULL) / "report.md").read_text(encoding="utf-8")
    assert "ortak soru üzerinden" not in text
    assert "değişmedi (3/4)" in text
