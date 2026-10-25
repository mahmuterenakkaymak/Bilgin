"""T117: taban varyantı eş anlamlı genişletmesini aramaya da söylemeli.

R3-9'un hükmü "hiçbir varyant recall@5'i düşürmez" tabanla +eşanlamı karşılaştırır; ikisi de
genişletmeyle koşuyorsa karşılaştırılan bir şey kalmaz — ölçümde taban ile +eşanlam aynı çıktı.
Burada sayı değil düğmenin kendisi ölçülüyor: aramaya giden her çağrıda ``rewrite`` ne gördü.
Stubın kendi varsayılanı bilerek ``False`` değil; çağıranın varsayana düşmesi ancak böyle görünür.
"""

from types import SimpleNamespace

from nl2sql import config
from nl2sql.eval import retrieval
from nl2sql.index.search import METHODS, Hit

GOLDEN = [
    {"id": "Q01", "question": "soru bir", "tags": ["x"], "requires_tables": ["TABLO_A"]},
    {"id": "Q02", "question": "soru iki", "tags": ["x"], "requires_tables": ["TABLO_C"]},
]

# Komşu bacağı için yeterli olan en küçük haller: graph komşusuz, şema iki veri tablosu.
GRAPH = SimpleNamespace(adjacency={})
SCHEMA = {"tables": [{"name": "TABLO_A"}, {"name": "TABLO_C"}]}

UNSET = object()


class RecordingSearch:
    """Aramanın eş anlamlı düğmesine gerçekten ne geçtiğini kaydeden sahte arama."""

    def __init__(self) -> None:
        self.rewrites: list[object] = []
        self.embedder = SimpleNamespace(id="stub:1")

    def search(
        self, query, collection="tables", k=config.SEARCH_K, method="hybrid", rewrite=UNSET
    ):
        self.rewrites.append(rewrite)
        return [Hit(doc_id="table:TABLO_A", title="TABLO_A", score=1.0, rank=1)]


def calls_per_variant() -> int:
    return len(GOLDEN) * len(METHODS)


def test_the_base_measurement_hands_the_rewrite_off_to_the_search():
    search = RecordingSearch()
    retrieval.run_retrieval(search, GOLDEN, k=3, expand=False, rewrite=False)
    assert search.rewrites == [False] * calls_per_variant()


def test_the_synonym_measurement_hands_the_rewrite_on():
    search = RecordingSearch()
    retrieval.run_retrieval(search, GOLDEN, k=3, expand=False, rewrite=True)
    assert search.rewrites == [True] * calls_per_variant()


def test_run_variants_never_rewrites_on_the_base_leg():
    search = RecordingSearch()
    report = retrieval.run_variants(search, GOLDEN, k=3, graph=GRAPH, schema=SCHEMA)

    assert list(report["variants"]) == ["base", "neighbours", "synonyms"]
    size = calls_per_variant()
    legs = {
        name: search.rewrites[start : start + size]
        for name, start in zip(report["variants"], range(0, len(search.rewrites), size))
    }
    assert set(legs["base"]) == {False}
    assert set(legs["neighbours"]) == {False}
    assert set(legs["synonyms"]) == {True}
