# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Metrikler iki yerden doğrulanır: elle kurulmuş outcome listelerinden ve gerçek bir koşudan.

Üst yarıda runner'ın kendisi hiç çalışmaz — QuestionResult'ları elle kurup her oranın elden
hesabını görüyoruz, null olanlar dahil. Alt yarıda üç golden + iki belirsiz soru gerçek SQLite
üzerinde FakeLLM ile koşuyor: belirsiz soruyu soran model precision 1 / recall 1 alır, her soruya
soran over_clarify ise golden'ları cevaplanmamış saydırıp precision'ı kırar (PLAN R5-12).
"""

import pytest

from nl2sql import config
from nl2sql.agent.fake import FakeLLM, for_golden, over_clarify
from nl2sql.engine.executor import LocalExecutor
from nl2sql.eval import runner
from nl2sql.eval.metrics import compute_metrics
from nl2sql.eval.runner import QuestionResult
from nl2sql.schema_map import build

GOLDEN = runner.load_golden()
THREE = ["Q01", "Q02", "Q03"]

# İki belirsiz satır: okunuşları farklı iki sayı veren gerçek sorgular (R5-12 biçimi).
AMBIGUOUS = [
    {
        "id": "A01",
        "question": "Eylül 2026'da satışlarımız ne kadar?",
        "expect": "clarify",
        "term": "satış",
        "readings": [
            {
                "label": "KDV hariç ciro",
                "sql": "SELECT SUM(STHAR_GCMIK * STHAR_NF) AS CIRO FROM TBLSTHAR WHERE STHAR_HTUR = 'S'",
            },
            {
                "label": "KDV dahil brüt satış",
                "sql": "SELECT SUM(GENELTOPLAM) AS BRUT FROM TBLFATUIRS WHERE FTIRSIP = 1",
            },
        ],
    },
    {
        "id": "A02",
        "question": "Kaç müşterimiz var?",
        "expect": "clarify",
        "term": "müşteri",
        "readings": [
            {
                "label": "Yalnız alıcı cariler",
                "sql": "SELECT COUNT(*) AS SAYI FROM TBLCASABIT WHERE CARI_TIP = 'A'",
            },
            {
                "label": "Alıcı ve hem alıcı hem satıcı cariler",
                "sql": "SELECT COUNT(*) AS SAYI FROM TBLCASABIT WHERE CARI_TIP IN ('A', 'H')",
            },
        ],
    },
]


@pytest.fixture(scope="module")
def paths(tmp_path_factory):
    paths = tmp_path_factory.mktemp("metrics")
    build.build_db(config.SEED, paths / "test.db", paths / "test.sql")
    return paths


@pytest.fixture(scope="module")
def executor(paths):
    return LocalExecutor("sqlite", paths / "test.db", audit_path=paths / "audit.jsonl")


def made(
    qid: str, outcome: str, kind: str = "golden", submitted: bool = False
) -> QuestionResult:
    """Elle kurulmuş tek soru: oranlar yalnız outcome, kind ve submitted üçlüsüne bakar."""
    return QuestionResult(id=qid, question="Soru?", outcome=outcome, kind=kind, submitted=submitted)


def golden_run(outcomes: list[str], submitted: list[bool] | None = None) -> list[QuestionResult]:
    submitted = [True] * len(outcomes) if submitted is None else submitted
    return [
        made(f"Q{index + 1:02d}", outcome, "golden", flag)
        for index, (outcome, flag) in enumerate(zip(outcomes, submitted))
    ]


# ------------------------------------------------------------------ elle kurulmuş koşular


def test_an_empty_run_has_no_rates_to_invent():
    assert compute_metrics([]) == {
        "accuracy": 0.0,
        "answered_pct": 0.0,
        "accuracy_when_answered": None,
        "wrong_answer_rate": 0.0,
        "clarify_precision": None,
        "clarify_recall": None,
        "golden": 0,
        "ambiguous": 0,
    }


def test_the_golden_rates_are_the_hand_count():
    # 4 golden: 2 pass, 1 wrong_result, 1 needs_clarification (submit yok -> cevaplanmış değil).
    results = golden_run(
        ["pass", "pass", "wrong_result", "needs_clarification"], [True, True, True, False]
    )
    metrics = compute_metrics(results)
    assert metrics["accuracy"] == 0.5  # 2/4
    assert metrics["answered_pct"] == 0.75  # 3/4
    assert metrics["accuracy_when_answered"] == 0.6667  # 2/3
    assert metrics["wrong_answer_rate"] == 0.25  # (3-2)/4
    assert metrics["golden"] == 4
    assert metrics["ambiguous"] == 0


def test_a_clarification_on_a_golden_question_is_not_an_answer():
    """Brief kuralı: golden soruyu netleştirmeyle kesmek cevap vermemektir, ama bir netleştirmedir."""
    metrics = compute_metrics(golden_run(["needs_clarification"] * 2, [False, False]))
    assert metrics["answered_pct"] == 0.0
    assert metrics["accuracy_when_answered"] is None
    assert metrics["wrong_answer_rate"] == 0.0
    # Tek netleştirme golden'dan geldi: belirsiz soru hiç yok, dolayısıyla recall null.
    assert metrics["clarify_precision"] == 0.0
    assert metrics["clarify_recall"] is None


def test_a_run_that_answered_nothing_has_no_accuracy_when_answered():
    metrics = compute_metrics(golden_run(["no_submission", "llm_error"], [False, False]))
    assert metrics["accuracy"] == 0.0
    assert metrics["answered_pct"] == 0.0
    assert metrics["accuracy_when_answered"] is None
    assert metrics["clarify_precision"] is None


def test_the_clarification_rates_count_both_sets():
    # 2 golden (1 pass, 1 wrong_result) + 3 belirsiz (clarified, guessed, llm_error).
    results = golden_run(["pass", "wrong_result"]) + [
        made("A01", "clarified", "ambiguous", False),
        made("A02", "guessed", "ambiguous", True),
        made("A03", "llm_error", "ambiguous", False),
    ]
    metrics = compute_metrics(results)
    assert metrics["golden"] == 2 and metrics["ambiguous"] == 3
    assert metrics["accuracy"] == 0.5
    assert metrics["answered_pct"] == 1.0
    assert metrics["accuracy_when_answered"] == 0.5
    assert metrics["wrong_answer_rate"] == 0.5  # (2-1)/2
    assert metrics["clarify_precision"] == 1.0  # tek netleştirme belirsiz sorudan
    assert metrics["clarify_recall"] == 0.3333  # 1/3


def test_a_golden_set_without_any_clarification_leaves_both_rates_null():
    metrics = compute_metrics(golden_run(["pass", "wrong_result", "no_submission"]))
    assert metrics["clarify_precision"] is None
    assert metrics["clarify_recall"] is None


def test_every_fraction_is_written_to_four_decimals():
    metrics = compute_metrics(golden_run(["pass"] + ["wrong_result"] * 6))
    assert metrics["accuracy"] == 0.1429  # 1/7
    assert metrics["wrong_answer_rate"] == 0.8571  # 6/7


# ------------------------------------------------------------------ gerçek koşular


def run(executor, llm, **kwargs) -> list[QuestionResult]:
    return runner.run_eval(lambda: llm, executor, GOLDEN, only=THREE, **kwargs)


def test_an_ambiguous_run_scores_the_asking_model_perfectly(executor):
    results = run(
        executor, for_golden(GOLDEN, ambiguous=AMBIGUOUS), clarify=True, ambiguous=AMBIGUOUS
    )
    assert [result.kind for result in results] == ["golden"] * 3 + ["ambiguous"] * 2
    assert [result.outcome for result in results] == ["pass"] * 3 + ["clarified"] * 2
    assert all(result.clarification for result in results[3:])
    assert all(result.clarification is None for result in results[:3])

    metrics = compute_metrics(results)
    assert metrics["accuracy"] == 1.0
    assert metrics["answered_pct"] == 1.0
    assert metrics["accuracy_when_answered"] == 1.0
    assert metrics["wrong_answer_rate"] == 0.0
    assert metrics["clarify_precision"] == 1.0
    assert metrics["clarify_recall"] == 1.0
    assert (metrics["golden"], metrics["ambiguous"]) == (3, 2)


def test_a_model_that_asks_everything_answers_nothing_and_loses_precision(executor):
    results = run(executor, FakeLLM(over_clarify()), clarify=True, ambiguous=AMBIGUOUS)
    assert [result.outcome for result in results] == ["needs_clarification"] * 3 + ["clarified"] * 2

    metrics = compute_metrics(results)
    assert metrics["answered_pct"] == 0.0
    assert metrics["accuracy_when_answered"] is None
    assert metrics["clarify_recall"] == 1.0
    assert metrics["clarify_precision"] == 0.4  # 2 doğru soru / 5 netleştirme


def test_an_ambiguous_question_answered_without_asking_is_a_guess(executor):
    """Sormadan okunuşlardan birini submit eden model guessed alır; recall onu saymaz."""
    results = run(executor, for_golden(GOLDEN), ambiguous=AMBIGUOUS)
    assert [result.outcome for result in results] == ["pass"] * 3 + ["guessed"] * 2
    assert all(result.sql for result in results[3:])

    metrics = compute_metrics(results)
    assert metrics["clarify_precision"] is None
    assert metrics["clarify_recall"] == 0.0
