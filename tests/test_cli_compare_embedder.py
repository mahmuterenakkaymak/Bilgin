"""``eval --compare`` embedder değişince rag'in eski koşusunu yeniden kullanmaz (T74).

README kullanıcıya ``NL2SQL_EMBED_MODEL`` değiştirip indeksi yeniden kurmayı söylüyor; içerik imzası
şema + kural olduğu için o değişimde aynı kalıyordu, yani rag ``(önceki koşu)`` basıyor ve R2-13
kararı bayat bir rag koşusuyla kuruluyordu. İmza vektörlerin kiminle üretildiğini de taşıdığı için
embedder'ı değişen koşuda yalnız rag yeniden koşar; şemaya dokunulmadığı için diğer iki mod yerinde
durur. Veritabanı, indeks, audit ve raporların hepsi tmp klasörde.
"""

import json

import pytest

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.cli import main as cli
from nl2sql.eval import runner
from nl2sql.schema_map import build

GOLDEN = runner.load_golden()
MODES = list(config.MODES)
REUSED = "(önceki koşu)"


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modül boyunca tek kurulum: veritabanı, indeks ve audit tek tmp klasörde."""
    paths = tmp_path_factory.mktemp("cli-compare-embedder")
    database = paths / "test.db"
    build.build_db(config.SEED, database, paths / "test.sql")
    return database, paths / "index", paths / "audit.jsonl"


def compare(world, tmp_path, embed: str, **kwargs) -> dict:
    """İndeksi ``embed`` ile kur, üç modu karşılaştır, karşılaştırma json'unu döndür."""
    database, index, audit = world
    assert cli.build_index(embed, index_dir=index) == 0
    out_dir = tmp_path / "eval_out"
    code = cli.compare_modes(
        lambda mode: fake.for_golden(GOLDEN, mode=mode),
        db_path=database,
        audit_path=audit,
        out_dir=out_dir,
        index_dir=index,
        **kwargs,
    )
    assert code == 0
    return json.loads((out_dir / "compare" / "latest" / "report.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------ yeniden kullanım


def test_the_second_compare_reuses_rag_too(world, tmp_path, capsys):
    """İndeks aynı embedder ile yeniden kurulsa bile imza değişmez; rag boşuna koşulmamalı."""
    first = compare(world, tmp_path, "fake:64")
    capsys.readouterr()

    second = compare(world, tmp_path, "fake:64")
    out = capsys.readouterr().out

    assert not any(first["modes"][mode]["reused"] for mode in MODES)
    assert all(second["modes"][mode]["reused"] for mode in MODES)
    assert out.count(REUSED) == len(MODES)


def test_a_new_embedder_reevals_only_rag(world, tmp_path, capsys):
    """Embedder değişince rag'in ``latest``i bayat: karar yeni bir rag koşusuyla kurulmalı."""
    compare(world, tmp_path, "fake:64")
    compare(world, tmp_path, "fake:64")
    capsys.readouterr()

    third = compare(world, tmp_path, "fake:128")
    out = capsys.readouterr().out

    assert third["modes"]["rag"]["reused"] is False
    assert third["modes"]["full"]["reused"] is True
    assert third["modes"]["full_rules"]["reused"] is True
    assert out.count(REUSED) == len(MODES) - 1
    assert third["verdict"]["line"].startswith("Karar:")
