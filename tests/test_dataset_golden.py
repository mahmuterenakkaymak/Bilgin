"""T141: her veri kümesinin golden kümesi kendi sözleşmesine göre ölçülür.

``datasets.list_datasets()`` içindeki her küme ve o kümenin her golden satırı tek tek sınanır:
satır policy'den geçer, tek bir SQLite ifadesine çevrilir, kümenin kendi ``build_db`` ile kurduğu
dünyada COMPARE bütçesiyle çalıştırılır ve 2 haneye indirilmiş Python doğrulundan farksız çıkar
(sıra yalnız satır ``ordered`` ise karşılaştırır), en az bir satır döner. Satırın beyanları
(SQL'iyle doğrulanır): etiketler o kümenin traps.jsonl'ından gelen ``trap:<ad>`` ile sabit
sözlükten gelir, ``requires_tables`` sqlglot'ın CTE farkıyla bulduğu gerçek tablolardır,
``multi_join`` ve ``needs_rule`` o beyanlardan türer, cite edilen her kural vardır ve işaretçileri
SQL'de geçer. Her tuzak naive SQL'i kendi sorusunun golden sonucundan saptırır. Kimlikler
dosyadan okunur, sayı sabitlenmez.
"""

import json
import re
from decimal import ROUND_HALF_UP, Decimal

import pytest

from nl2sql import datasets
from nl2sql.datasets import load_dataset
from nl2sql.engine import executor as executor_mod
from nl2sql.eval.runner import COMPARE
from nl2sql.policy import policy
from nl2sql.schema_map import doc

# R2-15 sabit etiketleri; trap:<ad> o kümenin traps.jsonl'ından gelir.
EXTRA_TAGS = ("needs_rule", "multi_join", "distractor", "needs_values", "archive")


def _load_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


DATASETS = {name: load_dataset(name) for name in datasets.list_datasets()}
SCHEMAS = {name: ds.schema() for name, ds in DATASETS.items()}
ALLOWLISTS = {name: doc.allowlist(SCHEMAS[name]) for name in DATASETS}
GOLDEN = {name: DATASETS[name].golden() for name in DATASETS}
ROWS = {name: DATASETS[name].generate() for name in DATASETS}
REFS = {name: DATASETS[name].references() for name in DATASETS}
RULES = {name: {rule["id"]: rule for rule in DATASETS[name].rules()} for name in DATASETS}
TRAPS = {
    name: _load_jsonl(DATASETS[name].traps_path) if DATASETS[name].traps_path else []
    for name in DATASETS
}
NAMES = sorted(DATASETS)
CASES = [(name, line) for name in NAMES for line in GOLDEN[name]]
CASE_IDS = [f"{name}::{line['id']}" for name, line in CASES]


def cell(value):
    """Sayıları 2 haneye indirir; yığma ondalık farkı doğruyu SQL ile kapıştırmasın."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    stable = Decimal(repr(round(float(value), 6)))
    return float(stable.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def comparable(rows, ordered):
    """ordered=True sırayı da karşılaştırır; değilse çok küme olarak sıralanır."""
    values = [tuple(map(cell, row)) for row in rows]
    return values if ordered else sorted(values, key=repr)


@pytest.fixture(scope="module")
def executors(tmp_path_factory):
    """Her kümenin kendi builder'ının kurduğu dosya üzerinden geçen tek kapı."""
    built = {}
    for name, ds in DATASETS.items():
        folder = tmp_path_factory.mktemp(f"golden-{name}")
        database, script = folder / f"{name}.db", folder / f"{name}.sql"
        ds.build_db(db_path=database, sql_path=script)
        built[name] = executor_mod.LocalExecutor("sqlite", database, ALLOWLISTS[name], folder / "audit.jsonl")
    return built


# ------------------------------------------------------------------ file shape per dataset


@pytest.mark.parametrize("name", NAMES)
def test_ids_are_unique_and_sequential(name):
    ids = [line["id"] for line in GOLDEN[name]]
    assert ids == [f"Q{number:02d}" for number in range(1, len(ids) + 1)], name


@pytest.mark.parametrize("name", NAMES)
def test_every_trap_maps_to_one_golden_question(name):
    golden_ids = {line["id"] for line in GOLDEN[name]}
    trapped = {line["trap"] for line in GOLDEN[name] if line["trap"]}
    assert {line["trap"] for line in TRAPS[name]} == trapped, name
    for line in TRAPS[name]:
        assert set(line) == {"trap", "qid", "naive_sql"}, line
        assert line["naive_sql"].strip() and line["qid"] in golden_ids, line


# ------------------------------------------------------------------ declared tags and tables


@pytest.mark.parametrize("name,line", CASES, ids=CASE_IDS)
def test_tags_come_from_the_vocabulary(name, line):
    vocabulary = {f"trap:{trap['trap']}" for trap in TRAPS[name]} | set(EXTRA_TAGS)
    tags = line["tags"]
    assert len(tags) == len(set(tags)), f"{name}/{line['id']} aynı etiketi iki kez yazıyor"
    assert set(tags) <= vocabulary, f"{name}/{line['id']} sözlükte olmayan etiket taşıyor"


@pytest.mark.parametrize("name,line", CASES, ids=CASE_IDS)
def test_the_trap_tag_is_the_trap_field(name, line):
    named = [tag for tag in line["tags"] if tag.startswith("trap:")]
    expected = [f"trap:{line['trap']}"] if line["trap"] else []
    assert named == expected, f"{name}/{line['id']}"


@pytest.mark.parametrize("name,line", CASES, ids=CASE_IDS)
def test_needs_rule_tag_is_the_rules_field(name, line):
    assert ("needs_rule" in line["tags"]) == bool(line["rules"]), f"{name}/{line['id']}"


@pytest.mark.parametrize("name,line", CASES, ids=CASE_IDS)
def test_requires_tables_are_the_real_tables_of_the_sql(name, line):
    declared = line["requires_tables"]
    assert len(declared) == len(set(declared)), f"{name}/{line['id']} aynı tabloyu iki kez yazıyor"
    verdict = policy.check(line["sql"], ALLOWLISTS[name])
    assert verdict.ok, f"{name}/{line['id']}: {verdict.reason}"
    assert {table.upper() for table in declared} == verdict.tables, f"{name}/{line['id']}"
    assert {table.upper() for table in declared} <= ALLOWLISTS[name], f"{name}/{line['id']}"


@pytest.mark.parametrize("name,line", CASES, ids=CASE_IDS)
def test_multi_join_tag_is_three_real_tables(name, line):
    assert ("multi_join" in line["tags"]) == (len(set(line["requires_tables"])) >= 3), f"{name}/{line['id']}"


@pytest.mark.parametrize("name,line", CASES, ids=CASE_IDS)
def test_cited_rules_exist_and_their_markers_match_the_sql(name, line):
    sql = re.sub(r"\s+", " ", line["sql"]).strip()
    for rule_id in line["rules"]:
        assert rule_id in RULES[name], f"{name}/{line['id']} bilinmeyen kural {rule_id} cite ediyor"
        for marker in RULES[name][rule_id]["markers"]:
            assert re.search(marker, sql, re.IGNORECASE), f"{name}/{line['id']} -> {rule_id}: {marker}"


# ------------------------------------------------------------------ built db == python truth


@pytest.mark.parametrize("name,line", CASES, ids=CASE_IDS)
def test_golden_sql_runs_and_matches_the_reference(name, line, executors):
    assert line["id"] in REFS[name], f"{name}/{line['id']} için doğrul yok"
    assert len(executor_mod.transpile(line["sql"])) == 1, f"{name}/{line['id']} tek SQLite ifadesine çevrilmiyor"
    result = executors[name].execute(line["sql"], COMPARE, line["id"])
    assert result.error is None, f"{name}/{line['id']}: {result.error}"
    assert result.rows, f"{name}/{line['id']} boş döndü; soru hiçbir şey ölçmüyor"
    expected = comparable(REFS[name][line["id"]](ROWS[name]), line["ordered"])
    assert comparable(result.rows, line["ordered"]) == expected, f"{name}/{line['id']} SQL sonucu Python doğrulundan farklı"


@pytest.mark.parametrize("name", NAMES)
def test_every_trap_naive_sql_differs_from_the_golden(name, executors):
    golden_by_id = {line["id"]: line for line in GOLDEN[name]}
    for trap in TRAPS[name]:
        line = golden_by_id[trap["qid"]]
        result = executors[name].execute(trap["naive_sql"], COMPARE, trap["trap"])
        assert result.error is None, f"{name}/{trap['trap']}: {result.error}"
        truth = comparable(REFS[name][line["id"]](ROWS[name]), line["ordered"])
        got = comparable(result.rows, line["ordered"])
        assert got != truth, f"{name}/{trap['trap']} tuzağı {line['id']} sonucunu değiştirmiyor"
