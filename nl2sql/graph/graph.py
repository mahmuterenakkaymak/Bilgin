"""Join graphı: şemadaki fk'lar ile profil çiftlerinin birleşimi (PLAN R2-10).

Kenar yönsüzdür - bir soru hangi tablodan yürümeye başlarsa köprüyü o taraftan kullanır. Bir fk
kenarı aynı kolon çiftini paylaşan profil kenarını kovar: şemanın söylediği bağlantı, profilin
tahmininden önce gelir. Modülde tek bir ERP kuralı yok; kolon adlarını buraya profil dosyası söyler.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class Edge:
    """İki tablonun birer kolonunu eşitleyen kenar; `source` "fk" veya "profile"."""

    left_table: str
    left_column: str
    right_table: str
    right_column: str
    confidence: float
    source: str


class JoinGraph:
    """Tablo -> ona dokunan kenarlar; `tables` kenarı olmayan şema tablolarını da içerir."""

    def __init__(self, edges: Iterable[Edge], tables: Iterable[str]) -> None:
        self.edges = list(edges)
        self.tables = set(tables)
        self.adjacency: dict[str, list[Edge]] = {name: [] for name in sorted(self.tables)}
        for edge in self.edges:
            self.adjacency[edge.left_table].append(edge)
            self.adjacency[edge.right_table].append(edge)


def build_graph(schema: dict, profile: list[dict]) -> JoinGraph:
    """fk kenarları (confidence 1.0) + profil kenarları; aynı kolon çiftinde fk kazanır."""
    edges: list[Edge] = []
    taken: set[frozenset[tuple[str, str]]] = set()
    for table in schema["tables"]:
        for column in table.get("columns", []):
            if column.get("fk"):
                ref_table, ref_column = column["fk"].rsplit(".", 1)
                _add(edges, taken, Edge(table["name"], column["name"], ref_table, ref_column, 1.0, "fk"))
    holders = _holders(schema)
    for pair in profile:
        for left in holders.get(pair["left"], []):
            for right in holders.get(pair["right"], []):
                if left != right:
                    _add(
                        edges,
                        taken,
                        Edge(left, pair["left"], right, pair["right"], pair["confidence"], "profile"),
                    )
    return JoinGraph(edges, [table["name"] for table in schema["tables"]])


def _holders(schema: dict) -> dict[str, list[str]]:
    """Kolon adı -> o kolonu taşıyan tablolar (şema sırasıyla): bir profil çifti burada çoğalır."""
    holders: dict[str, list[str]] = {}
    for table in schema["tables"]:
        for column in table.get("columns", []):
            holders.setdefault(column["name"], []).append(table["name"])
    return holders


def _add(edges: list[Edge], taken: set[frozenset[tuple[str, str]]], edge: Edge) -> None:
    """Aynı iki kolonu ikinci kez eklemeyişi; yön fark etmez, bu yüzden çift sırasız.

    Bir de aynı adlı çiftlerin (STOK...) A->B ve B->A hâlinde iki kez dönmesini engeller.
    """
    key = frozenset(((edge.left_table, edge.left_column), (edge.right_table, edge.right_column)))
    if key not in taken:
        taken.add(key)
        edges.append(edge)
