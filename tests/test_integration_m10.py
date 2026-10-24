"""T109: M10 entegrasyonu — üç Run 3 yüzeyi gerçek parçalarla birlikte.

Elle yapılmış sahte arama/rapor yok: ölçüm gerçek şema + gerçek kurallar + gerçek join graphı +
FakeEmbedder bellekten, auto çözümü gerçek CLI'ın ``resolve_auto``su ve gerçek şema, tekrarlı
karşılaştırma gerçek veritabanı + gerçek indeks üzerinden ``cli.compare_modes``. Fazın iddiası üç
cümle: üç geri çağırma varyantı (taban/+komşu/+eşanlam) gerçek aramada koşar ve hiçbiri tabanın
altına düşmez; ``--mode auto`` gerçek şemayı gerçek indekse bakarak çözer; ``--repeat``in
karşılaştırma raporu her mod için skor yayılımını taşır.
"""

import json
import re

import pytest

from nl2sql import config
from nl2sql.agent import fake, prompt
from nl2sql.cli import main as cli
from nl2sql.eval import compare_modes, retrieval, runner
from nl2sql.graph.graph import build_graph
from nl2sql.graph.profile import load_profile
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import METHODS, build_search
from nl2sql.schema_map import build, doc
from nl2sql.schema_map.rules import load_rules

SCHEMA = doc.load_schema()
RULES = load_rules()
GOLDEN = runner.load_golden()
GRAPH = build_graph(SCHEMA, load_profile())
SEARCH = build_search(SCHEMA, RULES, FakeEmbedder())
K = 5
MODES = list(config.MODES)
TOTAL = len(GOLDEN)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Modül boyunca tek kurulum: gerçek veritabanı, sahte indeks ve tek audit yolu tmp'de."""
    paths = tmp_path_factory.mktemp("m10")
    database = paths / "test.db"
    build.build_db(config.SEED, database, paths / "test.sql")
    cli.build_index("fake", index_dir=paths / "index")
    return database, paths / "index", paths / "audit.jsonl"


# ------------------------------------------------- geri çağırma varyantları gerçek aramada


def test_the_three_variants_run_over_the_real_index_and_graph(tmp_path):
    result = retrieval.run_variants(SEARCH, GOLDEN, K, GRAPH, SCHEMA)

    assert list(result["variants"]) == ["base", "neighbours", "synonyms"]
    assert result["embedder"] == "fake:256"
    assert result["mean"]["hybrid"] > 0.0, "gerçek aramada taban hibrit geri çağırması sıfır"
    for entry in result["variants"].values():
        assert set(entry["mean"]) == set(METHODS)
    # R3-9: genişletme listeye yalnız ekler, eş anlamlı yalnız sözcük bacağını genişletir; hiçbiri
    # tabanın altına düşmez.
    base = result["variants"]["base"]["mean"]
    for name in ("neighbours", "synonyms"):
        for method in METHODS:
            assert result["variants"][name]["mean"][method] >= base[method]


def test_the_retrieval_report_lands_on_disk(tmp_path, capsys):
    out_dir = tmp_path / "retrieval"

    assert cli.eval_retrieval("fake", out_dir=out_dir) == 0
    capsys.readouterr()

    data = json.loads((out_dir / "latest" / "report.json").read_text(encoding="utf-8"))
    assert list(data["variants"]) == ["base", "neighbours", "synonyms"]
    assert data["embedder"] == "fake:256"
    markdown = (out_dir / "latest" / "report.md").read_text(encoding="utf-8")
    assert "| Soru | taban | +komşu | +eşanlam |" in markdown


# ------------------------------------------------- auto çözümü gerçek şema + gerçek indeks


def full_rules_estimate() -> int:
    return doc.estimate_tokens(prompt.full_rules_prompt(config.AS_OF, SCHEMA, RULES))


def test_auto_resolution_reads_the_real_index(world):
    _, index, _ = world
    estimate = full_rules_estimate()

    mode, est = cli.resolve_auto(SCHEMA, RULES, index)

    assert est == estimate and estimate > 0
    expected = "full_rules" if estimate <= config.AUTO_FULL_MAX_TOKENS else "rag"
    assert mode == expected, "auto gerçek şemayı gerçek indekse bakarak yanlış çözdü"


def test_auto_falls_back_to_full_without_an_index(tmp_path, capsys):
    if full_rules_estimate() <= config.AUTO_FULL_MAX_TOKENS:
        pytest.skip("gerçek şema bütçeye sığıyor; auto zaten full_rules seçer")

    mode, _ = cli.resolve_auto(SCHEMA, RULES, tmp_path / "yok")
    capsys.readouterr()

    assert mode == "full", "taze indeks yoksa auto full'a düşmeli"


# ------------------------------------------------- tekrarlı karşılaştırma skoru taşır


def test_compare_repeat_json_carries_scores(world):
    database, index, audit = world
    out_dir = world[0].parent / "eval_out"

    code = cli.compare_modes(
        lambda mode: fake.for_golden(GOLDEN, mode=mode),
        db_path=database,
        audit_path=audit,
        out_dir=out_dir,
        index_dir=index,
        repeat=2,
    )
    assert code == 0

    data = json.loads((out_dir / "compare" / "latest" / "report.json").read_text(encoding="utf-8"))
    assert data["repeat"] == 2
    assert data["questions"] == TOTAL
    for mode in MODES:
        summary = data["modes"][mode]
        scores = summary["scores"]
        assert scores["min"] <= scores["mean"] <= scores["max"]
        assert re.fullmatch(rf"\d+(\.\d+)?/{TOTAL}/{TOTAL}", compare_modes.score_cell(summary))
