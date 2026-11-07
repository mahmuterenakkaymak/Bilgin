# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``eval --compare``: üç mod aynı sorularda, tek raporda (T65).

Model yine FakeLLM ve her mod kendi kaydını oynatıyor; veritabanı, indeks, audit ve raporların
hepsi tmp klasörde, yani test repoya hiçbir şey yazmıyor. Ekranın söylediği üç şey: mod başına tek
satır, karar satırı (R2-13) ve raporun yolu (R2-14). İkinci bir ``--compare`` hiçbir modu yeniden
koşmamalı — imzası eşleşen ``latest``i olduğu için (R2-12) —, ``--fresh`` hepsini yeniden koşmalı.
"""

import json
import re

import pytest

from bilgin import config
from bilgin.agent import fake
from bilgin.cli import main as cli
from bilgin.eval import runner
from bilgin.schema_map import build

GOLDEN = runner.load_golden()
MODES = list(config.MODES)
REUSED = "(önceki koşu)"
SCORE = f"{len(GOLDEN)}/{len(GOLDEN)}"
BUILD = "Önce `python -m bilgin build-db` çalıştırın"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modül boyunca tek kurulum: veritabanı, sahte indeks ve audit tek tmp klasörde."""
    paths = tmp_path_factory.mktemp("cli-compare")
    database = paths / "test.db"
    build.build_db(config.SEED, database, paths / "test.sql")
    cli.build_index("fake", index_dir=paths / "index")
    return database, paths / "index", paths / "audit.jsonl"


def compare(world, tmp_path, **kwargs):
    """``compare_modes``ın tek çağrısı; üç modun raporu da karşılaştırma da tmp klasöre gider."""
    database, index, audit = world
    out_dir = tmp_path / "eval_out"
    code = cli.compare_modes(
        lambda mode: fake.for_golden(GOLDEN, mode=mode),
        db_path=database,
        audit_path=audit,
        out_dir=out_dir,
        index_dir=index,
        **kwargs,
    )
    return code, out_dir


def comparison(out_dir) -> dict:
    path = out_dir / "compare" / "latest" / "report.json"
    return json.loads(path.read_text(encoding="utf-8"))


def rerun(*args, **kwargs):
    raise AssertionError("imzası eşleşen mod yeniden koşulmamalı (R2-12)")


# ------------------------------------------------------------------ karşılaştırma


def test_compare_runs_every_mode_and_writes_one_report(world, tmp_path, capsys):
    code, out_dir = compare(world, tmp_path)
    out = capsys.readouterr().out
    data = comparison(out_dir)

    assert code == 0
    assert list(data["modes"]) == MODES
    assert data["questions"] == len(GOLDEN)
    for mode in MODES:
        assert data["modes"][mode]["score"] == {"passed": len(GOLDEN), "total": len(GOLDEN)}
        assert re.search(rf"^{mode}\s+{SCORE}", out, re.MULTILINE), f"{mode} satırı yok: {out}"

    assert data["verdict"]["line"].startswith("Karar:")
    assert data["verdict"]["line"] in out
    assert str(out_dir / "compare") in out
    assert REUSED not in out, "ilk koşuda yeniden kullanılan mod olamaz"


def test_rag_keeps_the_score_on_a_smaller_context(world, tmp_path):
    """R2-13'ün iki koşulu sahte modelde de birlikte duruyor: aynı skor, daha küçük bağlam."""
    compare(world, tmp_path)
    data = comparison(tmp_path / "eval_out")

    assert data["verdict"]["keep_rag"] is True
    rag = data["modes"]["rag"]["context"]["max_prompt_tokens"]
    rules = data["modes"]["full_rules"]["context"]["max_prompt_tokens"]
    assert rag < rules


# ------------------------------------------------------------------ yeniden kullanım


def test_the_second_compare_reuses_every_mode(world, tmp_path, monkeypatch, capsys):
    compare(world, tmp_path)
    capsys.readouterr()
    monkeypatch.setattr(runner, "run_eval", rerun)

    code, out_dir = compare(world, tmp_path)
    out = capsys.readouterr().out
    data = comparison(out_dir)

    assert code == 0
    assert out.count(REUSED) == len(MODES)
    assert all(data["modes"][mode]["reused"] for mode in MODES)


def test_fresh_reruns_the_modes_a_reuse_would_have_kept(world, tmp_path, capsys):
    compare(world, tmp_path)
    capsys.readouterr()

    code, out_dir = compare(world, tmp_path, fresh=True)
    out = capsys.readouterr().out
    data = comparison(out_dir)

    assert code == 0
    assert REUSED not in out
    assert not any(data["modes"][mode]["reused"] for mode in MODES)


# ------------------------------------------------------------------ arıza ve söz dizimi


def test_compare_without_a_database_says_build_first(tmp_path, capsys):
    out_dir = tmp_path / "eval_out"
    code = cli.compare_modes(
        lambda mode: fake.for_golden(GOLDEN, mode=mode),
        db_path=tmp_path / "test.db",
        audit_path=tmp_path / "audit.jsonl",
        out_dir=out_dir,
        index_dir=tmp_path / "index",
    )
    out = capsys.readouterr().out

    assert code == 2
    assert BUILD in out and "Traceback" not in out
    assert not out_dir.exists(), "koşulmayan bir karşılaştırmanın raporu yazılmamalı"


def test_main_routes_compare_and_fresh(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "compare_modes", lambda factory, **kwargs: seen.append((factory, kwargs)) or 0)

    assert cli.main(["eval", "--llm", "fake", "--compare"]) == 0
    factory, kwargs = seen[-1]
    assert kwargs["fresh"] is False
    assert isinstance(factory("rag"), fake.FakeLLM), "modun kendi kaydı fabrikadan gelir"

    assert cli.main(["eval", "--llm", "fake", "--compare", "--fresh"]) == 0
    assert seen[-1][1]["fresh"] is True
