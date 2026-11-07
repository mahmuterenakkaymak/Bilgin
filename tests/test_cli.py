# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Komut satırının baştan sona davranışı: kur, sor, koş.

Model burada da FakeLLM; veritabanı, audit ve rapor yollarının hepsi tmp klasörde, yani test
repoya hiçbir şey yazmıyor. Asıl soru ekranın kendisi: adımlar numarası, ✓/✗ işareti ve gecikmesiyle
duruyor, policy reddi sebebini satırın içinde gösteriyor, tablo Türkçe sayılarla basılıyor, audit
satırları soruları taşıyor ama satırları taşımıyor.
"""

import json
import re

import pytest

from bilgin import config
from bilgin.agent import fake
from bilgin.agent.fake import FakeLLM
from bilgin.agent.llm import OpenAIClient
from bilgin.cli import main as cli
from bilgin.eval import runner
from bilgin.schema_map import build

GOLDEN = runner.load_golden()
BY_ID = {line["id"]: line for line in GOLDEN}


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    """Modül boyunca tek kurulum: sorgular gerçek SQLite üzerinde yürütülüyor."""
    paths = tmp_path_factory.mktemp("cli")
    database = paths / "test.db"
    build.build_db(config.SEED, database, paths / "test.sql")
    return database


def ask(question, llm, db, tmp_path):
    return cli.ask(question, llm, db_path=db, audit_path=tmp_path / "audit.jsonl")


# ------------------------------------------------------------------ build-db


def test_build_db_writes_both_targets(tmp_path, capsys):
    database, script = tmp_path / "test.db", tmp_path / "test.sql"
    assert cli.build_database(seed=7, db_path=database, sql_path=script) == 0
    assert database.exists() and script.exists()

    out = capsys.readouterr().out
    assert "Tohum: 7" in out and str(database) in out and str(script) in out
    assert build.checksum(database)[:12] in out


# ------------------------------------------------------------------ ask


def test_ask_shows_the_steps_the_sql_and_the_table(db, tmp_path, capsys):
    line = BY_ID["Q03"]
    code = ask(line["question"], fake.for_golden(GOLDEN), db, tmp_path)
    out = capsys.readouterr().out

    assert code == 0
    assert f"Soru: {line['question']}" in out
    assert " 1 ✓ get_schema" in out and " 2 ✓ run_sql" in out and " 3 ✓ submit_sql" in out
    assert re.search(r"\d+ ms", out)
    assert line["sql"] in out
    assert re.search(r"\d,\d{2}", out)
    assert "Token:" in out and "Süre:" in out


def test_a_policy_reject_shows_its_reason_inline(db, tmp_path, capsys):
    """Delight 6: guardrail çalıştığı ekranda görünmeli; red satırı sebebiyle birlikte durur."""
    line = BY_ID["Q01"]
    code = ask(line["question"], FakeLLM(fake.forbidden_then_recover(line["sql"])), db, tmp_path)
    out = capsys.readouterr().out

    assert code == 0
    assert "✗ run_sql" in out
    assert "Hata (policy)" in out and "Sistem kataloğu" in out
    assert line["sql"] in out


def test_a_run_that_never_submits_says_so(db, tmp_path, capsys):
    code = ask("Boş bir şey?", FakeLLM(fake.never_submit()), db, tmp_path)
    out = capsys.readouterr().out

    assert code == 1
    assert "Cevap gönderilmedi" in out and "listeledim" in out
    assert "Sonuç:" not in out and "Cevap SQL" not in out


def test_every_query_is_audited_under_ask_without_rows(db, tmp_path):
    line = BY_ID["Q01"]
    ask(line["question"], FakeLLM(fake.forbidden_then_recover(line["sql"])), db, tmp_path)
    entries = [
        json.loads(entry)
        for entry in (tmp_path / "audit.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert [entry["outcome"] for entry in entries] == ["policy", "ok", "ok", "ok"]
    assert all(entry["source"] == "ask" and entry["sql"] for entry in entries)
    assert all("rows" not in entry for entry in entries)


# ------------------------------------------------------------------ eval


def test_eval_scores_the_golden_run_and_writes_the_report(db, tmp_path, capsys):
    out_dir = tmp_path / "eval_out"
    code = cli.evaluate(
        fake.for_golden(GOLDEN), db_path=db, audit_path=tmp_path / "audit.jsonl", out_dir=out_dir
    )
    out = capsys.readouterr().out
    data = json.loads((out_dir / "latest" / "report.json").read_text(encoding="utf-8"))

    assert code == 0
    assert f"Skor: {len(GOLDEN)}/{len(GOLDEN)}" in out
    assert data["score"] == {"passed": len(GOLDEN), "total": len(GOLDEN)}
    assert data["model"] == "fake"
    assert str(out_dir) in out


def test_only_runs_the_asked_questions(db, tmp_path, capsys):
    code = cli.evaluate(
        fake.for_golden(GOLDEN),
        only=["Q03"],
        db_path=db,
        audit_path=tmp_path / "audit.jsonl",
        out_dir=tmp_path / "eval_out",
    )
    assert code == 0
    assert "Skor: 1/1" in capsys.readouterr().out


# ------------------------------------------------------------------ argparse


def test_the_llm_flag_picks_the_client():
    assert isinstance(cli.make_client("fake"), FakeLLM)
    client = cli.make_client("openai")
    assert isinstance(client, OpenAIClient)
    assert client.base_url == config.llm_settings().base_url


def test_main_routes_build_db(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "build_database", lambda **kwargs: seen.update(kwargs) or 0)
    assert cli.main(["build-db", "--seed", "7"]) == 0
    assert seen == {"seed": 7}


def test_main_routes_ask_and_eval(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "ask", lambda **kwargs: seen.update(kwargs) or 0)
    monkeypatch.setattr(cli, "evaluate", lambda **kwargs: seen.update(kwargs) or 0)

    assert cli.main(["ask", "Geçen ayın cirosu?", "--llm", "fake"]) == 0
    assert seen["question"] == "Geçen ayın cirosu?" and isinstance(seen["llm"], FakeLLM)

    assert cli.main(["eval", "--llm", "fake", "--only", "Q03"]) == 0
    assert seen["only"] == ["Q03"] and isinstance(seen["llm"], FakeLLM)


@pytest.mark.parametrize("argv", [[], ["yok-boyle-bir-komut"], ["ask"], ["eval", "--llm", "olmayan"]])
def test_bad_command_lines_are_rejected(argv):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(argv)
    assert exit_info.value.code != 0
