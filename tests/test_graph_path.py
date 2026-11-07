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


def test_two_tables_with_a_foreign_key_need_one_join():
    path = GRAPH.find_join_path(["TBLCARISUBE", "TBLCASABIT"])
    assert path.tables == ["TBLCARISUBE", "TBLCASABIT"]
    assert [(edge.source, edge.confidence) for edge in path.joins] == [("fk", 1.0)]
    assert path.low_confidence == []


def test_one_table_needs_no_join():
    path = GRAPH.find_join_path(["TBLSTHAR"])
    assert (path.tables, path.joins, path.low_confidence) == (["TBLSTHAR"], [], [])
    assert join_text(path) == "Tek tablo; join gerekmiyor."


def test_a_repeated_table_is_listed_once():
    assert GRAPH.find_join_path(["TBLSTHAR", "TBLSTHAR"]).tables == ["TBLSTHAR"]


def test_the_bridge_table_joins_the_two_it_was_asked_to_connect():
    path = GRAPH.find_join_path(["TBLFATUIRS", "TBLPLASIYER"])
    assert path.tables == ["TBLFATUIRS", "TBLPLASIYER", "TBLCASABIT"]
    assert {_sides(edge) for edge in path.joins} == {
        frozenset((("TBLFATUIRS", "CARI_KODU"), ("TBLCASABIT", "CARI_KOD"))),
        frozenset((("TBLCASABIT", "PLASIYER_KODU"), ("TBLPLASIYER", "PLASIYER_KODU"))),
    }


def test_an_fk_hop_wins_the_same_table_pair_over_a_profile_hop():
    # TBLRECETE ile TBLRECETED arasında iki kenar var: RECETE_ID fk'ı ve STOK_KODU profili (0,9).
    path = GRAPH.find_join_path(["TBLRECETE", "TBLRECETED"])
    assert [(edge.source, edge.confidence) for edge in path.joins] == [("fk", 1.0)]


def test_a_shared_bridge_is_used_once_and_the_answer_repeats_itself():
    tables = ["TBLFATUIRS", "TBLCASABIT", "TBLPLASIYER", "TBLDOVKUR"]
    path = GRAPH.find_join_path(tables)
    assert len(path.joins) == len({_sides(edge) for edge in path.joins}) == 3
    assert GRAPH.find_join_path(tables).joins == path.joins


def test_a_weak_edge_is_listed_apart_from_the_path():
    path = GRAPH.find_join_path(["TBLCARISUBE", "TBLGARANTI"])
    assert [(edge.source, edge.confidence) for edge in path.low_confidence] == [("profile", 0.6)]
    assert path.low_confidence == path.joins


def test_join_text_names_both_columns_and_where_the_edge_came_from():
    assert join_text(GRAPH.find_join_path(["TBLCARISUBE", "TBLCASABIT"])) == (
        "TBLCARISUBE.CARI_KOD = TBLCASABIT.CARI_KOD (fk 1.0)"
    )
    assert join_text(GRAPH.find_join_path(["TBLCARISUBE", "TBLGARANTI"])) == (
        "TBLCARISUBE.CARI_KOD = TBLGARANTI.CARI_KOD (profile 0.6)\n"
        "⚠ düşük güven: TBLCARISUBE.CARI_KOD = TBLGARANTI.CARI_KOD (profile 0.6)"
    )


def test_a_table_the_schema_does_not_have_stops_the_search():
    for tables in (["TBLYOK"], ["TBLSTHAR", "TBLYOK"]):
        with pytest.raises(GraphError, match="Bilinmeyen tablo: TBLYOK"):
            GRAPH.find_join_path(tables)


def test_two_tables_with_no_connection_name_both_of_them():
    with pytest.raises(GraphError, match=r"Bağlantı yolu yok: BASLIK - YALNIZ\."):
        build_graph(SPLIT_SCHEMA, []).find_join_path(["BASLIK", "YALNIZ"])


@pytest.mark.parametrize("golden", MULTI_JOIN, ids=[line["id"] for line in MULTI_JOIN])
def test_the_graph_holds_every_join_a_multi_join_golden_uses(golden):
    # ASSUMPTION: en ucuz yol iki istenen tabloyu doğrudan köprülediğinde golden aynı iki tabloyu üçüncüden
    # bağlayabiliyor (Q24, Q25, Q29, Q35); golden join'i bu yüzden graph'ın kenarlarında aranır, yolu da.
    path = GRAPH.find_join_path(golden["requires_tables"])
    assert set(golden["requires_tables"]) <= set(path.tables)
    assert _spans(path.joins, path.tables)
    conditions = _golden_joins(golden["sql"])
    assert conditions and conditions <= {_sides(edge) for edge in GRAPH.edges}
