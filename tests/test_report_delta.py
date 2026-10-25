"""Koşudan koşuya fark (Delight 5): ikinci rapor, ``latest``teki önceki koşuya göre yazılır.

İki sahte koşu üst üste aynı dizine yazılıyor. Birincide karşılaştırılacak bir şey yok; ikincide
skor farkı ve sonucu dönen sorular hem report.json'da (``previous``) hem report.md'de
("Önceki koşuya göre") görünüyor. Önceki rapor okunamadığında bölüm hiç yazılmıyor, koşulmuyor.
"""

import json

from nl2sql.eval import report
from nl2sql.eval.runner import QuestionResult

# İlk koşu 2/4; ikincide Q03 geçiyor, Q04 yanlış cevaba düşüyor => 3/4 ve iki dönüş.
FIRST = {"Q01": "pass", "Q02": "pass", "Q03": "wrong_result", "Q04": "no_submission"}
SECOND = {"Q01": "pass", "Q02": "pass", "Q03": "pass", "Q04": "wrong_result"}


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


def written(run_dir):
    return json.loads((run_dir / "report.json").read_text(encoding="utf-8"))


def markdown(run_dir):
    return (run_dir / "report.md").read_text(encoding="utf-8")


def twice(tmp_path, first=FIRST, second=SECOND):
    """Aynı dizinde iki ardışık koşu; ikinci raporun yolu döner."""
    report.write_report(made(first), tmp_path, model="fake-a")
    return report.write_report(made(second), tmp_path, model="fake-b")


def test_the_first_run_has_nothing_to_compare_yet(tmp_path):
    run_dir = report.write_report(made(FIRST), tmp_path)
    assert written(run_dir)["previous"] is None
    assert "Önceki koşuya göre" not in markdown(run_dir)


def test_the_second_run_keeps_the_previous_score(tmp_path):
    previous = written(twice(tmp_path))["previous"]
    assert previous["score"] == {"passed": 2, "total": 4}
    assert previous["model"] == "fake-a"
    assert previous["timestamp"]
    assert previous["delta"] == 1
    assert previous["flipped"] == [
        {"id": "Q03", "from": "wrong_result", "to": "pass"},
        {"id": "Q04", "from": "no_submission", "to": "wrong_result"},
    ]


def test_the_markdown_shows_the_change_and_the_flips(tmp_path):
    run_dir = twice(tmp_path)
    text = markdown(run_dir)
    assert "## Önceki koşuya göre" in text
    assert "- Önceki koşu: 2/4 — fake-a — " in text
    assert "**+1** soru (2/4 → 3/4)" in text
    assert "- Q03 ✗ wrong_result → ✓ pass" in text
    assert "- Q04 ✗ no_submission → ✗ wrong_result" in text
    assert (tmp_path / "latest" / "report.md").read_text(encoding="utf-8") == text


def test_a_lost_question_shows_a_negative_delta(tmp_path):
    data = written(twice(tmp_path, first=SECOND, second=FIRST))
    assert data["previous"]["delta"] == -1
    assert "**-1** soru (3/4 → 2/4)" in markdown(tmp_path / "latest")


def test_a_repeat_run_says_nothing_moved(tmp_path):
    run_dir = twice(tmp_path, first=SECOND, second=SECOND)
    previous = written(run_dir)["previous"]
    assert (previous["model"], previous["score"], previous["delta"], previous["flipped"]) == (
        "fake-a",
        {"passed": 3, "total": 4},
        0,
        [],
    )
    text = markdown(run_dir)
    assert "değişmedi (3/4)" in text
    assert "- Soru sonuçları aynı." in text


def test_a_shorter_run_compares_only_the_shared_questions(tmp_path):
    """``--only`` ile kısalan koşu: önceki raporda olmayan soru dönmüş sayılmaz."""
    run_dir = twice(tmp_path, first=FIRST, second={"Q02": "wrong_result", "Q03": "wrong_result"})
    previous = written(run_dir)["previous"]
    assert previous["flipped"] == [{"id": "Q02", "from": "pass", "to": "wrong_result"}]
    # Ortak Q02/Q03: Q02 pass -> wrong_result, Q03 iki tarafta da wrong_result.
    assert previous["delta"] == -1


def test_an_unreadable_previous_report_is_skipped_not_guessed(tmp_path):
    """İlk koşu yarıda kesilmiş olabilir: bozuk ``latest`` fark uydurmayı değil, sessiz geçmeyi gerektirir."""
    report.write_report(made(FIRST), tmp_path)
    latest = tmp_path / "latest" / "report.json"
    latest.write_text('{"score": {"passed": 9}}', encoding="utf-8")
    run_dir = report.write_report(made(SECOND), tmp_path)
    assert written(run_dir)["previous"] is None
    assert "Önceki koşuya göre" not in markdown(run_dir)

    latest.write_text("{yarı yazılmış", encoding="utf-8")
    assert written(report.write_report(made(SECOND), tmp_path))["previous"] is None
