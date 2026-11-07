# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Mod başına araç listesi ve sistem istemi (PLAN R2-5, R2-6).

İstem gerçek şema ve gerçek kurallarla kuruluyor: bu modülün ölçtüğü şey bağlamın boyutu ve
içeriği, yani uydurma bir şemayla sınanırsa hiçbir şeyi kanıtlamaz. Beklenti şu - `full` her
kolonu sayar, `rag` hiçbirini saymaz ama hangi araçla öğrenileceğini söyler, `full_rules` bir
de her kuralı olduğu gibi taşır.
"""

import json
import re

import pytest

from nl2sql import config
from nl2sql.agent import modes, prompt
from nl2sql.schema_map import doc
from nl2sql.schema_map.rules import load_rules

RAG_TOOLS = ["search_schema", "get_table_details", "find_join_path", "search_rules", "sample_values"]
SQL_TOOLS = ["run_sql", "submit_sql"]


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def rules():
    return load_rules()


def context(mode: str, schema: dict, rules: list | None = None) -> modes.ToolContext:
    return modes.ToolContext(executor=None, schema=schema, rules=rules or [], mode=mode)


def system_text(mode: str, schema: dict, rules: list | None = None) -> str:
    return modes.get_mode(mode).system_prompt(context(mode, schema, rules))


def column_names(schema: dict) -> list[str]:
    return [column["name"] for table in schema["tables"] for column in table["columns"]]


# ------------------------------------------------------------------ tool lists


def test_the_modes_are_the_configured_ones():
    assert tuple(modes.MODES) == tuple(config.MODES)


def test_the_full_modes_keep_the_run_one_tools():
    for name in ("full", "full_rules"):
        names = [tool["function"]["name"] for tool in modes.get_mode(name).tools]
        assert names == ["get_schema", *SQL_TOOLS]


def test_the_rag_mode_trades_get_schema_for_the_lookup_tools():
    names = [tool["function"]["name"] for tool in modes.get_mode("rag").tools]
    assert names == [*RAG_TOOLS, *SQL_TOOLS]
    assert "get_schema" not in names, "rag'da şemanın tamamı zaten istemde değil; arama araçları var"


def test_every_tool_of_every_mode_is_declared_in_openai_form():
    for mode in modes.MODES.values():
        for tool in mode.tools:
            assert tool["type"] == "function"
            function = tool["function"]
            assert function["description"].strip(), f"{mode.name}/{function['name']} açıklamasız"
            assert function["parameters"]["type"] == "object"
            assert set(function["parameters"]["properties"])
    assert json.loads(json.dumps(modes.get_mode("rag").tools, ensure_ascii=False))[0]["function"]["name"] == (
        "search_schema"
    )


# ------------------------------------------------------------------ prompts


def test_the_full_prompt_holds_no_business_rules(schema, rules):
    assert "İŞ KURALLARI" not in system_text("full", schema, rules)


def test_the_full_rules_prompt_carries_every_rule(schema, rules):
    text = system_text("full_rules", schema, rules)
    assert "İŞ KURALLARI" in text
    for rule in rules:
        assert rule["term"] in text
        assert rule["definition"] in text


def test_the_rag_prompt_names_no_column(schema):
    text = system_text("rag", schema)
    assert "HAREKET_MIKTAR" not in text
    # Kelime kelime bakılıyor: IL gibi kısa bir kolon adı bir tablo adının içinde geçebilir,
    # ama kendi başına geçmemeli. Kural 2 tarih aralığını TARIH ile örnekliyor; o muaf.
    words = set(re.findall(r"\w+", text))
    allowed = prompt.system_prompt(config.AS_OF, "")
    for name in column_names(schema):
        if name not in allowed:
            assert name not in words, name


def test_the_rag_prompt_lists_tables_and_names_the_tools_it_wants_used(schema):
    text = system_text("rag", schema)
    assert doc.name_list(schema) in text
    for name in RAG_TOOLS:
        assert name in text


def test_the_rag_prompt_orders_a_join_path_before_a_three_table_join(schema, rules):
    assert "3 veya daha fazla tabloyu birleştirmeden ÖNCE find_join_path çağır" in system_text("rag", schema)
    for mode in ("full", "full_rules"):
        assert "3 veya daha fazla tabloyu birleştirmeden" not in system_text(mode, schema, rules)


def test_the_full_context_costs_much_more_than_rag(schema, rules):
    full = doc.estimate_tokens(system_text("full", schema, rules))
    rag = doc.estimate_tokens(system_text("rag", schema, rules))
    assert full > 5 * rag, f"full {full} token, rag {rag} token"


# ------------------------------------------------------------------ limits and lookup


def test_each_mode_has_its_own_tool_call_limit():
    for name in config.MODES:
        assert modes.get_mode(name).max_tool_calls == config.MAX_TOOL_CALLS_BY_MODE[name]
    assert modes.get_mode("rag").max_tool_calls > modes.get_mode("full").max_tool_calls


def test_an_unknown_mode_names_the_modes_that_exist():
    with pytest.raises(ValueError) as excinfo:
        modes.get_mode("hybrid")
    for name in config.MODES:
        assert name in str(excinfo.value)


def test_the_tool_context_defaults_to_the_run_one_shape():
    ctx = modes.ToolContext(executor=None, schema={"tables": []})
    assert ctx.rules == []
    assert ctx.search is None
    assert ctx.graph is None
    assert ctx.mode == "full"
