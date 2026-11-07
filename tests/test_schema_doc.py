# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

import inspect
import json
import re

import pytest

from nl2sql import config
from nl2sql.schema_map import doc

BRIEF_TABLES = {
    "STOK_GRUP",
    "STOK_KART",
    "DEPO",
    "SATIS_TEMSILCI",
    "HESAP_KART",
    "FATURA",
    "STOK_HAREKET",
    "HESAP_HAREKET",
    "SIPARIS",
    "SIPARIS_SATIR",
}

# PLAN Decision 4: the coded columns generator, schema doc and golden SQL must agree on.
DECISION4_CODES = {
    ("HESAP_KART", "HESAP_TIP"): {"A", "S", "H"},
    ("FATURA", "FTIRSIP"): {"1", "2", "3"},
    ("FATURA", "IPTAL"): {"E", "H"},
    ("STOK_HAREKET", "HAREKET_YONU"): {"G", "C"},
    ("STOK_HAREKET", "HAREKET_TURU"): {"S", "A", "I", "T", "D"},
    ("HESAP_HAREKET", "BA"): {"B", "A"},
}

TYPE_RE = re.compile(r"^(INT|DATE|VARCHAR\(\d+\)|NVARCHAR\(\d+\)|DECIMAL\(\d+,\d+\)|REAL)$")
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
FK_RE = re.compile(r"^[A-Z][A-Z0-9_]*\.[A-Z][A-Z0-9_]*$")


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def columns_by_table(schema):
    return {table["name"]: {c["name"] for c in table["columns"]} for table in schema["tables"]}


def table_map(schema):
    return {table["name"]: table for table in schema["tables"]}


def column(schema, table_name, column_name):
    for table in schema["tables"]:
        if table["name"] == table_name:
            for column_ in table["columns"]:
                if column_["name"] == column_name:
                    return column_
    raise AssertionError(f"{table_name}.{column_name} yok")


# ----------------------------------------------------------------- shape


# ----------------------------------------------------------------- foreign keys


# ----------------------------------------------------------------- coded values


def test_every_coded_column_documents_every_value(schema):
    for table in schema["tables"]:
        for column_ in table["columns"]:
            if not column_["values"]:
                continue
            assert len(column_["values"]) >= 2, column_["name"]
            for code, meaning in column_["values"].items():
                assert code.strip() and meaning.strip(), column_["name"]
                assert not meaning.startswith(code), column_["name"]


# ----------------------------------------------------------------- trap columns


# ----------------------------------------------------------------- allowlist


# ----------------------------------------------------------------- compact text


def test_compact_text_one_line_per_table(schema):
    text = doc.compact_text(schema)
    lines = text.splitlines()
    assert len(lines) == len(schema["tables"])
    for table, line in zip(schema["tables"], lines):
        assert line.startswith(table["name"] + " ")
        assert table["description"] in line
        assert f"[{table['module']}]" in line


def test_compact_text_has_no_column_names(schema):
    text = doc.compact_text(schema)
    assert "HAREKET_MIKTAR" not in text
    assert "->" not in text


# ----------------------------------------------------------------- table detail


def test_table_detail_never_prints_none(schema):
    text = doc.table_detail(schema, sorted(BRIEF_TABLES))
    assert "None" not in text
    assert "-> ," not in text


# ----------------------------------------------------------------- loader


def test_load_schema_path_defaults_to_config():
    assert inspect.signature(doc.load_schema).parameters["path"].default == config.SCHEMA_PATH


def test_load_schema_fills_optional_fields(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text(
        json.dumps({"tables": [{"name": "TABLO_X", "columns": [{"name": "A", "type": "INT"}]}]}),
        encoding="utf-8",
    )
    table = doc.load_schema(path)["tables"][0]
    assert table["description"] == "" and table["module"] == ""
    column_ = table["columns"][0]
    assert (column_["fk"], column_["values"], column_["nullable"], column_["description"]) == (
        None,
        {},
        True,
        "",
    )


def test_load_schema_keeps_explicit_values(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text(
        json.dumps(
            {
                "tables": [
                    {
                        "name": "TABLO_X",
                        "description": "x",
                        "module": "m",
                        "columns": [
                            {"name": "A", "type": "INT", "description": "d", "fk": "TABLO_Y.B", "values": {"E": "e"}, "nullable": False}
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    column_ = doc.load_schema(path)["tables"][0]["columns"][0]
    assert column_["fk"] == "TABLO_Y.B" and column_["nullable"] is False and column_["values"] == {"E": "e"}


