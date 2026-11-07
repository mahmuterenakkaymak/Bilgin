# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Bağlam taşması her yerde aynı adı taşır: canlı satır, rapor, ask'ın çıktısı (PLAN R4-11, R4-14).

Model yine yok; bütçe o kadar küçük seçiliyor ki hiçbir modun sistem isteme sığmıyor, yani döngü
modele hiç gitmeden duruyor. Böylece outcome'un kendisi (``context_overflow``), Delight 4 satırı,
report.md ve report.json'ın ``context`` hanesi ile ``ask``'ın tek cümlesi aynı koşu üzerinde
görülüyor. Üç soru uydurma ama SQL'leri build_db ile kurulan gerçek SQLite üzerinde çalışıyor.
"""

import json

import pytest

from bilgin import config
from bilgin.agent.fake import FakeLLM, golden_replay
from bilgin.cli import main as cli
from bilgin.engine.executor import LocalExecutor
from bilgin.eval import report, runner
from bilgin.schema_map import build

GOLDEN = [
    {
        "id": "Q01",
        "question": "Carilerin kodu ve ünvanı?",
        "sql": "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT ORDER BY CARI_KOD",
    },
    {"id": "Q02", "question": "Kaç cari var?", "sql": "SELECT COUNT(*) FROM TBLCASABIT"},
    {"id": "Q03", "question": "Carilerin ili?", "sql": "SELECT IL FROM TBLCASABIT ORDER BY IL"},
]
IDS = ["Q01", "Q02", "Q03"]
NO_ROOM = 100  # hiçbir modun sistem isteminin sığmayacağı bütçe: tur 1'de taşar


@pytest.fixture(scope="module")
def paths(tmp_path_factory):
    paths = tmp_path_factory.mktemp("overflow")
    build.build_db(config.SEED, paths / "test.db", paths / "test.sql")
    return paths


@pytest.fixture(scope="module")
def executor(paths):
    return LocalExecutor("sqlite", paths / "test.db", audit_path=paths / "audit.jsonl")


def overflow_run(executor, **kwargs):
    """Bütçe o kadar dar ki FakeLLM hiç çağrılmıyor; oynattığı kayıt bu yüzden önemsiz."""
    return runner.run_eval(
        lambda: FakeLLM(golden_replay(GOLDEN[0]["sql"])),
        executor,
        GOLDEN,
        budget=NO_ROOM,
        **kwargs,
    )


def written(run_dir) -> dict:
    return json.loads((run_dir / "report.json").read_text(encoding="utf-8"))


def markdown(run_dir) -> str:
    return (run_dir / "report.md").read_text(encoding="utf-8")


# ------------------------------------------------------------------ runner


def test_a_budget_nothing_fits_into_overflows_every_question(executor):
    results = overflow_run(executor)
    assert [result.id for result in results] == IDS
    assert [result.outcome for result in results] == ["context_overflow"] * len(IDS)
    assert all(result.outcome in runner.OUTCOMES for result in results)
    assert all(result.submitted is False and result.sql == "" for result in results)


def test_every_overflow_names_its_budget_in_its_reason(executor):
    for result in overflow_run(executor):
        assert "Bağlam bütçesi aşıldı" in result.reason
        assert f"sınır {NO_ROOM} token" in result.reason
        assert result.overflows == 1
        assert result.peak_estimate > NO_ROOM, "reddedilen tahmin soruya da yazılmalı"


def test_the_progress_line_reads_like_the_other_outcomes(executor):
    lines = [runner.progress_line(result) for result in overflow_run(executor)]
    assert all("✗ context_overflow" in line for line in lines)
    assert len({len(line) for line in lines}) == 1, "satırlar aynı sütun genişliğinde durur"


# ------------------------------------------------------------------ rapor


def test_the_report_counts_the_overflow_in_json_and_md(tmp_path, executor):
    run_dir = report.write_report(overflow_run(executor), tmp_path, model="fake")
    data = written(run_dir)
    assert [question["outcome"] for question in data["questions"]] == ["context_overflow"] * len(IDS)
    assert data["context"]["overflows"] == len(IDS)
    assert data["context"]["peak_estimate"] > NO_ROOM

    text = markdown(run_dir)
    assert "✗ context_overflow" in text
    assert "Bağlam bütçesi: tepe tahmin" in text
    assert f"{len(IDS)} soru bütçeye sığmadı" in text


def test_a_run_that_never_overflowed_says_nothing_about_the_budget(tmp_path):
    """Bütçe konuşmamışsa rapor uydurma sıfırlar yazmaz; bağlam hanesi eskisi gibi okunur."""
    results = [
        runner.QuestionResult(id="Q01", question="Soru?", outcome="pass", max_prompt_tokens=1000)
    ]
    run_dir = report.write_report(results, tmp_path)
    assert "overflows" not in written(run_dir)["context"]
    assert "Bağlam bütçesi" not in markdown(run_dir)


# ------------------------------------------------------------------ ask


def test_ask_names_the_overflow_and_exits_one(paths, capsys):
    code = cli.ask(
        GOLDEN[0]["question"],
        FakeLLM(golden_replay(GOLDEN[0]["sql"])),
        db_path=paths / "test.db",
        audit_path=paths / "audit.jsonl",
        budget=NO_ROOM,
    )
    out = capsys.readouterr().out
    assert code == 1
    assert "Cevap gönderilmedi: Bağlam bütçesi aşıldı: tahmin " in out
    assert f"sınır {NO_ROOM} token" in out
    assert "Cevap SQL:" not in out
