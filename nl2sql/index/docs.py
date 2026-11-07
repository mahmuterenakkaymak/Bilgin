# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""İndeks dokümanları: şema ile kuralların aranabilir metni ve kaçak kontrolü (PLAN R2-16).

Bir doküman retrieval'ın gördüğü tek şey; içinde eksik kalan kelimeyi model hiç bulamaz. Bu yüzden
metin, modelin promptta gördüğü dille aynı. `kind` ise bilinçli olarak dışarıda: hangi tablonun
dolgu olduğunu söyleyen bir bayrak, altın sorunun sızması kadar büyük bir sızıntı olurdu.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field

from nl2sql.index.text import fold, shingles, tokens
from nl2sql.schema_map.rules import rule_text

COLLECTIONS = ("tables", "rules", "summaries", "examples")


@dataclass
class Doc:
    """Tek bir indeksleme birimi; `id` hem vektörün hem her Hit'in geri döndüğü anahtar."""

    id: str
    collection: str
    title: str
    text: str
    meta: dict = field(default_factory=dict)


def build_documents(schema: dict, rules: list[dict]) -> list[Doc]:
    """Tablo başına bir, kural başına bir doküman; `examples` koleksiyonu Run 2'de boş kalır."""
    docs = [
        Doc(
            id=f"table:{table['name']}",
            collection="tables",
            title=table["name"],
            text=_table_text(table),
            meta={"table": table["name"], "module": table.get("module", "")},
        )
        for table in schema["tables"]
    ]
    docs += [
        Doc(
            id=f"rule:{rule['id']}",
            collection="rules",
            title=rule["term"],
            text=rule_text(rule),
            meta={"term": rule["term"], "tables": list(rule.get("tables", []))},
        )
        for rule in rules
    ]
    return docs


def leaks(docs: Iterable[Doc], questions: Iterable[dict], n: int = 6) -> list[tuple[str, str]]:
    """Soru metnini aynen içeren veya onun herhangi bir n-token penceresini paylaşan (qid, doc_id)."""
    prepared = [(doc, fold(doc.text), _shingles(doc.text, n)) for doc in docs]
    found: list[tuple[str, str]] = []
    for question in questions:
        asked = fold(question["question"])
        shared = _shingles(question["question"], n)
        found += [
            (question["id"], doc.id)
            for doc, doc_text, doc_shingles in prepared
            if asked in doc_text or shared & doc_shingles
        ]
    return found


def _table_text(table: dict) -> str:
    """Tablo adı ve modülü, açıklaması, anahtar kelimeleri, sonra her okunabilir kolon ve kod anlamları.

    Bir `deny` kolon dokümana hiç girmez: adını buradan okuyan model onu sorgusuna da yazar (PLAN R4-7).
    """
    module = f" [{table['module']}]" if table.get("module") else ""
    lines = [f"{table['name']}{module}"]
    if table.get("description"):
        lines.append(table["description"])
    if table.get("keywords"):
        lines.append("Anahtar kelimeler: " + ", ".join(table["keywords"]))
    for column in table.get("columns", []):
        if column.get("deny"):
            continue
        line = column["name"]
        if column.get("description"):
            line += " — " + column["description"]
        if column.get("values"):
            codes = ", ".join(f"{code}={meaning}" for code, meaning in column["values"].items())
            line += " [" + codes + "]"
        lines.append(line)
    return "\n".join(lines)


def _shingles(text: str, n: int) -> set[tuple[str, ...]]:
    return shingles(tokens(text), n)
