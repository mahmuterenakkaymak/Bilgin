"""`rag` modunun arama araçlarının modele döndürdüğü metin (T59).

İddia retrieval'ın isabeti değil — o test_search.py'de — iddia cevapların biçimi: arama bir tablo
bulduysa model kolon adlarını da aynı satırda görür, bulamadıysa boş durumu okur, join yolu
eşitlikleri ve güveni söyler, uzun bir cevap ise modele girmeden kırpılır. İndeks ve graph gerçek
(FakeEmbedder ile kurulmuş arama, şemadan örülmüş graph), çünkü uydurma bir cevap metni üzerinden
biçim sınanmaz.
"""

from nl2sql import config
from nl2sql.agent import modes, tools
from nl2sql.graph.graph import build_graph, join_text
from nl2sql.graph.profile import load_profile
from nl2sql.index.embed import FakeEmbedder
from nl2sql.index.search import build_search
from nl2sql.schema_map import doc
from nl2sql.schema_map.rules import load_rules, rule_text

SCHEMA = doc.load_schema()
RULES = load_rules()
SEARCH = build_search(SCHEMA, RULES, FakeEmbedder())
GRAPH = build_graph(SCHEMA, load_profile())
TABLES = {table["name"]: table for table in SCHEMA["tables"]}


def context(mode: str) -> modes.ToolContext:
    return modes.ToolContext(
        executor=None, schema=SCHEMA, rules=RULES, search=SEARCH, graph=GRAPH, mode=mode
    )


def rag(name: str, args: dict, mode: str = "rag") -> str:
    return tools.dispatch(name, args, context(mode))


# ------------------------------------------------------------------ search_schema


def test_search_schema_says_when_nothing_matches():
    assert rag("search_schema", {"query": ""}) == "Eşleşen tablo yok."
    assert rag("search_schema", {}) == "Eşleşen tablo yok."


# ------------------------------------------------------------------ get_table_details


def test_get_table_details_names_a_table_the_schema_does_not_have():
    assert "Bilinmeyen tablo: OLMAYAN_TABLO" in rag("get_table_details", {"tables": ["OLMAYAN_TABLO"]})


def test_a_long_answer_is_cut_before_the_model_sees_it():
    full = doc.full_text(SCHEMA)
    answer = rag("get_table_details", {"tables": list(TABLES)})
    assert len(full) > config.TOOL_RESULT_MAX_CHARS
    assert answer == full[: config.TOOL_RESULT_MAX_CHARS] + (
        f"… (kırpıldı: {len(full) - config.TOOL_RESULT_MAX_CHARS} karakter)"
    )


def test_cap_text_only_touches_what_is_too_long():
    assert tools.cap_text("kısa cevap", 100) == "kısa cevap"
    assert tools.cap_text("abcdefghij", 4) == "abcd… (kırpıldı: 6 karakter)"


# ------------------------------------------------------------------ search_rules


def test_search_rules_says_when_nothing_matches():
    assert rag("search_rules", {"query": ""}) == "Eşleşen kural yok."


# ------------------------------------------------------------------ find_join_path


# ------------------------------------------------------------------ mode gating


def test_a_tool_outside_the_mode_is_answered_with_the_mode_tools():
    answer = rag("get_schema", {"tables": ["STOK_HAREKET"]})
    assert answer.startswith(f"{tools.UNKNOWN_TOOL_PREFIX}: get_schema. ")
    names = ", ".join(tool["function"]["name"] for tool in modes.get_mode("rag").tools)
    assert answer.endswith(f"Kullanabileceklerin: {names}.")
    assert "get_schema, run_sql, submit_sql" not in answer


def test_the_rag_tools_are_not_available_in_full_mode():
    answer = rag("search_schema", {"query": "stok"}, mode="full")
    assert answer.startswith(f"{tools.UNKNOWN_TOOL_PREFIX}: search_schema. ")
    assert "get_schema, run_sql, submit_sql" in answer


def test_a_tool_called_without_its_argument_answers_instead_of_crashing():
    assert rag("get_table_details", {}).startswith("Tablo adı verilmedi.")
    assert rag("find_join_path", {}) == "Tek tablo; join gerekmiyor."
