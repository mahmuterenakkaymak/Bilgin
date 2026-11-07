# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""``eval --schema`` ve ``merge-map``: ölçüm hangi şema dosyasıyla yapıldıysa odur (T91, PLAN R3-5).

Model yine FakeLLM; veritabanı, indeks, audit ve raporun hepsi tmp klasörde, yani test repoya
hiçbir şey yazmıyor. İki iddia var. Birincisi: koşan şemanın yolu ve imzası hem ekranda hem
raporda duruyor, yani iki koşu ancak aynı şemayı ölçtüüyse birbirinin devamı. İkincisi: R2-9'un
bayatlık denetimi de okunan o şemadan hesaplanıyor — başka bir şemayla kurulmuş indeks hiçbir soru
koşmadan reddedilir, aynı şemayla kurulanı ise koşar. ``merge-map`` zincirin üretici tarafı:
birleşik şemayı yazar, ``eval --schema`` onu okur.
"""

import json
from pathlib import Path

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.cli import main as cli
from nl2sql.eval import runner
from nl2sql.schema_map import build, doc, introspect

GOLDEN = runner.load_golden()
BUILD = "`python -m nl2sql build-index` çalıştırın"
UNREADABLE = "Şema dosyası okunamadı"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modül boyunca tek kurulum: veritabanı, varsayılan şemayla kurulmuş indeks ve audit."""
    paths = tmp_path_factory.mktemp("cli-eval-schema")
    database = paths / "test.db"
    build.build_db(config.SEED, database, paths / "test.sql")
    index = paths / "index"
    cli.build_index("fake", index_dir=index)
    return database, index, paths / "audit.jsonl"


def copy_schema(dest: Path, marker: str = "") -> Path:
    """``schema.json``ın kopyası; ``marker`` ilk tablonun açıklamasına eklenir, yani içerik değişir."""
    schema = json.loads(Path(config.SCHEMA_PATH).read_text(encoding="utf-8"))
    if marker:
        schema["tables"][0]["description"] += f" {marker}"
    dest.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
    return dest


def run(world, tmp_path, schema, mode="full", index_dir=None):
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
        schema_path=schema,
    )
    return code, out_dir


def written(out_dir, mode="full") -> dict:
    return json.loads((out_dir / mode / "latest" / "report.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ koşan şema


def test_a_copied_schema_names_itself_on_the_screen_and_in_the_report(world, tmp_path, capsys):
    schema = copy_schema(tmp_path / "musteri.json")
    code, out_dir = run(world, tmp_path, schema)
    out = capsys.readouterr().out

    assert code == 0
    assert f"Skor: {len(GOLDEN)}/{len(GOLDEN)}" in out

    data = written(out_dir)
    assert data["schema"]["path"] == str(schema)
    assert len(data["schema"]["hash"]) == 64
    assert f"Şema: {schema} ({data['schema']['hash'][:8]})" in out, "ekran kısa imzayı taşır"
    assert out.index("Şema:") < out.index("Q01"), "şema satırı canlı satırlardan önce gelir"
    assert f"- Şema: `{schema}` ({data['schema']['hash'][:8]})" in (
        out_dir / "full" / "latest" / "report.md"
    ).read_text(encoding="utf-8")


def test_the_hash_is_the_content_and_not_the_file_name(world, tmp_path):
    same = copy_schema(tmp_path / "ayni.json")
    other = copy_schema(tmp_path / "baska.json", marker="müşteri notu")

    run(world, tmp_path / "kopya", same)
    run(world, tmp_path / "farkli", other)
    run(world, tmp_path / "varsayilan", "full")

    copy = written(tmp_path / "kopya" / "eval_out")["schema"]
    changed = written(tmp_path / "farkli" / "eval_out")["schema"]
    default = written(tmp_path / "varsayilan" / "eval_out")["schema"]
    assert copy["path"] == str(same) and default["path"] == str(config.SCHEMA_PATH)
    assert copy["hash"] == default["hash"], "aynı içeriğin kopyası aynı ölçümdür"
    assert changed["hash"] != copy["hash"], "içerik değişince imza da değişmeli"


def test_full_is_the_default_schema_file(world, tmp_path):
    _, out_dir = run(world, tmp_path, "full")
    assert written(out_dir)["schema"]["path"] == str(config.SCHEMA_PATH)


def test_skeleton_is_the_config_skeleton_file(world, tmp_path, monkeypatch):
    skeleton = copy_schema(tmp_path / "iskelet.json")
    monkeypatch.setattr(config, "SKELETON_PATH", skeleton)
    _, out_dir = run(world, tmp_path, "skeleton")
    assert written(out_dir)["schema"]["path"] == str(skeleton)


# ------------------------------------------------------------------ R2-9: imza okunan şemadan


def test_rag_refuses_an_index_built_from_another_schema(world, tmp_path, capsys):
    other = copy_schema(tmp_path / "baska.json", marker="müşteri notu")
    code, out_dir = run(world, tmp_path, other, mode="rag")
    out = capsys.readouterr().out

    assert code == 2
    assert "İndeks eski" in out and BUILD in out and "Traceback" not in out
    assert "Skor:" not in out and not out_dir.exists(), "reddedilen koşunun raporu yazılmaz"


def test_rag_runs_on_an_index_built_from_the_very_schema(world, tmp_path, capsys):
    other = copy_schema(tmp_path / "baska.json", marker="müşteri notu")
    index = tmp_path / "index"
    cli.build_index("fake", index_dir=index, schema_path=other)
    capsys.readouterr()

    code, out_dir = run(world, tmp_path, other, mode="rag", index_dir=index)
    out = capsys.readouterr().out

    assert code == 0 and f"Skor: {len(GOLDEN)}/{len(GOLDEN)}" in out
    assert written(out_dir, "rag")["schema"]["path"] == str(other)


# ------------------------------------------------------------------ okunamayan şema


def test_a_schema_that_cannot_be_read_is_one_line_and_code_two(world, tmp_path, capsys):
    missing = tmp_path / "yok.json"
    code, out_dir = run(world, tmp_path, missing)
    out = capsys.readouterr().out

    assert code == 2
    assert f"{UNREADABLE}: {missing}" in out and "Traceback" not in out
    assert "Mod:" not in out and not out_dir.exists()


def test_a_file_that_is_not_a_schema_says_the_same_thing(world, tmp_path, capsys):
    mapping = tmp_path / "esleme.json"
    mapping.write_text(json.dumps({"sheets": []}), encoding="utf-8")

    assert run(world, tmp_path, mapping)[0] == 2
    out = capsys.readouterr().out
    assert f"{UNREADABLE}: {mapping}" in out and "Traceback" not in out


def test_main_routes_the_schema_option(monkeypatch):
    seen = {}
    monkeypatch.setattr(cli, "evaluate", lambda **kwargs: seen.update(kwargs) or 0)

    assert cli.main(["eval", "--llm", "fake", "--schema", "skeleton"]) == 0
    assert seen["schema_path"] == "skeleton"

    seen.clear()
    assert cli.main(["eval", "--llm", "fake"]) == 0
    assert seen["schema_path"] == "full"


# ------------------------------------------------------------------ merge-map


def test_merge_map_writes_the_merged_schema(world, tmp_path, capsys):
    database, _, _ = world
    skeleton = introspect.sqlite_skeleton(database)
    skeleton_path = tmp_path / "iskelet.json"
    skeleton_path.write_text(json.dumps(skeleton, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "merged.json"

    assert cli.merge_map(config.SCHEMA_PATH, db_schema=skeleton_path, out=out) == 0
    printed = capsys.readouterr().out
    assert f"Birleşik şema yazıldı: {out}" in printed and "Traceback" not in printed

    merged = json.loads(out.read_text(encoding="utf-8"))
    by_name = {table["name"]: table for table in doc.load_schema(config.SCHEMA_PATH)["tables"]}
    assert [table["name"] for table in merged["tables"]] == [
        table["name"] for table in skeleton["tables"]
    ], "varlık veritabanının"
    assert sum(len(table["columns"]) for table in merged["tables"]) == sum(
        len(table["columns"]) for table in skeleton["tables"]
    )
    assert all(
        table["description"] == by_name[table["name"]]["description"]
        for table in merged["tables"]
    ), "anlam Excel'den"
    assert not any(table["description"] for table in skeleton["tables"])


def test_merge_map_can_take_the_database_live(world, tmp_path, capsys):
    database, _, _ = world
    out = tmp_path / "merged.json"

    assert cli.merge_map(config.SCHEMA_PATH, db_path=database, out=out) == 0
    assert f"Veritabanı: canlı ({database})" in capsys.readouterr().out
    assert len(json.loads(out.read_text(encoding="utf-8"))["tables"]) == len(
        doc.load_schema(config.SCHEMA_PATH)["tables"]
    )


def test_merge_map_names_the_side_it_could_not_read(world, tmp_path, capsys):
    missing = tmp_path / "yok.json"

    assert cli.merge_map(config.SCHEMA_PATH, db_schema=missing, out=tmp_path / "m.json") == 2
    out = capsys.readouterr().out
    assert f"{UNREADABLE}: {missing}" in out and "Traceback" not in out
    assert not (tmp_path / "m.json").exists()
