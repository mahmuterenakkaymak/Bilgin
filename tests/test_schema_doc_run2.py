# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R2-2/R2-5: kind and keywords stay off the model's screen; the Run 2 text forms and the token estimate."""

import json

import pytest

from bilgin import config
from bilgin.schema_map import doc


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


def load_one(tmp_path, table: dict) -> dict:
    path = tmp_path / "schema.json"
    path.write_text(json.dumps({"tables": [table]}), encoding="utf-8")
    return doc.load_schema(path)["tables"][0]


# ----------------------------------------------------------------- loader


def test_load_schema_defaults_kind_and_keywords(tmp_path):
    table = load_one(tmp_path, {"name": "TBLX", "columns": [{"name": "A", "type": "INT"}]})
    assert table["kind"] == "data"
    assert table["keywords"] == []


def test_load_schema_keeps_explicit_kind_and_keywords(tmp_path):
    table = load_one(
        tmp_path,
        {
            "name": "TBLX",
            "kind": "distractor",
            "keywords": ["fatura", "taslak"],
            "columns": [{"name": "A", "type": "INT"}],
        },
    )
    assert table["kind"] == "distractor"
    assert table["keywords"] == ["fatura", "taslak"]


# ----------------------------------------------------------------- full_text


def test_full_text_carries_every_table_in_detail(schema):
    text = doc.full_text(schema)
    assert text.startswith("TBLSTGRUP — ")
    assert "STHAR_GCMIK" in text
    assert "G=giriş" in text
    for table in schema["tables"]:
        assert f"{table['name']} — {table['description']}" in text


def test_full_text_separates_tables_with_a_blank_line(schema):
    lines = doc.full_text(schema).splitlines()
    names = {table["name"] for table in schema["tables"]}
    headers = [i for i, line in enumerate(lines) if line.split(" — ")[0] in names]
    assert len(headers) == len(schema["tables"])
    assert headers[0] == 0
    assert all(lines[i - 1] == "" for i in headers[1:])


# ----------------------------------------------------------------- name_list


def test_name_list_one_line_per_module_in_schema_order(schema):
    modules = []
    for table in schema["tables"]:
        if table["module"] not in modules:
            modules.append(table["module"])
    lines = doc.name_list(schema).splitlines()
    assert [line.split(":")[0] for line in lines] == modules
    for module, line in zip(modules, lines):
        names = [table["name"] for table in schema["tables"] if table["module"] == module]
        assert line == f"{module}: {', '.join(names)}"


def test_name_list_shows_no_descriptions_or_columns(schema):
    text = doc.name_list(schema)
    assert "STHAR_GCMIK" not in text
    assert "->" not in text
    assert schema["tables"][0]["description"] not in text


# ----------------------------------------------------------------- token estimate


def test_estimate_tokens_rounds_up():
    n = config.CHARS_PER_TOKEN
    assert doc.estimate_tokens("") == 0
    assert doc.estimate_tokens("a" * (n - 1)) == 1
    assert doc.estimate_tokens("a" * n) == 1
    assert doc.estimate_tokens("a" * (n + 1)) == 2


def test_full_detail_costs_more_tokens_than_the_compact_list(schema):
    assert doc.estimate_tokens(doc.full_text(schema)) > doc.estimate_tokens(doc.compact_text(schema))


# ----------------------------------------------------------------- bookkeeping fields stay hidden


def test_model_texts_never_show_kind_or_keywords():
    schema = doc.load_schema()
    for table in schema["tables"]:
        table["kind"] = "distractor"
        table["keywords"] = ["cirokelimesi"]
    for text in (doc.compact_text(schema), doc.table_detail(schema, ["TBLSTHAR"]), doc.full_text(schema)):
        assert "kind" not in text
        assert "keywords" not in text
        assert "distractor" not in text
        assert "cirokelimesi" not in text
