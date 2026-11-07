# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``--mode auto`` (T107, PLAN R3-10): bağlam tahminine göre modun kendiliğinden seçilmesi.

Ölçüt tam kurallı sistem isteminin tahmini: bütçeye sığıyorsa full_rules, sığmıyorsa rag; rag'in
taze indeksi yoksa notla full. Eşiğin iki tarafı da şemanın büyüklüğüne bırakılmayıp config değeri
oynatılarak sınanır, böylece test gerçek şemanın bugün kaç token olduğuna bağlı kalmaz. ``ask``ın
varsayılanı auto'dur ve çözülen mod hem ekrana hem koşuya (AgentRun.mode) işler; eval ise auto'yu
açık bir cümleyle reddeder.
"""

import json

import pytest

from bilgin import config
from bilgin.agent import fake, prompt
from bilgin.agent.loop import AgentRun
from bilgin.cli import main as cli
from bilgin.eval import runner
from bilgin.schema_map import build, doc
from bilgin.schema_map.rules import load_rules

GOLDEN = runner.load_golden()
BY_ID = {line["id"]: line for line in GOLDEN}
FALLBACK = cli.NO_INDEX_NOTE


def estimate_of(schema, rules) -> int:
    return doc.estimate_tokens(prompt.full_rules_prompt(config.AS_OF, schema, rules))


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modül boyunca tek kurulum: veritabanı, gerçek şema/kuralla kurulmuş taze indeks ve audit."""
    paths = tmp_path_factory.mktemp("cli-auto")
    database = paths / "test.db"
    build.build_db(config.SEED, database, paths / "test.sql")
    cli.build_index("fake", index_dir=paths / "index")
    return database, paths / "index", paths / "audit.jsonl"


# ------------------------------------------------------------------ resolve_auto: üç sonuç

def test_a_small_schema_stays_full_rules(tmp_path):
    small = {"tables": [{"name": "TBLKUCUK", "columns": [{"name": "KOD", "type": "int"}]}]}
    path = tmp_path / "kucuk.json"
    path.write_text(json.dumps(small), encoding="utf-8")
    schema = doc.load_schema(path)

    mode, estimate = cli.resolve_auto(schema, [], tmp_path / "index")

    assert mode == "full_rules" and estimate <= config.AUTO_FULL_MAX_TOKENS


def test_at_the_threshold_full_rules_still_wins(world, monkeypatch):
    schema, rules = doc.load_schema(), load_rules()
    estimate = estimate_of(schema, rules)
    monkeypatch.setattr(config, "AUTO_FULL_MAX_TOKENS", estimate)  # sınırdaki dahil

    mode, est = cli.resolve_auto(schema, rules, world[1])

    assert mode == "full_rules" and est == estimate


def test_one_token_over_the_threshold_uses_the_index(world, monkeypatch):
    schema, rules = doc.load_schema(), load_rules()
    estimate = estimate_of(schema, rules)
    monkeypatch.setattr(config, "AUTO_FULL_MAX_TOKENS", estimate - 1)  # bir token taşınca rag

    mode, est = cli.resolve_auto(schema, rules, world[1])

    assert mode == "rag" and est == estimate


def test_over_the_threshold_without_an_index_falls_back_to_full(world, tmp_path, monkeypatch, capsys):
    schema, rules = doc.load_schema(), load_rules()
    estimate = estimate_of(schema, rules)
    monkeypatch.setattr(config, "AUTO_FULL_MAX_TOKENS", estimate - 1)

    mode, est = cli.resolve_auto(schema, rules, tmp_path / "yok")

    assert mode == "full" and est == estimate
    assert FALLBACK in capsys.readouterr().out


# ------------------------------------------------------------------ ask: auto varsayılanı

def test_ask_default_auto_prints_the_resolution(world, monkeypatch, capsys):
    monkeypatch.setattr(config, "AUTO_FULL_MAX_TOKENS", 10**9)  # her halükarda full_rules
    line = BY_ID["Q03"]

    code = cli.ask(
        line["question"],
        fake.for_golden(GOLDEN, mode="full_rules"),
        mode="auto",
        db_path=world[0],
        audit_path=world[2],
        index_dir=world[1],
    )
    out = capsys.readouterr().out

    assert code == 0
    assert "Mod: auto -> full_rules (bağlam tahmini " in out
    assert "Mod: full_rules\n" not in out, "auto çözümü düz mod satırının yerini almalı"


def test_ask_resolves_auto_before_the_run(world, monkeypatch):
    seen = {}

    def spy(question, llm, executor, schema, source, *, mode, context):
        seen["mode"] = mode
        return AgentRun(question=question, mode=mode)

    monkeypatch.setattr(cli, "run_agent", spy)
    monkeypatch.setattr(config, "AUTO_FULL_MAX_TOKENS", 10**9)

    cli.ask(
        "Soru?",
        fake.FakeLLM([]),
        mode="auto",
        db_path=world[0],
        audit_path=world[2],
        index_dir=world[1],
    )

    assert seen["mode"] == "full_rules", "koşuya çözülmüş mod gitmeli, auto değil"


def test_main_defaults_ask_to_a_resolved_mode(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "resolve_auto", lambda *a, **k: ("full_rules", 1234))
    monkeypatch.setattr(cli, "ask", lambda **kwargs: seen.update(kwargs) or 0)

    assert cli.main(["ask", "Geçen ayın cirosu?", "--llm", "fake"]) == 0

    assert seen["mode"] == "full_rules" and seen["estimate"] == 1234


# ------------------------------------------------------------------ eval: auto reddi

def test_eval_rejects_auto_with_a_clear_message(capsys):
    code = cli.main(["eval", "--llm", "fake", "--mode", "auto"])
    out = capsys.readouterr().out

    assert code == 2
    assert "auto" in out and "Traceback" not in out
