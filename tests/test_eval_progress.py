"""Delight 4: ekran koşu bitince değil, her soru bitince tek satır görüyor.

Üç golden soru gerçek SQLite üzerinde FakeLLM ile koşuyor: callback'in sırası satırın koşu
bitmeden geldiğini, satırın birebir biçimi runner.progress_line'dan, ekranda durduğu hali ise
cli.evaluate'ın yakalanan çıktısı doğruluyor.
"""

import re

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.cli import main as cli
from nl2sql.engine.executor import LocalExecutor
from nl2sql.eval import runner
from nl2sql.schema_map import build

GOLDEN = runner.load_golden()
THREE = ["Q01", "Q02", "Q03"]

# Q03 ✓ pass  4 araç  12.3 sn  8.1K token
LINE = re.compile(r"^Q\d\d [✓✗] \S+ +\d+ araç +\d+\.\d sn +\d+(\.\d)?K? token$")


@pytest.fixture(scope="module")
def paths(tmp_path_factory):
    """Tek kurulum: üç soru da aynı gerçek SQLite dosyasından cevaplanıyor."""
    paths = tmp_path_factory.mktemp("progress")
    build.build_db(config.SEED, paths / "test.db", paths / "test.sql")
    return paths


@pytest.fixture(scope="module")
def executor(paths):
    return LocalExecutor(db_path=paths / "test.db", audit_path=paths / "audit.jsonl")


def three(executor, on_progress=None):
    return runner.run_eval(
        lambda: fake.for_golden(GOLDEN), executor, GOLDEN, only=THREE, on_progress=on_progress
    )


def made(outcome: str = "pass", tool_calls: int = 3, total_tokens: int = 900, seconds: float = 1.2):
    """Satır biçiminin sahte sorusu: maliyet alanları sabit, değişen tek şey outcome ve token."""
    return runner.QuestionResult(
        id="Q03",
        question="Soru?",
        outcome=outcome,
        tool_calls=tool_calls,
        total_tokens=total_tokens,
        seconds=seconds,
    )


# ------------------------------------------------------------------ callback


def test_the_callback_sees_each_question_the_moment_it_is_judged(executor):
    seen: list[runner.QuestionResult] = []
    results = three(executor, seen.append)
    assert [result.id for result in seen] == THREE
    assert all(asked is given for asked, given in zip(seen, results))


def test_every_question_reports_its_verdict_and_its_cost(executor):
    seen: list[runner.QuestionResult] = []
    three(executor, seen.append)
    assert all(result.outcome == "pass" for result in seen)
    assert all(result.tool_calls == 3 and result.total_tokens > 0 for result in seen)
    assert all(LINE.match(runner.progress_line(result)) for result in seen)


def test_a_run_without_a_callback_stays_silent(executor, capsys):
    assert len(three(executor)) == len(THREE)
    assert capsys.readouterr().out == ""


# ------------------------------------------------------------------ satırın biçimi


def test_the_line_reads_as_the_plan_written_it():
    line = runner.progress_line(made("pass", tool_calls=4, total_tokens=8123, seconds=12.34))
    assert LINE.match(line)
    assert line.split() == ["Q03", "✓", "pass", "4", "araç", "12.3", "sn", "8.1K", "token"]


def test_only_a_pass_gets_the_check():
    assert runner.progress_line(made("wrong_result")).split()[1] == "✗"
    assert "wrong_result" in runner.progress_line(made("wrong_result"))


def test_the_outcome_column_keeps_every_line_the_same_width():
    lines = [runner.progress_line(made(outcome)) for outcome in runner.OUTCOMES]
    assert len(lines) == len(runner.OUTCOMES)
    assert len({len(line) for line in lines}) == 1


@pytest.mark.parametrize("total,shown", [(0, "0"), (999, "999"), (1000, "1.0K"), (8123, "8.1K")])
def test_token_counts_are_written_short_from_a_thousand(total, shown):
    assert runner.progress_line(made(total_tokens=total)).endswith(f"{shown} token")


# ------------------------------------------------------------------ ekran


def test_eval_prints_one_line_per_question_before_the_score(paths, capsys):
    code = cli.evaluate(
        fake.for_golden(GOLDEN),
        only=THREE,
        db_path=paths / "test.db",
        audit_path=paths / "audit.jsonl",
        out_dir=paths / "eval_out",
    )
    out = capsys.readouterr().out
    lines = [line for line in out.splitlines() if LINE.match(line)]

    assert code == 0
    assert [line.split()[0] for line in lines] == THREE
    assert all(line.split()[1] == "✓" for line in lines)
    assert out.index(lines[0]) < out.index(lines[1]) < out.index(lines[2]) < out.index("Skor: 3/3")
