"""``eval --mode`` ve ``--tag``: her mod kendi klasörüne, her etiket kendi kümesine koşar (T63).

Model yine FakeLLM; veritabanı, indeks, audit ve raporun hepsi tmp klasörde, yani test repoya
hiçbir şey yazmıyor. Ekranın göstermesi gereken üç şey var: rag gerçekten diskteki indeksten ve
join graphından besleniyor (adım listesinde ``search_schema`` duruyor), rapor modun kendi
klasörüne yazılıyor (R2-12 — iki mod birbirinin devamı değil), ve kullanıcının düzeltebileceği iki
arıza — boş bir etiket ile eksik/bayat indeks — iz dökümü değil tek cümle ve kod 2.
"""

import json
import shutil

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.cli import main as cli
from nl2sql.eval import runner
from nl2sql.index.store import META_FILE
from nl2sql.schema_map import build

GOLDEN = runner.load_golden()
ARCHIVE = [line["id"] for line in GOLDEN if "archive" in line["tags"]]
BUILD = "`python -m nl2sql build-index` çalıştırın"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modül boyunca tek kurulum: veritabanı, sahte indeks ve audit tek tmp klasörde."""
    paths = tmp_path_factory.mktemp("cli-eval-modes")
    database = paths / "test.db"
    build.build_db(config.SEED, database, paths / "test.sql")
    cli.build_index("fake", index_dir=paths / "index")
    return database, paths / "index", paths / "audit.jsonl"


def run(world, tmp_path, mode, index_dir=None, **kwargs):
    """``evaluate``ın tek çağrısı; rapor ``out_dir/<mode>`` altına gider, out_dir geri verilir."""
    database, index, audit = world
    out_dir = tmp_path / "eval_out"
    code = cli.evaluate(
        fake.for_golden(GOLDEN, mode=mode),
        mode=mode,
        db_path=database,
        audit_path=audit,
        out_dir=out_dir / mode,
        index_dir=index_dir or index,
        **kwargs,
    )
    return code, out_dir


def written(out_dir, mode) -> dict:
    return json.loads((out_dir / mode / "latest" / "report.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ modlar


def test_rag_scores_every_question_through_the_index_and_the_graph(world, tmp_path, capsys):
    code, out_dir = run(world, tmp_path, "rag")
    out = capsys.readouterr().out

    assert code == 0
    assert "Mod: rag" in out and f"Skor: {len(GOLDEN)}/{len(GOLDEN)}" in out

    data = written(out_dir, "rag")
    assert data["mode"] == "rag"
    assert data["score"] == {"passed": len(GOLDEN), "total": len(GOLDEN)}
    assert {"search_schema", "get_table_details"} <= {
        step["tool"] for step in data["questions"][0]["steps"]
    }, "rag aracının yolu indeksten geçmeli"
    assert data["config"]["fingerprint"]["index_hash"], "rag imzası indeksi de taşır"


def test_full_rules_scores_every_question_without_needing_an_index(world, tmp_path, capsys):
    code, out_dir = run(world, tmp_path, "full_rules", index_dir=tmp_path / "yok")
    out = capsys.readouterr().out

    assert code == 0 and "Mod: full_rules" in out
    data = written(out_dir, "full_rules")
    assert data["score"] == {"passed": len(GOLDEN), "total": len(GOLDEN)}
    assert [question["mode"] for question in data["questions"]] == ["full_rules"] * len(GOLDEN)
    assert data["config"]["fingerprint"]["index_hash"] == ""
    assert not (out_dir / "latest").exists(), "R2-12: latest modun kendi klasöründe durur"


# ------------------------------------------------------------------ etiket


def test_a_tag_runs_only_the_questions_carrying_it(world, tmp_path, capsys):
    assert ARCHIVE, "senaryo boş bir kümenin üzerinde geçmesin"
    code, out_dir = run(world, tmp_path, "full", tags=["archive"])
    out = capsys.readouterr().out

    assert code == 0 and "Mod: full" in out
    assert f"Skor: {len(ARCHIVE)}/{len(ARCHIVE)}" in out
    data = written(out_dir, "full")
    assert [question["id"] for question in data["questions"]] == ARCHIVE
    assert data["tags"]["archive"] == {"passed": len(ARCHIVE), "total": len(ARCHIVE)}


def test_a_tag_no_question_carries_names_the_tag_and_runs_nothing(world, tmp_path, capsys):
    code, out_dir = run(world, tmp_path, "full", tags=["boyle-etiket-yok"])
    out = capsys.readouterr().out

    assert code == 2
    assert "Bu etiketle soru yok: boyle-etiket-yok" in out and "Traceback" not in out
    assert "Mod:" not in out and "Skor:" not in out
    assert not out_dir.exists(), "koşulmayan bir koşunun raporu yazılmamalı"


# ------------------------------------------------------------------ indeks yok / bayat


def test_rag_without_an_index_says_build_it(world, tmp_path, capsys):
    code, out_dir = run(world, tmp_path, "rag", index_dir=tmp_path / "yok")
    out = capsys.readouterr().out

    assert code == 2
    assert "İndeks bulunamadı" in out and BUILD in out and "Traceback" not in out
    assert "Skor:" not in out and not out_dir.exists()


def test_a_stale_index_is_refused_instead_of_rebuilt(world, tmp_path, capsys):
    stale = tmp_path / "index"
    shutil.copytree(world[1], stale)
    meta = json.loads((stale / META_FILE).read_text(encoding="utf-8"))
    (stale / META_FILE).write_text(
        json.dumps({**meta, "content_hash": "bayat"}), encoding="utf-8"
    )

    code, out_dir = run(world, tmp_path, "rag", index_dir=stale)
    out = capsys.readouterr().out

    assert code == 2
    assert "İndeks eski" in out and BUILD in out and "Traceback" not in out
    assert "Skor:" not in out and not out_dir.exists()


# ------------------------------------------------------------------ istemci ve söz dizimi


def test_the_fake_client_replays_the_mode_it_is_given():
    messages = [{"role": "user", "content": GOLDEN[0]["question"]}]
    assert cli.make_client("fake", "rag").chat(messages).tool_calls[0].name == "search_schema"
    assert cli.make_client("fake").chat(messages).tool_calls[0].name == "get_schema"


def test_main_routes_the_mode_and_the_tag(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "evaluate", lambda **kwargs: seen.update(kwargs) or 0)

    assert cli.main(["eval", "--llm", "fake", "--mode", "rag", "--tag", "archive"]) == 0
    assert seen["mode"] == "rag" and seen["tags"] == ["archive"]

    seen.clear()
    assert cli.main(["eval", "--llm", "fake"]) == 0
    assert seen["mode"] == config.DEFAULT_EVAL_MODE and seen["tags"] is None


def test_an_unknown_mode_is_rejected_by_argparse():
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["eval", "--llm", "fake", "--mode", "uydurma"])
    assert exit_info.value.code != 0
