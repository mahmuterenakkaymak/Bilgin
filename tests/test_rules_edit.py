# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R5-16: kural düzenleme - doğrulama, normalize, atomik kayıt.

Testler commit'lenmiş datasets/wwi/rules.json'un bir tmp kopyası üzerinde çalışır; asıl
dosyaya hiçbir test yazmaz (sha256 önce == sonra).
"""

import hashlib
import shutil
from pathlib import Path

import pytest

from nl2sql import config
from nl2sql.index.store import content_hash
from nl2sql.schema_map import doc
from nl2sql.schema_map.rules import load_rules
from nl2sql.schema_map.rules_edit import normalize_rule, save_rules, validate_rule

SRC = config.RULES_PATH
SCHEMA = doc.load_schema()


@pytest.fixture
def rules_path(tmp_path):
    path = tmp_path / "rules.json"
    shutil.copy(SRC, path)
    return path


def _rule(**over):
    rule = {
        "id": "yeni_kural",
        "term": "Yeni kural",
        "synonyms": ["yeni"],
        "definition": "Bir tanım.",
        "sql_hint": "SELECT 1",
        "tables": ["STOK_HAREKET"],
        "markers": [r"SELECT\s+1"],
    }
    rule.update(over)
    return rule


INVALID = [
    (_rule(id="Kötü Kimlik"), "id", "küçük harf"),
    (_rule(id=""), "id", "küçük harf"),
    (_rule(term="   "), "term", "boş olamaz"),
    (_rule(definition=""), "definition", "boş olamaz"),
    (_rule(synonyms="metin"), "synonyms", "liste"),
    (_rule(tables="STOK_HAREKET"), "tables", "liste"),
    (_rule(markers=[1]), "markers", "liste"),
    (_rule(tables=["TBOYLEBILE"]), "tables", "TBOYLEBILE"),
    (_rule(markers=["("]), "markers", "derlenmiyor"),
]


@pytest.mark.parametrize("rule,field,needle", INVALID)
def test_invalid_rule_reports_field_and_message(rule, field, needle):
    errors = validate_rule(rule, SCHEMA, [])
    hit = [error for error in errors if error["field"] == field]
    assert hit, f"{field} için hata yok: {errors}"
    assert needle in hit[0]["message"]


def test_duplicate_id_rejected(rules_path):
    existing = load_rules(rules_path)
    errors = validate_rule(dict(existing[0]), SCHEMA, existing)
    assert any(e["field"] == "id" and "zaten var" in e["message"] for e in errors)


def test_editing_keeps_the_id(rules_path):
    existing = load_rules(rules_path)
    editing = dict(existing[0], term="Değişmiş terim")
    assert validate_rule(editing, SCHEMA, existing, editing_id=existing[0]["id"]) == []


def test_normalize_strips_and_defaults():
    rule = normalize_rule({
        "id": "  k  ",
        "term": " T ",
        "definition": " D ",
        "synonyms": [" a ", "", "  ", "b"],
    })
    assert rule == {
        "id": "k",
        "term": "T",
        "definition": "D",
        "sql_hint": "",
        "synonyms": ["a", "b"],
        "tables": [],
        "markers": [],
    }


def test_save_load_round_trip(rules_path):
    loaded = load_rules(rules_path)
    save_rules(loaded, rules_path)
    assert load_rules(rules_path) == loaded


def test_content_hash_changes_after_a_save(rules_path):
    before = content_hash({}, load_rules(rules_path))
    save_rules(load_rules(rules_path) + [normalize_rule(_rule())], rules_path)
    assert content_hash({}, load_rules(rules_path)) != before


def test_committed_rules_untouched(rules_path):
    def digest() -> str:
        return hashlib.sha256(Path(SRC).read_bytes()).hexdigest()

    before = digest()
    save_rules(load_rules(rules_path) + [normalize_rule(_rule())], rules_path)
    assert digest() == before
