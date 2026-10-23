"""T67: TBLSTHAR_ARSIV açıklaması arşivin yalnız 2025 içerdiğini doğru söylüyor."""

import re

import pytest

from nl2sql.schema_map import doc

ARSIV = "TBLSTHAR_ARSIV"


@pytest.fixture(scope="module")
def description():
    schema = doc.load_schema()
    return {t["name"]: t for t in schema["tables"]}[ARSIV]["description"]


def test_the_description_names_2025(description):
    assert "2025" in description


def test_the_description_never_puts_2026_movements_in_the_archive(description):
    assert "2026 hareketleri burada" not in description


def test_the_description_says_2026_is_not_in_the_archive(description):
    clauses = [clause for clause in re.split(r"[.;:,]", description) if "2026" in clause]
    assert any("yoktur" in clause and "burada" not in clause for clause in clauses), description
