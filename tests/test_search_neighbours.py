"""R3-9 komşu genişletmesi: bulunan tablonun join komşuları bağlama kendiliğinden girer.

İddia aramanın isabeti değil (o test_search.py'de) genişletmenin davranışı: komşular vuruşların
arkasına sıralanır ve işaretlenir, yalnız veri tablolarıdır, sayıları tablo başına `max_extra`yı
geçmez ve genişleme kapalıyken sonuç bugünkü arama listesinin ta kendisidir. İndeks ve graph
gerçek - uydurma bir graph üzerinden komşuluk sınanmaz, asıl soru zaten gerçek şemada kimin kimin
komşusu olduğu.
"""

from nl2sql import config
from nl2sql.agent import modes, tools
from nl2sql.cli.main import _search_notes
from nl2sql.graph.graph import Edge, JoinGraph, build_graph
from nl2sql.graph.profile import load_profile
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import build_search, expanded_hits
from nl2sql.schema_map import doc
from nl2sql.schema_map.rules import load_rules

SCHEMA = doc.load_schema()
RULES = load_rules()
SEARCH = build_search(SCHEMA, RULES, FakeEmbedder())
GRAPH = build_graph(SCHEMA, load_profile())
TABLES = {table["name"]: table for table in SCHEMA["tables"]}

# İlk vuruşu fatura başlığı olan bir soru: faturanın cari hesap ve depo komşuları aramanın
# bulduğu bir şey değil, şemanın söylediği bir bağlantı.
QUERY = "stok hareketleri satış iade"
MARK = " (komşu)"


def base():
    return SEARCH.search(QUERY, collection="tables", k=config.SEARCH_K)


def neighbours(name: str) -> set[str]:
    return {
        edge.right_table if edge.left_table == name else edge.left_table
        for edge in GRAPH.adjacency[name]
    }


def context(graph=GRAPH) -> modes.ToolContext:
    return modes.ToolContext(
        executor=None, schema=SCHEMA, rules=RULES, search=SEARCH, graph=graph, mode="rag"
    )


# ------------------------------------------------------------------ genişletmenin kendisi


def test_the_neighbours_follow_the_hits_and_carry_the_mark():
    hits = expanded_hits(SEARCH, QUERY, GRAPH, SCHEMA, config.SEARCH_K)
    head, extras = hits[: len(base())], hits[len(base()) :]
    assert extras, "gerçek graphta komşusuz beş vuruş olamaz"
    assert not any(hit.meta for hit in head)
    assert all(hit.meta.get("komşu") for hit in extras)
    assert [hit.rank for hit in hits] == list(range(1, len(hits) + 1))
    assert all(hit.doc_id == f"table:{hit.title}" for hit in extras)


def test_a_neighbour_is_a_data_table_adjacent_to_a_hit_and_new():
    hits = expanded_hits(SEARCH, QUERY, GRAPH, SCHEMA, config.SEARCH_K)
    extras = hits[len(base()) :]
    adjacent = set().union(*(neighbours(hit.title) for hit in base()))
    assert {hit.title for hit in extras} <= adjacent
    assert not {hit.title for hit in extras} & {hit.title for hit in base()}
    assert all(TABLES[hit.title].get("kind") != "distractor" for hit in extras)


# ------------------------------------------------------------------ kapalı hali


def test_expansion_off_is_exactly_todays_search():
    assert expanded_hits(SEARCH, QUERY, GRAPH, SCHEMA, config.SEARCH_K, expand=False) == base()


def test_no_room_for_neighbours_is_exactly_todays_search():
    assert expanded_hits(SEARCH, QUERY, GRAPH, SCHEMA, config.SEARCH_K, max_extra=0) == base()


def test_a_context_without_a_graph_still_searches():
    assert expanded_hits(SEARCH, QUERY, None, SCHEMA, config.SEARCH_K) == base()


# ------------------------------------------------------------------ aracın cevabı


def test_the_tool_without_a_graph_answers_with_the_hits_alone():
    answer = tools.dispatch("search_schema", {"query": QUERY}, context(graph=None))
    assert len(answer.splitlines()) == len(base())
    assert MARK not in answer
