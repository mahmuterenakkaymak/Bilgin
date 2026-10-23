"""R2-10: graph yalnızca fk ve profilden kurulur - Python'da ERP kuralı yok.

İki iddia var: şemadaki her fk bir kenardır ve hiçbir profil kenarı onu geçersiz kılamaz; profil
kenarları ise yönsüzdür ve her tabloda bulunan kolonlardan (TARIH, TUTAR, ACIKLAMA) çöp kenar üretmez.
"""

import json
from pathlib import Path

import pytest

from nl2sql.graph import graph as graph_module
from nl2sql.graph.graph import build_graph
from nl2sql.graph.profile import load_profile
from nl2sql.schema_map.doc import load_schema

SCHEMA = load_schema()
PROFILE = load_profile()
GRAPH = build_graph(SCHEMA, PROFILE)
FK_COLUMNS = [
    (table["name"], column["name"], column["fk"])
    for table in SCHEMA["tables"]
    for column in table["columns"]
    if column["fk"]
]

# Başlı-cari kodu iki ayrı kolona yazan bir tablo çifti: fk mı profil mi, kendi kendine döner mi.
MINI_SCHEMA = {
    "tables": [
        {
            "name": "HEAD",
            "columns": [{"name": "CARI_KOD"}, {"name": "CARI_KODU"}, {"name": "TUTAR"}],
        },
        {
            "name": "LINE",
            "columns": [{"name": "CARI_KOD", "fk": "HEAD.CARI_KOD"}, {"name": "TUTAR"}],
        },
    ]
}

GENERIC = ("TARIH", "TUTAR", "ACIKLAMA")


def test_every_fk_column_becomes_a_full_confidence_edge():
    fk_edges = [edge for edge in GRAPH.edges if edge.source == "fk"]
    assert len(fk_edges) == len(FK_COLUMNS)
    assert all(edge.confidence == 1.0 for edge in fk_edges)
    assert {(edge.left_table, edge.left_column) for edge in fk_edges} == {
        (table, column) for table, column, _ in FK_COLUMNS
    }
    assert {(edge.right_table, edge.right_column) for edge in fk_edges} == {
        tuple(fk.rsplit(".", 1)) for _, _, fk in FK_COLUMNS
    }


def test_a_profile_edge_is_walkable_from_both_tables():
    # Hareket ile kampanya arasında fk yok; ikisini STOK_KODU üzerinden profil bağlıyor.
    edges = [
        edge
        for edge in GRAPH.adjacency["TBLKAMPANYA"]
        if {edge.left_table, edge.right_table} == {"TBLKAMPANYA", "TBLSTHAR"}
    ]
    assert len(edges) == 1
    edge = edges[0]
    assert (edge.source, edge.confidence) == ("profile", 0.9)
    assert (edge.left_column, edge.right_column) == ("STOK_KODU", "STOK_KODU")
    assert edge in GRAPH.adjacency["TBLSTHAR"]


def test_an_fk_wins_over_a_profile_edge_on_the_same_columns():
    graph = build_graph(MINI_SCHEMA, [{"left": "CARI_KOD", "right": "CARI_KOD", "confidence": 0.6}])
    assert len(graph.edges) == 1
    assert (graph.edges[0].source, graph.edges[0].confidence) == ("fk", 1.0)


def test_a_table_carrying_both_columns_never_joins_itself():
    graph = build_graph(MINI_SCHEMA, [{"left": "CARI_KOD", "right": "CARI_KODU", "confidence": 0.8}])
    assert all(edge.left_table != edge.right_table for edge in graph.edges)
    assert {(edge.left_table, edge.right_table) for edge in graph.edges} == {("LINE", "HEAD")}


def test_no_edge_starts_and_ends_in_the_same_table():
    assert all(edge.left_table != edge.right_table for edge in GRAPH.edges)


def test_the_everyday_columns_join_nothing():
    # ASSUMPTION: TARIH <-> KUR_TARIH, döviz kurunun belge tarihine bağlandığı tek tarih çifti
    # (Q26, Q36); yasak olan aynı adlı genel kolonun iki tabloyu birbirine bağlaması.
    assert all(pair["left"] != pair["right"] or pair["left"] not in GENERIC for pair in PROFILE)
    assert not any(edge.left_column == edge.right_column == name for name in GENERIC for edge in GRAPH.edges)
    assert not any(
        name in (edge.left_column, edge.right_column) for name in ("TUTAR", "ACIKLAMA") for edge in GRAPH.edges
    )


def test_every_profile_pair_names_a_column_the_schema_has():
    columns = {column["name"] for table in SCHEMA["tables"] for column in table["columns"]}
    assert all(pair["left"] in columns and pair["right"] in columns for pair in PROFILE)


def test_the_profile_carries_the_netsis_column_pairs():
    assert {(pair["left"], pair["right"]): pair["confidence"] for pair in PROFILE} == {
        ("STOK_KODU", "STOK_KODU"): 0.9,
        ("DEPO_KODU", "DEPO_KODU"): 0.9,
        ("CARI_KOD", "CARI_KODU"): 0.8,
        ("FISNO", "FATIRS_NO"): 0.8,
        ("PLASIYER_KODU", "PLASIYER_KODU"): 0.8,
        ("SIPARIS_NO", "SIPARIS_NO"): 0.8,
        ("GRUP_KODU", "GRUP_KODU"): 0.7,
        ("TARIH", "KUR_TARIH"): 0.7,
        ("CARI_KOD", "CARI_KOD"): 0.6,
    }


def test_a_table_without_an_edge_is_still_a_known_table():
    lonely = {"tables": [{"name": "HEAD", "columns": [{"name": "CARI_KOD"}]}, {"name": "SOLO", "columns": []}]}
    graph = build_graph(lonely, [])
    assert graph.edges == []
    assert graph.tables == {"HEAD", "SOLO"}


@pytest.mark.parametrize("confidence", ["0.8", 0, 1, 1.5, -0.5])
def test_load_profile_refuses_any_other_confidence(tmp_path, confidence):
    path = tmp_path / "profil.json"
    pair = {"left": "CARI_KOD", "right": "CARI_KODU", "confidence": confidence}
    path.write_text(json.dumps({"name": "test", "pairs": [pair]}), encoding="utf-8")
    with pytest.raises(ValueError, match="confidence"):
        load_profile(path)


def test_the_graph_modules_never_name_a_table():
    for path in sorted(Path(graph_module.__file__).parent.glob("*.py")):
        assert "TBL" not in path.read_text(encoding="utf-8"), path
