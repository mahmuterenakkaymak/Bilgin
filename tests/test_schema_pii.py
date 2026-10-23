"""T94: şema belgesindeki PII işaretleri (PLAN R3-6/R3-7).

`pii` yalnızca şema belgesinde durur: maskeleme şemadan yapılır, modelin okuduğu metne ise
hiç düşmez. Bu yüzden burada ölçülen iki şey var - işaretlerin geçerli sınıf adları taşıması
ve şema metrinin işaretlerden bağımsız olması.
"""

import copy

import pytest

from nl2sql.policy import pii
from nl2sql.schema_map import doc

# PLAN R3-7: PII işaretini taşıyan sütunların tam listesi; listelenmeyen hiçbir sütun işaretli değildir.
ANNOTATED = {
    ("TBLPERSONEL", "AD_SOYAD"): "person_name",
    ("TBLPERSONEL", "TELEFON"): "phone",
    ("TBLPERSONEL", "TCKN"): "tckn",
    ("TBLPERSONEL", "VKN"): "vkn",
    ("TBLPERSONEL", "IBAN"): "iban",
    ("TBLPERSONEL", "E_POSTA"): "email",
    ("TBLPERSONEL", "ADRES"): "address",
    ("TBLCARISUBE", "ADRES"): "address",
    ("TBLCARISUBE", "TELEFON"): "phone",
    ("TBLCARISUBE", "E_POSTA"): "email",
    ("TBLMAAS", "BRUT_TUTAR"): "salary",
    ("TBLMAAS", "KESINTI_TUTAR"): "salary",
    ("TBLMAAS", "NET_TUTAR"): "salary",
    ("TBLMAASDETAY", "TUTAR"): "salary",
}

# tckn/vkn/iban şemada sütun adı ve açıklama olarak da geçer ("TR ile başlayan IBAN");
# öbür sınıf adları Türkçe şema metrinde hiçbir biçimde geçmez.
PLAIN_CLASSES = ("phone", "email", "address", "salary", "person_name")

PII_TABLES = sorted({table for table, _ in ANNOTATED})


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


def annotated(schema: dict) -> dict:
    return {
        (table["name"], column["name"]): column["pii"]
        for table in schema["tables"]
        for column in table["columns"]
        if column["pii"]
    }


def without_pii(schema: dict) -> dict:
    clean = copy.deepcopy(schema)
    for table in clean["tables"]:
        for column in table["columns"]:
            column.pop("pii")
    return clean


# ----------------------------------------------------------------- annotations


def test_every_pii_value_is_a_known_class(schema):
    for table in schema["tables"]:
        for column in table["columns"]:
            assert column["pii"] is None or column["pii"] in pii.CLASSES, f"{table['name']}.{column['name']}"


def test_annotated_columns_are_exactly_the_planned_ones(schema):
    assert annotated(schema) == ANNOTATED


def test_load_schema_defaults_pii_to_none(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text(
        '{"tables": [{"name": "TBLT", "columns": [{"name": "KOLON", "type": "INT"}]}]}', encoding="utf-8"
    )
    assert doc.load_schema(path)["tables"][0]["columns"][0]["pii"] is None


# ----------------------------------------------------------------- model-facing text


def test_pii_never_changes_the_model_text(schema):
    """İşaretin varlığı ile yokluğu model için aynı metni üretir; sınıf adları metne sızmaz."""
    clean = without_pii(schema)
    assert doc.compact_text(schema) == doc.compact_text(clean)
    assert doc.full_text(schema) == doc.full_text(clean)
    assert doc.table_detail(schema, PII_TABLES) == doc.table_detail(clean, PII_TABLES)


def test_class_names_are_absent_from_the_model_text(schema):
    compact = doc.compact_text(schema).lower()
    full = doc.full_text(schema).lower()
    for cls in pii.CLASSES:
        assert cls not in compact
    for cls in PLAIN_CLASSES:
        assert cls not in full
    assert "pii" not in full
