"""``eval --compare --schema``: üç mod da adıyla verilen şemayla ölçer (T112, PLAN R3-5).

Model yine FakeLLM; veritabanı, indeks, audit ve raporların hepsi tmp klasörde, yani test repoya
hiçbir şey yazmıyor. Kurulan şemanın kopyası işaretli, yani imzası ``schema.json``dan farklı:
koşan üç modun raporu da o kopyayı adlandırıp onun imzasını taşırsa ``--compare`` artık başka bir
şemayı ölçmüş gibi okunmaz. Ekran aynı dosyayı mod satırlarından önce söyler. Okunamayan bir
``--schema`` ise hiçbir mod koşmadan çıkar (R3-13'ün tek cümlesi, kod 2).
"""

import json
from pathlib import Path

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.cli import main as cli
from nl2sql.eval import report, runner
from nl2sql.schema_map import build, doc

GOLDEN = runner.load_golden()
MODES = list(config.MODES)
RUNNING = "koşuluyor ..."
UNREADABLE = "Şema dosyası okunamadı"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modül boyunca tek kurulum: veritabanı ve audit tek tmp klasörde; indeks şemaya bağlı."""
    paths = tmp_path_factory.mktemp("cli-compare-schema")
    database = paths / "test.db"
    build.build_db(config.SEED, database, paths / "test.sql")
    return database, paths / "audit.jsonl"


def marked(dest: Path) -> Path:
    """``schema.json``ın imzasını değiştiren kopya: ilk tablonun açıklamasına bir not eklenir."""
    schema = json.loads(Path(config.SCHEMA_PATH).read_text(encoding="utf-8"))
    schema["tables"][0]["description"] += " müşteri notu"
    dest.write_text(json.dumps(schema, ensure_ascii=False), encoding="utf-8")
    return dest


def index_for(tmp_path, schema: Path) -> Path:
    """Kopya şemayla kurulmuş sahte indeks: rag'in imza denetimi okunan şemadan hesaplanır (R2-9)."""
    index = tmp_path / "index"
    cli.build_index("fake", index_dir=index, schema_path=schema)
    return index


def compare(world, tmp_path, schema: Path, index: Path):
    """``compare_modes``ın tek çağrısı; üç modun raporu da karşılaştırma da tmp klasöre gider."""
    database, audit = world
    out_dir = tmp_path / "eval_out"
    code = cli.compare_modes(
        lambda mode: fake.for_golden(GOLDEN, mode=mode),
        db_path=database,
        audit_path=audit,
        out_dir=out_dir,
        index_dir=index,
        schema_path=schema,
    )
    return code, out_dir


def mode_report(out_dir: Path, mode: str) -> dict:
    path = out_dir / mode / "latest" / "report.json"
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ koşan şema


def test_every_mode_reports_the_schema_it_was_measured_against(world, tmp_path, capsys):
    schema = marked(tmp_path / "musteri.json")
    index = index_for(tmp_path, schema)
    capsys.readouterr()

    code, out_dir = compare(world, tmp_path, schema, index)
    out = capsys.readouterr().out

    assert code == 0
    expected = report.schema_info(schema, doc.load_schema(schema))
    assert f"Şema: {schema} ({expected['hash'][:8]})" in out
    assert out.index("Şema:") < out.index(RUNNING), "şema satırı mod satırlarından önce gelir"
    for mode in MODES:
        data = mode_report(out_dir, mode)
        assert data["schema"] == expected, f"{mode} başka bir şemayı ölçmüş gibi yazdı"
        assert data["schema"]["hash"] != report.schema_info(
            config.SCHEMA_PATH, doc.load_schema()
        )["hash"], "işaretli kopya schema.json ile aynı ölçüm değildir"


# ------------------------------------------------------------------ söz dizimi ve arıza


def test_main_routes_the_schema_option_to_compare(monkeypatch):
    seen = []
    monkeypatch.setattr(cli, "compare_modes", lambda factory, **kwargs: seen.append(kwargs) or 0)

    assert cli.main(["eval", "--llm", "fake", "--compare", "--schema", "X"]) == 0
    assert seen[-1]["schema_path"] == "X"

    seen.clear()
    assert cli.main(["eval", "--llm", "fake", "--compare"]) == 0
    assert seen[-1]["schema_path"] == "full"


def test_an_unreadable_schema_stops_the_compare_before_any_mode(world, tmp_path, capsys):
    database, audit = world
    missing = tmp_path / "yok.json"
    out_dir = tmp_path / "eval_out"

    code = cli.compare_modes(
        lambda mode: fake.for_golden(GOLDEN, mode=mode),
        db_path=database,
        audit_path=audit,
        out_dir=out_dir,
        index_dir=tmp_path / "index",
        schema_path=missing,
    )
    out = capsys.readouterr().out

    assert code == 2
    assert f"{UNREADABLE}: {missing}" in out and "Traceback" not in out
    assert RUNNING not in out and not out_dir.exists(), "koşulmayan bir karşılaştırmanın raporu yazılmaz"
