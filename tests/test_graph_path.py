# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R2-10: find_join_path en ucuz yolların birleşimini, join_text de aracın metnini verir.

Üç iddia: köprü tablo istenmemiş olsa da yola girer; bir tablo çiftinde fk kenarı aynı çiftin
profil kenarını ezer; golden SQL'in kullandığı her eşitlik joini graph'ta bir kenardır.
"""

import pytest
import sqlglot
from sqlglot import exp

from nl2sql.eval.runner import load_golden
from nl2sql.graph.graph import GraphError, build_graph, join_text
from nl2sql.graph.profile import load_profile
from nl2sql.schema_map.doc import load_schema

GRAPH = build_graph(load_schema(), load_profile())
MULTI_JOIN = [line for line in load_golden() if "multi_join" in line["tags"]]

# Gerçek şemada birbirine bağlı olmayan iki tablo yok (83 tablo tek parça), o yüzden kopukluk
# küçük bir şemada denenir.
SPLIT_SCHEMA = {
    "tables": [
        {"name": "BASLIK", "columns": [{"name": "KOD", "fk": "KALEM.KOD"}]},
        {"name": "KALEM", "columns": [{"name": "KOD"}]},
        {"name": "YALNIZ", "columns": [{"name": "KOD"}]},
    ]
}


def _sides(edge):
    return frozenset(((edge.left_table, edge.left_column), (edge.right_table, edge.right_column)))


def _spans(edges, tables) -> bool:
    """joinler tabloları tek parça bağlıyor mu: cevap gerçekten kullanılabilir bir join planı."""
    reached = {tables[0]}
    stack = [tables[0]]
    while stack:
        node = stack.pop()
        for edge in edges:
            other = edge.right_table if edge.left_table == node else edge.left_table
            if other not in reached:
                reached.add(other)
                stack.append(other)
    return reached == set(tables)


def _golden_joins(sql) -> set:
    """SQL'deki iki kolonu eşitleyen koşullar; alias gerçek tablo adına çevrilmiş hâlde."""
    tree = sqlglot.parse_one(sql, read="tsql")
    alias = {table.alias_or_name: table.name for table in tree.find_all(exp.Table)}
    conditions = set()
    for equality in tree.find_all(exp.EQ):
        left, right = equality.left, equality.right
        if isinstance(left, exp.Column) and isinstance(right, exp.Column):
            a = (alias.get(left.table, left.table), left.name)
            b = (alias.get(right.table, right.table), right.name)
            if a[0] != b[0]:
                conditions.add(frozenset((a, b)))
    return conditions


def test_two_tables_with_no_connection_name_both_of_them():
    with pytest.raises(GraphError, match=r"Bağlantı yolu yok: BASLIK - YALNIZ\."):
        build_graph(SPLIT_SCHEMA, []).find_join_path(["BASLIK", "YALNIZ"])


