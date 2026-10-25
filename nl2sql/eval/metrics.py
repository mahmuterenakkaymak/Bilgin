"""Bir koşunun sayıları: doğruluk, cevaplanan oranı ve netleştirme davranışı (PLAN R5-12).

Runner her soruya tek bir outcome ve submit edilip edilmediğini bırakır; burada o alanlar toplanır,
hiçbir karar yeniden verilmez. İki kural brief'ten gelir: golden bir soruya gelen netleştirme
cevap sayılmaz (o yüzden ``answered_pct`` ``submitted``'ı sayar), belirsiz bir soruyu tahmin etmek
yerine sormak ise doğru davranıştır. Oranlar 0-1 aralığında ve 4 ondalıktadır; paydası olmayan bir
oran yok sayılır, 0.0'a çevrilmez - "hiç netleştirme olmadı" ile "hepsi yanlış" aynı şey değil.
"""

from __future__ import annotations

from collections.abc import Iterable

from nl2sql.eval.runner import AMBIGUOUS_OUTCOMES, QuestionResult

DECIMALS = 4


def compute_metrics(results: Iterable[QuestionResult]) -> dict:
    """Run 5 ölçüm bloğu (PLAN Contracts): iki soru setinin ayrı ayrı, tek bakışta okunan hali."""
    golden, ambiguous = _split(results)
    passed = sum(1 for result in golden if result.outcome == "pass")
    answered = sum(1 for result in golden if result.submitted)
    clarified = sum(1 for result in ambiguous if result.outcome == AMBIGUOUS_OUTCOMES[0])
    # Her netleştirme iki yerden gelir: belirsiz soruyu soran (doğru) ve golden soruyu sorup
    # cevaplamayan (brief kuralı: cevaplanmamış). Kesinlik bu ikisinin oranıdır.
    asked = clarified + sum(1 for result in golden if result.outcome == "needs_clarification")
    return {
        "accuracy": _rate(passed, len(golden)),
        "answered_pct": _rate(answered, len(golden)),
        "accuracy_when_answered": _rate_or_none(passed, answered),
        "wrong_answer_rate": _rate(answered - passed, len(golden)),
        "clarify_precision": _rate_or_none(clarified, asked),
        "clarify_recall": _rate_or_none(clarified, len(ambiguous)),
        "golden": len(golden),
        "ambiguous": len(ambiguous),
    }


def _split(results: Iterable[QuestionResult]) -> tuple[list[QuestionResult], list[QuestionResult]]:
    """(golden, ambiguous): satırın ait olduğu set, outcome'un ne anlama geldiğini de belirler."""
    return (
        [result for result in results if result.kind == "golden"],
        [result for result in results if result.kind == "ambiguous"],
    )


def _rate(part: int, whole: int) -> float:
    """Paydası olmayan bir oran 0.0: ölçülecek soru olmayan bir koşuda o sayı sıfırdır."""
    return round(part / whole, DECIMALS) if whole else 0.0


def _rate_or_none(part: int, whole: int) -> float | None:
    """Paydası olmayan oran null (PLAN Contracts): üç oran yokluğunu 0.0 yalanıyla söylemez."""
    return round(part / whole, DECIMALS) if whole else None
