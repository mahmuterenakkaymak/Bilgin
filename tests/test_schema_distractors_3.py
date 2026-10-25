"""R2-4 part 3: the last three modules and the near-duplicates that shadow the real tables.

The near-duplicate is the sharp end of R2-4: it carries the real table's columns, so a model
that stops reading at the column names picks it and gets a different number. These tests hold
the shadowing shape (superset of the real columns) and the schema-wide totals; which table the
model picks is the eval's job.
"""

import pytest

from nl2sql.schema_map import doc

NEW_MODULES = {"Sabit Kıymet", "Kalite", "Lojistik"}

# PLAN R2-4: the schema's size window and the distractor floor the ~81-table estimate assumes.
MIN_TABLES, MAX_TABLES = 75, 90
MIN_DISTRACTORS = 60

# Near-duplicate -> the real table it shadows. The shadow must keep every real column.
NEAR_DUPLICATES = {
    "STOK_HAREKET_LOG": "STOK_HAREKET",
    "FATURA_TASLAK": "FATURA",
    "HESAP_KART_YEDEK": "HESAP_KART",
    "STOK_KART_ESKI": "STOK_KART",
    "SIPARIS_SATIR_TMP": "SIPARIS_SATIR",
    "SIPARIS_TASLAK": "SIPARIS",
    "HESAP_HAREKET_LOG": "HESAP_HAREKET",
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


def test_names_are_unique_across_the_whole_schema(schema):
    names = [table["name"] for table in schema["tables"]]
    assert len(set(names)) == len(names)


def test_every_distractor_fk_resolves(schema, distractors):
    index = {(table["name"], c["name"]) for table in schema["tables"] for c in table["columns"]}
    for table in distractors:
        for column_ in table["columns"]:
            if column_["fk"] is None:
                continue
            target = tuple(column_["fk"].split("."))
            assert target in index, f"{table['name']}.{column_['name']} -> {column_['fk']} yok"
