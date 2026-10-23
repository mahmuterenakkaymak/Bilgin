"""Koşu baştan sona: golden sorular gerçek yürütücüyle cevaplanıp skorlanır, rapor diske yazılır.

Burada sahte olan tek şey model: FakeLLM senaryo oynatıyor, veritabanı build_db ile kurulmuş gerçek
SQLite ve sorgular LocalExecutor'dan (policy dahil) geçiyor. Böylece runner'ın sekiz outcome'unu
gerçekten ürettiği, golden'ın 10/10 geçtiği, raporun json + md + latest kopyası ve karar satırıyla
doğrulanması bir arada görülüyor.
"""

import json

import pytest

from nl2sql import config
from nl2sql.agent.fake import (
    BROKEN_SQL,
    FORBIDDEN_SQL,
    FakeLLM,
    failing_sql_forever,
    for_golden,
    golden_replay,
    never_submit,
    unreachable,
    wrong_sql,
)
from nl2sql.engine.executor import LocalExecutor
from nl2sql.eval import report, runner
from nl2sql.eval.runner import QuestionResult
from nl2sql.schema_map import build

GOLDEN = runner.load_golden()
IDS = [line["id"] for line in GOLDEN]
BY_QUESTION = {line["question"]: line for line in GOLDEN}

# Filtresiz hali Q01'in cevabından fazla satır döndürüyor: çalışır ama yanlış cevap.
WRONG = "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT ORDER BY CARI_KOD"

# Karışık senaryo: soru -> beklenen outcome + oynatılacak senaryo.
MIXED = {
    "Q01": ("wrong_result", wrong_sql(WRONG)),
    "Q02": ("policy_reject", wrong_sql(FORBIDDEN_SQL)),
    "Q03": ("sql_error", failing_sql_forever()),
    "Q04": ("no_submission", never_submit()),
    "Q05": ("llm_error", unreachable()),
}


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    paths = tmp_path_factory.mktemp("runner")
    db = paths / "test.db"
    build.build_db(config.SEED, db, paths / "test.sql")
    return LocalExecutor("sqlite", db, audit_path=paths / "audit.jsonl")


def run(executor, llm, **kwargs):
    return runner.run_eval(lambda: llm, executor, GOLDEN, **kwargs)


def mixed_llm() -> FakeLLM:
    """Soru metnine göre senaryo oynatan tek client; runner her soruya aynı client'ı veriyor."""
    by_question = {line["question"]: MIXED[line["id"]][1] for line in GOLDEN if line["id"] in MIXED}

    def script(messages):
        question = next(
            (str(m.get("content") or "").strip() for m in messages if m.get("role") == "user"), ""
        )
        return by_question[question]

    return FakeLLM(script)


def made(passed: int, failed: int = 0, peaks: list[int] | None = None) -> list[QuestionResult]:
    """Rapor testlerinin sahte koşusu: outcome'ları ve bağlam tokenlarını elle kuruyoruz."""
    outcomes = ["pass"] * passed + ["wrong_result"] * failed
    peaks = peaks or [1000] * len(outcomes)
    return [
        QuestionResult(
            id=f"Q{index + 1:02d}",
            question="Soru?",
            outcome=outcome,
            sql="SELECT 1",
            golden_sql="SELECT 2" if outcome != "pass" else "SELECT 1",
            reason="" if outcome == "pass" else "Satırlar farklı: 1 satır karşı tarafta yok.",
            tool_calls=3,
            max_prompt_tokens=peak,
            total_tokens=2 * peak,
            seconds=1.25,
        )
        for index, (outcome, peak) in enumerate(zip(outcomes, peaks))
    ]


def written(run_dir):
    return json.loads((run_dir / "report.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ golden koşusu 10/10


def test_the_golden_replay_answers_every_question(executor):
    results = run(executor, for_golden(GOLDEN))
    assert [result.id for result in results] == IDS
    assert [result.outcome for result in results] == ["pass"] * len(IDS)
    assert all(result.sql == BY_QUESTION[result.question]["sql"] for result in results)
    assert all(result.reason == "" for result in results)


def test_every_question_carries_its_cost(executor):
    results = run(executor, for_golden(GOLDEN))
    assert all(result.tool_calls == 3 for result in results)
    assert all(result.max_prompt_tokens > 0 and result.total_tokens > 0 for result in results)
    assert all(result.seconds >= 0 and len(result.steps) == 3 for result in results)


def test_only_keeps_the_asked_questions_in_order(executor):
    results = run(executor, for_golden(GOLDEN), only=["q07", "Q03"])
    assert [result.id for result in results] == ["Q03", "Q07"]


def test_a_golden_line_that_does_not_run_breaks_the_run(executor):
    """Doğrusu çalışmayan bir soru ölçümü geçersiz kılar; yanlış saymak yerine kırar."""
    broken = [{"id": "QXX", "question": GOLDEN[0]["question"], "sql": FORBIDDEN_SQL}]
    with pytest.raises(RuntimeError, match="QXX"):
        runner.run_eval(lambda: FakeLLM(golden_replay(WRONG)), executor, broken)


# ------------------------------------------------------------------ karışık senaryo


def test_the_mixed_script_reaches_each_outcome(executor):
    results = run(executor, mixed_llm(), only=list(MIXED))
    assert {result.id: result.outcome for result in results} == {
        qid: expected for qid, (expected, _) in MIXED.items()
    }
    assert all(result.outcome in runner.OUTCOMES for result in results)
    assert len(runner.OUTCOMES) == 8


def test_every_outcome_explains_itself(executor):
    results = {result.id: result for result in run(executor, mixed_llm(), only=list(MIXED))}
    assert all(result.reason for result in results.values())
    assert results["Q01"].sql == WRONG
    assert results["Q02"].sql == FORBIDDEN_SQL
    assert BROKEN_SQL in results["Q03"].reason or results["Q03"].sql == BROKEN_SQL
    assert results["Q04"].sql == "" and results["Q04"].steps
    assert "127.0.0.1:" in results["Q05"].reason


def test_the_golden_sql_is_kept_for_the_report(executor):
    results = {result.id: result for result in run(executor, mixed_llm(), only=["Q01", "Q04"])}
    assert results["Q01"].golden_sql == BY_QUESTION[results["Q01"].question]["sql"]
    assert results["Q04"].golden_sql


# ------------------------------------------------------------------ rapor


def test_the_report_scores_the_run_and_copies_latest(tmp_path):
    run_dir = report.write_report(made(7, 3), tmp_path, model="qwen-test", config={"backend": "sqlite"})
    data = written(run_dir)
    assert data["score"] == {"passed": 7, "total": 10}
    assert data["model"] == "qwen-test"
    assert data["config"] == {"backend": "sqlite"}
    assert data["previous"] is None
    assert len(data["questions"]) == 10
    assert data["questions"][0]["outcome"] == "pass"

    markdown = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "Skor: 7/10" in markdown and "Devam" in markdown
    assert "Q08 — ✗ wrong_result" in markdown and "Satırlar farklı" in markdown
    for name in report.REPORT_FILES:
        assert (tmp_path / "latest" / name).read_text(encoding="utf-8") == (run_dir / name).read_text(
            encoding="utf-8"
        )


@pytest.mark.parametrize(
    "passed,expected",
    [(10, "Devam"), (7, "Devam"), (6, "Yeniden"), (5, "Yeniden"), (4, "Baştan"), (0, "Baştan")],
)
def test_the_decision_line_follows_the_score(tmp_path, passed, expected):
    data = written(report.write_report(made(passed, 10 - passed), tmp_path))
    assert data["decision"].startswith(expected)


def test_the_context_block_carries_the_peak_and_the_median(tmp_path):
    data = written(report.write_report(made(3, 0, peaks=[1000, 3000, 2000]), tmp_path))
    assert data["context"] == {"max_prompt_tokens": 3000, "median_prompt_tokens": 2000}


def test_an_empty_run_reports_without_dividing_by_zero(tmp_path):
    run_dir = report.write_report([], tmp_path)
    data = written(run_dir)
    assert data["score"] == {"passed": 0, "total": 0}
    assert data["context"] == {"max_prompt_tokens": 0, "median_prompt_tokens": 0}
    assert data["decision"].startswith("Kararsız")
    assert "Skor: 0/0" in (run_dir / "report.md").read_text(encoding="utf-8")


def test_a_real_golden_run_reports_ten_out_of_ten(tmp_path, executor):
    run_dir = report.write_report(
        run(executor, for_golden(GOLDEN)), tmp_path / "eval_out", model="fake", config={"backend": "sqlite"}
    )
    data = written(run_dir)
    assert data["score"] == {"passed": 10, "total": 10}
    assert data["context"]["max_prompt_tokens"] > 0

    markdown = (run_dir / "report.md").read_text(encoding="utf-8")
    assert "Skor: 10/10" in markdown
    assert all(f"### {qid} — ✓ pass" in markdown for qid in IDS)
    assert (tmp_path / "eval_out" / "latest" / "report.md").exists()
