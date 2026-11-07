# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""`rag` modunun arama araçlarının modele döndürdüğü metin (T59).

İddia retrieval'ın isabeti değil — o test_search.py'de — iddia cevapların biçimi: arama bir tablo
bulduysa model kolon adlarını da aynı satırda görür, bulamadıysa boş durumu okur, join yolu
eşitlikleri ve güveni söyler, uzun bir cevap ise modele girmeden kırpılır. İndeks ve graph gerçek
(FakeEmbedder ile kurulmuş arama, şemadan örülmüş graph), çünkü uydurma bir cevap metni üzerinden
biçim sınanmaz.
"""

from bilgin import config
from bilgin.agent import modes, tools
from bilgin.graph.graph import build_graph, join_text
from bilgin.graph.profile import load_profile
from bilgin.index.embed import FakeEmbedder
from bilgin.index.search import build_search
from bilgin.schema_map import doc
from bilgin.schema_map.rules import load_rules, rule_text

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


def test_search_schema_answers_with_the_columns_of_every_hit():
    answer = rag("search_schema", {"query": "stok hareketleri satış iade"})
    lines = answer.splitlines()
    # R3-9: cevabın ilk SEARCH_K satırı vuruşların kendisi, arkası "(komşu)" işaretli komşular.
    hits, neighbours = lines[: config.SEARCH_K], lines[config.SEARCH_K :]
    assert len(hits) == config.SEARCH_K
    assert "TBLSTHAR" in answer
    for line in hits:
        assert " (komşu)" not in line
        name, _, tail = line.partition(" — ")
        header, _, columns = tail.rpartition(": ")
        table = TABLES[name]
        assert header.startswith(table["description"])
        assert header.endswith(f" [{table['module']}]")
        assert columns.split(", ") == [column["name"] for column in table["columns"]]
    for line in neighbours:
        assert line.endswith(" (komşu)")


def test_search_schema_says_when_nothing_matches():
    assert rag("search_schema", {"query": ""}) == "Eşleşen tablo yok."
    assert rag("search_schema", {}) == "Eşleşen tablo yok."


# ------------------------------------------------------------------ get_table_details


def test_get_table_details_is_the_schema_detail_of_the_asked_tables():
    answer = rag("get_table_details", {"tables": ["TBLSTHAR"]})
    assert answer == doc.table_detail(SCHEMA, ["TBLSTHAR"])
    assert "STHAR_GCMIK" in answer


def test_get_table_details_names_a_table_the_schema_does_not_have():
    assert "Bilinmeyen tablo: TBLYOK" in rag("get_table_details", {"tables": ["TBLYOK"]})


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


def test_search_rules_answers_with_rule_blocks():
    answer = rag("search_rules", {"query": "ağustos net ciro"})
    blocks = answer.split("\n\n")
    assert len(blocks) == config.RULES_K
    assert blocks[0] == rule_text(next(rule for rule in RULES if rule["id"] == "ciro"))
    assert all("  Tanım: " in block for block in blocks)


def test_search_rules_says_when_nothing_matches():
    assert rag("search_rules", {"query": ""}) == "Eşleşen kural yok."


# ------------------------------------------------------------------ find_join_path


def test_find_join_path_lists_the_join_conditions():
    assert rag("find_join_path", {"tables": ["TBLCARISUBE", "TBLCASABIT"]}) == (
        "TBLCARISUBE.CARI_KOD = TBLCASABIT.CARI_KOD (fk 1.0)"
    )


def test_find_join_path_warns_about_a_weak_edge():
    answer = rag("find_join_path", {"tables": ["TBLCARISUBE", "TBLGARANTI"]})
    assert answer == join_text(GRAPH.find_join_path(["TBLCARISUBE", "TBLGARANTI"]))
    assert answer.startswith(
        "TBLCARISUBE.CARI_KOD = TBLGARANTI.CARI_KOD (profile 0.6)\n⚠ düşük güven: "
    )


def test_find_join_path_names_the_table_that_stopped_it():
    assert rag("find_join_path", {"tables": ["TBLSTHAR", "TBLYOK"]}) == (
        f"{tools.ERROR_PREFIX}: Bilinmeyen tablo: TBLYOK"
    )


# ------------------------------------------------------------------ mode gating


def test_a_tool_outside_the_mode_is_answered_with_the_mode_tools():
    answer = rag("get_schema", {"tables": ["TBLSTHAR"]})
    assert answer.startswith(f"{tools.UNKNOWN_TOOL_PREFIX}: get_schema. ")
    names = ", ".join(tool["function"]["name"] for tool in modes.get_mode("rag").tools)
    assert answer.endswith(f"Kullanabileceklerin: {names}.")
    assert "get_schema, run_sql, submit_sql" not in answer


def test_the_rag_tools_are_not_available_in_full_mode():
    answer = rag("search_schema", {"query": "stok"}, mode="full")
    assert answer.startswith(f"{tools.UNKNOWN_TOOL_PREFIX}: search_schema. ")
    assert "get_schema, run_sql, submit_sql" in answer


def test_the_run_one_call_form_still_routes():
    assert "STHAR_GCMIK" in tools.dispatch("get_schema", {"tables": ["TBLSTHAR"]}, None, SCHEMA)


def test_a_tool_called_without_its_argument_answers_instead_of_crashing():
    assert rag("get_table_details", {}).startswith("Tablo adı verilmedi.")
    assert rag("find_join_path", {}) == "Tek tablo; join gerekmiyor."
