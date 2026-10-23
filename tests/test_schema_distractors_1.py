"""R2-4 part 1: the Muhasebe/Banka/Çek-Senet tables that exist only to be walked past.

A distractor has to look like the real thing - Netsis-style name, the frequent columns, a
foreign key into the real world - otherwise it measures nothing. These tests hold that shape;
they do not check which tables the model picks (that is the eval's job).
"""

import re

import pytest

from nl2sql.schema_map import doc

MODULES = {"Muhasebe", "Banka", "Çek/Senet"}
MIN_DISTRACTORS = 22

# The names PLAN R2-4 lists for these three modules.
NAMED = {"TBLMUHHESAP", "TBLMUHDETAY", "TBLBANKA", "TBLBNKHAR", "TBLCEKSEN", "TBLCEKHAR"}

# R2-4: the frequent columns, repeated across the distractors so they read as plausible.
FREQUENT = {"CARI_KOD", "CARI_KODU", "STOK_KODU", "TARIH", "TUTAR", "ACIKLAMA", "FISNO"}

RUN1_TABLES = {
    "TBLSTGRUP",
    "TBLSTSABIT",
    "TBLDEPO",
    "TBLPLASIYER",
    "TBLCASABIT",
    "TBLFATUIRS",
    "TBLSTHAR",
    "TBLCAHAR",
    "TBLSIPAMAS",
    "TBLSIPATRA",
}

TYPE_RE = re.compile(r"^(INT|DATE|VARCHAR\(\d+\)|NVARCHAR\(\d+\)|DECIMAL\(\d+,\d+\)|REAL)$")
NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def distractors(schema):
    return [
        table
        for table in schema["tables"]
        if table["kind"] == "distractor" and table["module"] in MODULES
    ]


def test_at_least_22_distractors_in_the_three_modules(distractors):
    assert len(distractors) >= MIN_DISTRACTORS
    assert {table["module"] for table in distractors} == MODULES
    assert NAMED <= {table["name"] for table in distractors}


def test_distractor_names_are_unique_and_not_real_tables(schema, distractors):
    real = {table["name"] for table in schema["tables"] if table["kind"] != "distractor"}
    names = [table["name"] for table in distractors]
    assert len(set(names)) == len(names)
    assert not set(names) & real
    for name in names:
        assert NAME_RE.match(name), name


def test_every_distractor_is_documented(distractors):
    for table in distractors:
        assert table["kind"] == "distractor", table["name"]
        assert table["module"] in MODULES, table["name"]
        assert table["description"].strip(), table["name"]


def test_columns_are_four_to_ten_and_typed(distractors):
    for table in distractors:
        names = [c["name"] for c in table["columns"]]
        assert 4 <= len(names) <= 10, (table["name"], len(names))
        assert len(set(names)) == len(names), table["name"]
        for column_ in table["columns"]:
            assert NAME_RE.match(column_["name"]), (table["name"], column_["name"])
            assert TYPE_RE.match(column_["type"]), (table["name"], column_["type"])
            assert column_["description"].strip(), (table["name"], column_["name"])
            assert isinstance(column_["nullable"], bool), column_["name"]


def test_every_distractor_fk_resolves(schema, distractors):
    index = {(table["name"], c["name"]) for table in schema["tables"] for c in table["columns"]}
    for table in distractors:
        for column_ in table["columns"]:
            if column_["fk"] is None:
                continue
            target = tuple(column_["fk"].split("."))
            assert target in index, f"{table['name']}.{column_['name']} -> {column_['fk']} yok"


def test_distractors_reach_the_run1_tables(distractors):
    # A distractor nobody can join to the real world is never picked, so it measures nothing.
    targets = {
        column_["fk"].split(".")[0]
        for table in distractors
        for column_ in table["columns"]
        if column_["fk"]
    }
    assert targets & RUN1_TABLES >= {"TBLCASABIT", "TBLSTSABIT", "TBLFATUIRS"}


def test_frequent_columns_are_widespread(distractors):
    used = {column_["name"] for table in distractors for column_ in table["columns"]}
    assert FREQUENT <= used, FREQUENT - used
    shared = sum(1 for table in distractors if FREQUENT & {c["name"] for c in table["columns"]})
    assert shared >= 3 * len(distractors) // 4
