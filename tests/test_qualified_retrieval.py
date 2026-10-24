"""R4-8: retrieval, graph, araçlar ve CLI tam adlarla konuşur - mini kümesi üzerinde.

Çıplak ad modelin ezberinde olan şey, tam ad şemanın söylediği şey. İddia dört yerde aynı: indeks
dokümanı tabloyu `table:<tam ad>` ile tanır ve metninin tokenları şema ile tablo kısmını ayrı ayrı
içerir; graph fk kenarlarını tam adlarla örer; araçlar çıplak adı kabul edip tam adla cevap verir;
CLI'ın adım notu regexi `Sales.Orders` satırını okur. Mini kümesi seçildi, çünkü gerçek şema dbo'da
çıplak adlarla duruyor - yani burada sınanan hiçbir şey onun üzerinden sınanamazdı.
"""

from pathlib import Path

from nl2sql.agent import modes, tools
from nl2sql.cli.main import _search_notes
from nl2sql.datasets import load_dataset
from nl2sql.graph.graph import build_graph, join_text
from nl2sql.graph.profile import load_profile
from nl2sql.index.docs import build_documents
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import build_search
from nl2sql.index.text import fold, tokens
from nl2sql.schema_map import doc

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
DATASET = load_dataset("mini", root=FIXTURE_ROOT)
SCHEMA = DATASET.schema()
RULES = DATASET.rules()
DOCS = build_documents(SCHEMA, RULES)
SEARCH = build_search(SCHEMA, RULES, FakeEmbedder())
GRAPH = build_graph(SCHEMA, load_profile(DATASET.profile_path))


def context(schema: dict = SCHEMA, graph=GRAPH) -> modes.ToolContext:
    return modes.ToolContext(
        executor=None, schema=schema, rules=RULES, search=SEARCH, graph=graph, mode="rag"
    )


def rag(name: str, args: dict) -> str:
    return tools.dispatch(name, args, context())


# ------------------------------------------------------------------ indeks dokümanları

# ASSUMPTION: docs.py'nin kendisi değişmedi - id zaten tablo adının tamamı, token() noktayı ayraç
# saydığı için metnin tokenları şema ve tablo kısmını ayrı ayrı taşıyor; aşağıdaki ikisi bu yüzden
# değişikliğin değil, R4-8'in bu iki yere dokunmak zorunda olmadığının testi.


def test_table_doc_ids_are_the_full_names():
    assert [item.id for item in DOCS if item.collection == "tables"] == [
        f"table:{table['name']}" for table in SCHEMA["tables"]
    ]


def test_doc_text_tokens_carry_the_schema_and_the_table_part():
    for table in SCHEMA["tables"]:
        found = set(tokens(next(i.text for i in DOCS if i.id == f"table:{table['name']}")))
        assert all(fold(part) in found for part in doc.split_name(table["name"])), table["name"]


def test_search_finds_the_order_table_by_its_full_name():
    hits = SEARCH.search("sipariş")
    assert "table:Sales.Orders" in [hit.doc_id for hit in hits]
    assert "Sales.Orders" in [hit.title for hit in hits]


# ------------------------------------------------------------------ join graphı


def test_the_graph_edges_name_both_tables_in_full():
    assert {(edge.left_table, edge.right_table, edge.source) for edge in GRAPH.edges} == {
        ("Sales.Orders", "Sales.Customers", "fk"),
        ("Sales.OrderLines", "Sales.Orders", "fk"),
        ("Sales.OrderLines", "Warehouse.StockItems", "fk"),
    }


def test_the_path_between_the_ends_runs_through_the_order_header_and_lines():
    path = GRAPH.find_join_path(["Sales.Customers", "Warehouse.StockItems"])
    assert path.tables == [
        "Sales.Customers",
        "Warehouse.StockItems",
        "Sales.OrderLines",
        "Sales.Orders",
    ]
    assert path.low_confidence == []
    assert all(edge.source == "fk" for edge in path.joins)
    assert "Sales.OrderLines.OrderID = Sales.Orders.OrderID" in join_text(path)


# ------------------------------------------------------------------ araçların cevapları


def test_get_table_details_accepts_a_unique_bare_name_and_answers_with_the_full_one():
    answer = rag("get_table_details", {"tables": ["OrderLines"]})
    assert answer.startswith("Sales.OrderLines — ")
    assert "-> Sales.Orders.OrderID" in answer


def test_find_join_path_answers_with_full_names_from_bare_ones():
    assert rag("find_join_path", {"tables": ["Customers", "StockItems"]}) == join_text(
        GRAPH.find_join_path(["Sales.Customers", "Warehouse.StockItems"])
    )


def test_a_bare_name_the_schema_does_not_have_is_still_named_as_asked():
    assert rag("find_join_path", {"tables": ["Yok"]}) == f"{tools.ERROR_PREFIX}: Bilinmeyen tablo: Yok"


def test_an_ambiguous_bare_name_asks_for_the_schema():
    schema = {
        "tables": [
            {"name": "Sales.Orders", "columns": [{"name": "OrderID", "fk": "Purchasing.Orders.OrderID"}]},
            {"name": "Purchasing.Orders", "columns": [{"name": "OrderID"}]},
        ]
    }
    answer = tools.dispatch(
        "find_join_path", {"tables": ["Orders", "Sales.Orders"]}, context(schema, build_graph(schema, []))
    )
    assert answer == f"{tools.ERROR_PREFIX}: Belirsiz tablo adı: Orders (Sales.Orders, Purchasing.Orders); şemasıyla yazın."


def test_search_schema_answers_with_full_names():
    answer = rag("search_schema", {"query": "sipariş"})
    assert "Sales.Orders — " in answer and "Warehouse.StockItems — " in answer


# ------------------------------------------------------------------ CLI adım notları


def test_the_ask_step_note_lists_qualified_names():
    note = _search_notes("search_schema", rag("search_schema", {"query": "sipariş"}))[0]
    assert note.startswith("→ ") and "Sales.Orders" in note and "Sales.OrderLines" in note


def test_the_ask_step_note_counts_qualified_detail_heads():
    answer = rag("get_table_details", {"tables": ["Orders", "StockItems"]})
    assert _search_notes("get_table_details", answer) == ["→ 2 tablo"]
