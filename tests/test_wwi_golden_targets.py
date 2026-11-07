# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T142: WWI golden kümesi R4-9 hedeflerini karşılar (PLAN R4-9).

Altın küme bütün olarak sayılır: en az altı `needs_rule`, en az altı `multi_join`, en az dört
`needs_values` (satın alma grubu, stok grubu, ülke ve teslimat yöntemi adlarının her biri en az bir
soru tarafından süzülür); traps.jsonl'daki her tuzak en az bir soruda kullanılır ve rules.json'daki
her kural en az bir soru tarafından cite edilir. Her `multi_join` sorusunun SQL'indeki her join
koşulu, o sorunun `requires_tables` listesi için `find_join_path`'in bulduğu en kısa yolun
kenarlarından biridir - yani soru gerçekten grafla kurulabilen bir join yürür. Son olarak hiçbir
altın soru indeks dokümanlarına sızmaz (retrieval altın cevabı okuyamaz).
"""

import json

import pytest
from sqlglot import exp, parse_one

from nl2sql.datasets import load_dataset
from nl2sql.graph.graph import build_graph
from nl2sql.graph.profile import load_profile
from nl2sql.index import docs as docs_mod

DATASET = load_dataset("wwi")
SCHEMA = DATASET.schema()
GOLDEN = DATASET.golden()
RULES = DATASET.rules()
TRAPS = [json.loads(line) for line in DATASET.traps_path.read_text(encoding="utf-8").splitlines() if line.strip()]
GRAPH = build_graph(SCHEMA, load_profile(DATASET.profile_path))

# needs_values'un süzdüğü dört değer türü: her birinin adı ayrı bir tablodadır.
VALUE_TABLES = {
    "Sales.BuyingGroups": "satın alma grubu adı",
    "Warehouse.StockGroups": "stok grubu adı",
    "Application.Countries": "ülke adı",
    "Application.DeliveryMethods": "teslimat yöntemi adı",
}
MULTI_JOIN = [line for line in GOLDEN if "multi_join" in line["tags"]]


def tagged(tag):
    return [line for line in GOLDEN if tag in line["tags"]]


def join_pairs(sql):
    """SQL'deki her ON koşulunu yönsüz (tablo, kolon) çiftleri kümesine çevirir; takma adlar çözülür."""
    tree = parse_one(sql, read="tsql")
    alias = {table.alias_or_name: (f"{table.db}.{table.name}" if table.db else table.name) for table in tree.find_all(exp.Table)}
    pairs = []
    for join in tree.find_all(exp.Join):
        on = join.args.get("on")
        if on is None:
            continue
        columns = list(on.find_all(exp.Column))
        if len(columns) != 2:
            continue
        left, right = columns
        pairs.append(
            frozenset({
                (alias.get(left.table, left.table), left.name),
                (alias.get(right.table, right.table), right.name),
            })
        )
    return pairs


def path_pairs(tables):
    path = GRAPH.find_join_path(tables)
    return {frozenset({(e.left_table, e.left_column), (e.right_table, e.right_column)}) for e in path.joins}


def edge_text(pair):
    return " = ".join(sorted(f"{table}.{column}" for table, column in pair))


# ------------------------------------------------------------------ count targets


def test_at_least_six_needs_rule():
    assert len(tagged("needs_rule")) >= 6


def test_at_least_six_multi_join():
    assert len(tagged("multi_join")) >= 6


def test_at_least_four_needs_values():
    assert len(tagged("needs_values")) >= 4


def test_needs_values_cover_the_four_value_kinds():
    tables = {table for line in tagged("needs_values") for table in line["requires_tables"]}
    for value_table, kind in VALUE_TABLES.items():
        assert value_table in tables, f"hiçbir needs_values {kind} ({value_table}) üzerinden süzmüyor"


def test_every_trap_tag_is_used_by_at_least_one_question():
    used = {line["trap"] for line in GOLDEN if line["trap"]}
    missing = {trap["trap"] for trap in TRAPS} - used
    assert not missing, f"hiçbir soru şu tuzakları kullanmıyor: {sorted(missing)}"


def test_every_rule_is_cited_by_at_least_one_question():
    cited = {rule_id for line in GOLDEN for rule_id in line["rules"]}
    missing = {rule["id"] for rule in RULES} - cited
    assert not missing, f"hiçbir soru şu kuralları cite etmiyor: {sorted(missing)}"


# ------------------------------------------------------------------ join conditions ride the graph


def test_there_are_multi_join_questions_to_check():
    assert MULTI_JOIN, "join yolunu sınanacak multi_join sorusu yok"


@pytest.mark.parametrize("line", MULTI_JOIN, ids=[line["id"] for line in MULTI_JOIN])
def test_every_multi_join_condition_is_on_the_shortest_join_path(line):
    on_path = path_pairs(line["requires_tables"])
    for pair in join_pairs(line["sql"]):
        assert pair in on_path, f"{line['id']}: {edge_text(pair)} en kısa join yolunda ({line['requires_tables']}) yok"


# ------------------------------------------------------------------ no golden answer in the index


def test_no_golden_question_leaks_into_the_index():
    documents = docs_mod.build_documents(SCHEMA, RULES)
    assert docs_mod.leaks(documents, GOLDEN) == []
