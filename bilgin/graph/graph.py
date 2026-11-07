# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Join graphı: şemadaki fk'lar ile profil çiftlerinin birleşimi (PLAN R2-10).

Kenar yönsüzdür - bir soru hangi tablodan yürümeye başlarsa köprüyü o taraftan kullanır. Bir fk
kenarı aynı kolon çiftini paylaşan profil kenarını kovar: şemanın söylediği bağlantı, profilin
tahmininden önce gelir. Modülde tek bir ERP kuralı yok; kolon adlarını buraya profil dosyası söyler.
"""

from __future__ import annotations

import heapq
from collections.abc import Iterable
from dataclasses import dataclass, field

from bilgin import config
from bilgin.schema_map import doc


class GraphError(RuntimeError):
    """Yol kurulamayan iki durum: tablo şemada yok ya da iki tablo birbirine bağlı değil."""


@dataclass(frozen=True)
class Edge:
    """İki tablonun birer kolonunu eşitleyen kenar; `source` "fk" veya "profile"."""

    left_table: str
    left_column: str
    right_table: str
    right_column: str
    confidence: float
    source: str


@dataclass(frozen=True)
class JoinPath:
    """Yolun kapsadığı tablolar (istenenler + köprüler), kullanılan kenarlar ve düşük güvenliler."""

    tables: list[str]
    joins: list[Edge]
    low_confidence: list[Edge] = field(default_factory=list)


class JoinGraph:
    """Tablo -> ona dokunan kenarlar; `tables` kenarı olmayan şema tablolarını da içerir."""

    def __init__(self, edges: Iterable[Edge], tables: Iterable[str]) -> None:
        self.edges = list(edges)
        self.tables = set(tables)
        self.adjacency: dict[str, list[Edge]] = {name: [] for name in sorted(self.tables)}
        for edge in self.edges:
            self.adjacency[edge.left_table].append(edge)
            self.adjacency[edge.right_table].append(edge)

    def find_join_path(self, tables: Iterable[str]) -> JoinPath:
        """İlk tablodan diğerlerinin her birine en ucuz yolların birleşimi (PLAN R2-10).

        Köprü olarak kullanılan tablolar `tables`a eklenir; tek tablo join istemez.
        """
        names = list(dict.fromkeys(tables))
        for name in names:
            if name not in self.tables:
                raise GraphError(f"Bilinmeyen tablo: {name}")
        if len(names) < 2:
            return JoinPath(names, [])
        start = names[0]
        previous = self._cheapest_from(start)
        joins: dict[tuple[str, str, str, str], Edge] = {}
        bridges: set[str] = set()
        for target in names[1:]:
            if target not in previous:
                raise GraphError(f"Bağlantı yolu yok: {start} - {target}.")
            node = target
            while node != start:
                edge, parent = previous[node]
                joins[_identity(edge)] = edge
                bridges.update((node, parent))
                node = parent
        ordered = sorted(joins.values(), key=_identity)
        return JoinPath(
            names + sorted(bridges - set(names)),
            ordered,
            [edge for edge in ordered if edge.confidence < config.LOW_CONFIDENCE],
        )

    def _cheapest_from(self, start: str) -> dict[str, tuple[Edge, str]]:
        """Dijkstra: kenar maliyeti 1/confidence; eşit maliyette tablo adı alfabede önde olan kazanır."""
        cost = {start: 0.0}
        previous: dict[str, tuple[Edge, str]] = {}
        queue: list[tuple[float, str]] = [(0.0, start)]
        settled: set[str] = set()
        while queue:
            so_far, table = heapq.heappop(queue)
            if table in settled:
                continue
            settled.add(table)
            neighbours = [
                (edge, edge.right_table if edge.left_table == table else edge.left_table)
                for edge in self.adjacency[table]
            ]
            for edge, other in sorted(neighbours, key=lambda pair: (pair[1], _identity(pair[0]))):
                step = so_far + 1.0 / edge.confidence
                if other not in cost or step < cost[other]:
                    cost[other] = step
                    previous[other] = (edge, table)
                    heapq.heappush(queue, (step, other))
        return previous


def _identity(edge: Edge) -> tuple[str, str, str, str]:
    """Kenarı sıralanabilir ve tekrar edilemez yapan kimlik; yön adları, kolon adları izler."""
    return edge.left_table, edge.left_column, edge.right_table, edge.right_column


def build_graph(schema: dict, profile: list[dict]) -> JoinGraph:
    """fk kenarları (confidence 1.0) + profil kenarları; aynı kolon çiftinde fk kazanır."""
    edges: list[Edge] = []
    taken: set[frozenset[tuple[str, str]]] = set()
    for table in schema["tables"]:
        for column in table.get("columns", []):
            if column.get("fk"):
                # split_fk kolonu son parça sayar, yani "Sales.Orders.OrderID" hedefi tablo adını
                # bölemeden kalır (R4-5).
                ref_table, ref_column = doc.split_fk(column["fk"])
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


def join_text(path: JoinPath) -> str:
    """Aracın model verdiği cevap: her join bir satır, düşük güvenli joinler ayrıca uyarı satırı."""
    if not path.joins:
        return "Tek tablo; join gerekmiyor."
    lines = [_edge_text(edge) for edge in path.joins]
    lines += [f"⚠ düşük güven: {_edge_text(edge)}" for edge in path.low_confidence]
    return "\n".join(lines)


def _edge_text(edge: Edge) -> str:
    return f"{edge.left_table}.{edge.left_column} = {edge.right_table}.{edge.right_column} ({edge.source} {edge.confidence})"
