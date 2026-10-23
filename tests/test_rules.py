"""R2-11: bir kural ile onu iddia eden golden SQL aynı şeyi söylemek zorunda.

Kuralın işaretçileri (markers), o kuralı `rules` alanına yazan her golden SQL'de geçmeli. Böylece
kural metni ile sorgunun gerçek kalıbı iki ayrı dünyaya kopamıyor: metin "iadeler düşülmez" derken
SQL iadeyi düşürürse test kırmızıya döner.
"""

import json
import re

import pytest

from nl2sql.eval.runner import load_golden
from nl2sql.schema_map import doc, rules

RULES = rules.load_rules()
BY_ID = {rule["id"]: rule for rule in RULES}
TABLES = doc.allowlist(doc.load_schema())
GOLDEN = {line["id"]: line for line in load_golden()}
CITATIONS = [(qid, rule_id) for qid, line in GOLDEN.items() for rule_id in line["rules"]]


def collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_rule_count_stays_in_the_planned_range():
    assert 12 <= len(RULES) <= 15, f"{len(RULES)} kural"


def test_ids_are_unique():
    assert len(BY_ID) == len(RULES), sorted(rule["id"] for rule in RULES)


@pytest.mark.parametrize("rule_id", sorted(BY_ID))
def test_rule_shape(rule_id):
    rule = BY_ID[rule_id]
    assert re.fullmatch(r"[a-z0-9_]+", rule_id), rule_id
    assert rule["term"].strip() and rule["definition"].strip()
    assert isinstance(rule["sql_hint"], str)
    for name in ("synonyms", "tables", "markers"):
        assert isinstance(rule[name], list), f"{rule_id}.{name} liste değil"
        assert all(isinstance(value, str) and value.strip() for value in rule[name]), f"{rule_id}.{name}"


@pytest.mark.parametrize("rule_id", sorted(BY_ID))
def test_rule_tables_exist_in_the_schema(rule_id):
    for table in BY_ID[rule_id]["tables"]:
        assert table.upper() in TABLES, f"{rule_id} şemada olmayan tabloya bakıyor: {table}"


@pytest.mark.parametrize("rule_id", sorted(BY_ID))
def test_markers_are_valid_regexes(rule_id):
    for marker in BY_ID[rule_id]["markers"]:
        re.compile(marker)


def test_every_rule_cited_by_a_golden_line_exists():
    missing = sorted({rule_id for _, rule_id in CITATIONS} - set(BY_ID))
    assert not missing, f"golden'da kural iddiası var, rules.json'da yok: {missing}"


@pytest.mark.parametrize("qid,rule_id", CITATIONS)
def test_markers_match_the_sql_that_cites_them(qid, rule_id):
    sql = collapse(GOLDEN[qid]["sql"])
    for marker in BY_ID[rule_id]["markers"]:
        assert re.search(marker, sql, re.IGNORECASE), f"{qid} -> {rule_id} işaretçisi SQL'de yok: {marker}"


def test_the_rules_the_plan_names_say_what_the_plan_says():
    assert "KDV hariç" in BY_ID["ciro"]["definition"]
    assert "STHAR_NF" in BY_ID["ciro"]["definition"]
    assert "düşülmez" in BY_ID["ciro"]["definition"]
    assert "iade" in BY_ID["net_satis"]["definition"]
    assert "miktar" in BY_ID["net_satis"]["definition"].lower()
    assert "AS_OF" in BY_ID["gecen_ay"]["definition"] and "2026-08" in BY_ID["gecen_ay"]["definition"]
    assert "AS_OF" in BY_ID["bu_yil"]["definition"] and "2026-01-01" in BY_ID["bu_yil"]["definition"]
    assert "'A'" in BY_ID["alici"]["sql_hint"] and "'H'" in BY_ID["alici"]["sql_hint"]


def test_rule_text_block_carries_every_field():
    rule = BY_ID["ciro"]
    text = rules.rule_text(rule)
    assert text.startswith(rule["term"])
    assert "Eş anlamlıları: " + ", ".join(rule["synonyms"]) in text
    assert "Tanım: " + rule["definition"] in text
    assert "SQL ipucu: " + rule["sql_hint"] in text
    assert "Tablolar: " + ", ".join(rule["tables"]) in text


def test_rules_text_is_one_block_per_rule():
    assert rules.rules_text(RULES).split("\n\n") == [rules.rule_text(rule) for rule in RULES]


def test_load_rules_fills_the_contract_defaults(tmp_path):
    path = tmp_path / "rules.json"
    path.write_text(
        json.dumps({"rules": [{"id": "test", "term": "Test", "definition": "tanım"}]}), encoding="utf-8"
    )
    assert rules.load_rules(path) == [
        {
            "id": "test",
            "term": "Test",
            "definition": "tanım",
            "sql_hint": "",
            "synonyms": [],
            "tables": [],
            "markers": [],
        }
    ]
