# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``eval --ambiguous`` skoru: belirsiz set netleştirmeyi ölçer, kill-gate'in paydasına girmez.

Skor üç yerde duruyor — report.json, report.md ve konsol — ve üçünün de aynı paydayı taşıması
gerekir. Metrik bloğunun ``Doğruluk``'u altın set üzerinden bölündüğü için, belirsiz satırları
skora katmak aynı koşumda iki ayrı doğruluk (ve karar eşiğinin aşağı çekilmesi) demekti (R5-12,
R5-14). Testlerin yarısı kuralı sahte satırlarla doğrudan ``write_report`` üzerinden ölçer;
konsol satırı gerçek bir koşumla (FakeLLM, tmp veritabanı) sınanır.
"""

import dataclasses
import json

import pytest

from nl2sql import config, datasets
from nl2sql.cli import main as cli
from nl2sql.eval import report
from nl2sql.eval.runner import QuestionResult
from nl2sql.schema_map import build

DATASET = "synthetic_erp"
TOP = report.DECISIONS[0][1]


def made(count: int, outcome: str, kind: str) -> list[QuestionResult]:
    """Bir setin sahte satırları: skorun okuduğu iki alan, yani outcome ve kind."""
    return [
        QuestionResult(
            id=f"{kind[0].upper()}{n:02d}",
            question="Soru?",
            outcome=outcome,
            sql="SELECT 1",
            golden_sql="SELECT 1",
            tool_calls=2,
            total_tokens=200,
            seconds=1.0,
            kind=kind,
            submitted=kind == "golden",
        )
        for n in range(1, count + 1)
    ]


def written(tmp_path, results) -> tuple[dict, str]:
    """Koşumun diske bıraktığı ikili: report.json ve report.md."""
    run_dir = report.write_report(results, tmp_path, model="fake")
    data = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    return data, (tmp_path / "latest" / "report.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ raporun kendisi


def test_the_ambiguous_lines_stay_out_of_the_score(tmp_path):
    data, text = written(tmp_path, made(5, "pass", "golden") + made(3, "clarified", "ambiguous"))

    assert data["score"] == {"passed": 5, "total": 5}
    assert "## Skor: 5/5" in text
    # Metrikler ve soru listesi her satırı korur: belirsiz setin kendi ölçüsü orada durur.
    assert data["metrics"]["golden"] == 5 and data["metrics"]["ambiguous"] == 3
    assert data["metrics"]["accuracy"] == 1.0
    assert len(data["questions"]) == 8


def test_the_decision_comes_from_the_golden_set(tmp_path):
    # Altın set tam puanlı; belirsiz satırlar paydaya girseydi 5/8 "Yeniden kur" eşiğine düşerdi.
    data, text = written(tmp_path, made(5, "pass", "golden") + made(3, "clarified", "ambiguous"))

    assert data["decision"] == TOP
    assert f"**{TOP}**" in text


def test_a_plain_run_scores_every_line_it_ran(tmp_path):
    results = made(5, "pass", "golden")
    results[-1] = dataclasses.replace(results[-1], outcome="wrong_result")

    data, text = written(tmp_path, results)

    assert data["score"] == {"passed": 4, "total": 5}
    assert "## Skor: 4/5" in text


def test_ambiguous_lines_alone_measure_no_score(tmp_path):
    data, _ = written(tmp_path, made(3, "clarified", "ambiguous"))

    assert data["score"] == {"passed": 0, "total": 0}
    assert data["decision"] == report.NO_QUESTIONS
    assert data["metrics"]["clarify_recall"] == 1.0


# ------------------------------------------------------------------ konsol


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modül boyunca tek kurulum: sentetik dünyanın veritabanı ve audit'i tek tmp klasörde."""
    paths = tmp_path_factory.mktemp("eval-ambiguous-score")
    database = paths / "test.db"
    build.build_db(config.SEED, database, paths / "test.sql")
    return database, paths / "audit.jsonl"


def evaluate(world, out_root, **kwargs):
    """``evaluate``ın tek çağrısı; out_root testler arasında ayrı olmalı ki ``latest``ler karışmasın."""
    database, audit = world
    out_dir = out_root / "eval_out"
    ds = datasets.load_dataset(DATASET)
    code = cli.evaluate(
        cli.make_client("fake", "full", ds),
        db_path=database,
        audit_path=audit,
        out_dir=out_dir / "full",
        dataset=DATASET,
        **kwargs,
    )
    return code, out_dir


def score_line(out: str) -> str:
    return next(line for line in out.splitlines() if line.startswith("Skor:"))


def test_the_console_score_is_the_golden_score(world, tmp_path, capsys):
    ds = datasets.load_dataset(DATASET)
    golden, ambiguous = len(ds.golden()), len(ds.ambiguous())

    code, out_dir = evaluate(world, tmp_path, ambiguous=True)
    out = capsys.readouterr().out
    data = json.loads((out_dir / "full" / "latest" / "report.json").read_text(encoding="utf-8"))
    text = (out_dir / "full" / "latest" / "report.md").read_text(encoding="utf-8")

    assert code == 0
    assert score_line(out) == f"Skor: {golden}/{golden}"
    assert data["score"] == {"passed": golden, "total": golden}
    assert f"## Skor: {golden}/{golden}" in text
    # Ekrandaki skor, hemen altında basılan Doğruluk ile aynı şeyi söyler (R5-14).
    assert data["metrics"]["accuracy"] == 1.0
    assert len(data["questions"]) == golden + ambiguous


def test_an_ambiguous_run_scores_exactly_like_the_plain_one(world, tmp_path, capsys):
    plain_code, _ = evaluate(world, tmp_path / "plain")
    plain = score_line(capsys.readouterr().out)

    code, _ = evaluate(world, tmp_path / "ambiguous", ambiguous=True)
    out = capsys.readouterr().out

    assert code == plain_code == 0
    assert score_line(out) == plain
    assert "Metrikler:" in out, "belirsiz koşumun metrik bloğu skoru yutmadı"
