# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R2-4 part 3: the last three modules and the near-duplicates that shadow the real tables.

The near-duplicate is the sharp end of R2-4: it carries the real table's columns, so a model
that stops reading at the column names picks it and gets a different number. These tests hold
the shadowing shape (superset of the real columns) and the schema-wide totals; which table the
model picks is the eval's job.
"""

import pytest

from bilgin.schema_map import doc

NEW_MODULES = {"Sabit Kıymet", "Kalite", "Lojistik"}

# PLAN R2-4: the schema's size window and the distractor floor the ~81-table estimate assumes.
MIN_TABLES, MAX_TABLES = 75, 90
MIN_DISTRACTORS = 60

# Near-duplicate -> the real table it shadows. The shadow must keep every real column.
NEAR_DUPLICATES = {
    "TBLSTHAR_LOG": "TBLSTHAR",
    "TBLFATUIRS_TASLAK": "TBLFATUIRS",
    "TBLCASABIT_YEDEK": "TBLCASABIT",
    "TBLSTSABIT_ESKI": "TBLSTSABIT",
    "TBLSIPATRA_TMP": "TBLSIPATRA",
    "TBLSIPAMAS_TASLAK": "TBLSIPAMAS",
    "TBLCAHAR_LOG": "TBLCAHAR",
}


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def tables_by_name(schema):
    return {table["name"]: table for table in schema["tables"]}


@pytest.fixture(scope="module")
def distractors(schema):
    return [table for table in schema["tables"] if table["kind"] == "distractor"]


def test_schema_is_in_the_75_to_90_range_with_60_distractors(schema, distractors):
    total = len(schema["tables"])
    assert MIN_TABLES <= total <= MAX_TABLES, total
    assert len(distractors) >= MIN_DISTRACTORS, len(distractors)


def test_the_last_three_modules_are_present(distractors):
    modules = {table["module"] for table in distractors}
    assert NEW_MODULES <= modules, NEW_MODULES - modules


def test_names_are_unique_across_the_whole_schema(schema):
    names = [table["name"] for table in schema["tables"]]
    assert len(set(names)) == len(names)


def test_near_duplicates_shadow_their_real_tables(tables_by_name):
    for shadow_name, real_name in NEAR_DUPLICATES.items():
        shadow = tables_by_name[shadow_name]
        real = tables_by_name[real_name]
        assert shadow["kind"] == "distractor", shadow_name
        extra = {c["name"] for c in shadow["columns"]} - {c["name"] for c in real["columns"]}
        assert extra, (shadow_name, "gölge tablonun kendi kolonu yok")
        assert {c["name"] for c in real["columns"]} <= {c["name"] for c in shadow["columns"]}, shadow_name


def test_sthar_log_adds_only_log_tarih_and_islem(tables_by_name):
    shadow = tables_by_name["TBLSTHAR_LOG"]
    real = tables_by_name["TBLSTHAR"]
    extra = {c["name"] for c in shadow["columns"]} - {c["name"] for c in real["columns"]}
    assert extra == {"LOG_TARIH", "ISLEM"}, extra


def test_every_distractor_fk_resolves(schema, distractors):
    index = {(table["name"], c["name"]) for table in schema["tables"] for c in table["columns"]}
    for table in distractors:
        for column_ in table["columns"]:
            if column_["fk"] is None:
                continue
            target = tuple(column_["fk"].split("."))
            assert target in index, f"{table['name']}.{column_['name']} -> {column_['fk']} yok"
