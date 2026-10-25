"""Tablo özetleri: bir tablonun aranabilir tek cümlelik tanıtımı (PLAN R5-20).

Tablo dokümanı kolon kolon her şeyi sayar; özet ise tablonun ne işe yaradığını tek nefeste söyler:
anahtar kolonları, onu işleyen iş kurallarını ve join graphındaki komşularını. Böylece kuralını
arayan bir soru tabloyu kuralın adının yanında da bulabilir - iki ayrı doküman arasındaki köprü,
aramanın gördüğü tek yer olan metnin kendisidir.

Metin üç girdiden de (şema, kurallar, graph) yalnız kopyalar taşır, kendi cümlesini kurmaz: bir
özet uydurulmuş bir açıklama taşırsa model onu şemanın sözü sanır. Aynı girdi aynı metni verir,
yoksa iki koşumun indeksi birbirinin ölçümüyle kıyaslanamaz olur.
"""

from __future__ import annotations

from nl2sql import config
from nl2sql.index.docs import Doc

# Bir kolonun kod olduğunu söyleyen ad sonları: bu şemanın kodları Türkçe _KOD/_KODU diye
# adlandırılır, wwi'ninki İngilizce ...Code. Değer taşıyan her kolon zaten koddur (kararname 4).
_CODE_SUFFIXES = ("_KOD", "_KODU", "CODE")


def table_summaries(schema: dict, rules: list[dict], graph) -> list[Doc]:
    """Tablo başına bir özet: açıklama, anahtar kolonlar, işleyen kural terimleri ve komşular."""
    data = {
        table["name"] for table in schema["tables"] if table.get("kind") != "distractor"
    }
    terms = _terms_by_table(rules)
    return [
        Doc(
            id=f"summary:{table['name']}",
            collection="summaries",
            title=table["name"],
            text=_text(
                table,
                terms.get(table["name"], []),
                _neighbours(graph, table["name"], data),
            ),
            meta={"table": table["name"]},
        )
        for table in schema["tables"]
    ]


def _text(table: dict, terms: list[str], neighbours: list[str]) -> str:
    """Şablon: `Tablo X (modül): açıklama. Anahtar kolonlar: ... Kurallar: ... Komşular: ...`"""
    parts = [_header(table)]
    sections = (
        ("Anahtar kolonlar", _key_columns(table)),
        ("Kurallar", terms),
        ("Komşular", neighbours),
    )
    parts += [f"{title}: {', '.join(items)}" for title, items in sections if items]
    return " ".join(parts)


def _header(table: dict) -> str:
    name = f"Tablo {table['name']}"
    if table.get("module"):
        name += f" ({table['module']})"
    description = table.get("description") or ""
    return _sentence(f"{name}: {description}" if description else name)


def _key_columns(table: dict) -> list[str]:
    """fk ve kod kolonları şema sırasıyla, en fazla `SUMMARY_KEY_COLUMNS` tanesi.

    Bir `deny` kolon özete de girmez (R4-7): adını burada okuyan model onu sorgusuna da yazar.
    """
    keys = []
    for column in table.get("columns", []):
        if len(keys) == config.SUMMARY_KEY_COLUMNS:
            break
        if not column.get("deny") and _is_key(column):
            keys.append(_column_note(column))
    return keys


def _column_note(column: dict) -> str:
    """Kolonun adı ve açıklaması: özetin okuyucusu kolonu buradan tanır."""
    if not column.get("description"):
        return column["name"]
    return f"{column['name']} ({column['description']})"


def _is_key(column: dict) -> bool:
    """Anahtar kolon: bir yere bağlanan ya da kodu olan kolon - adı ya değerleri onu söyler."""
    return (
        bool(column.get("fk"))
        or bool(column.get("values"))
        or column["name"].upper().endswith(_CODE_SUFFIXES)
    )


def _terms_by_table(rules: list[dict]) -> dict[str, list[str]]:
    """Tablo adı -> `tables`ı o tabloyu söyleyen kuralların terimleri, kural dosyasının sırasıyla."""
    index: dict[str, list[str]] = {}
    for rule in rules:
        for name in rule.get("tables") or []:
            index.setdefault(name, []).append(rule["term"])
    return index


def _neighbours(graph, name: str, data: set[str]) -> list[str]:
    """Graphta 1 adımlık komşuların içinden yalnız veri tabloları, alfabede sıralı.

    Bir dolgunun komşusu olmak onu ilginç kılmaz (R3-9 aynı kuralı komşu genişletmesinde koyuyor).
    """
    found = set()
    for edge in graph.adjacency.get(name, []):
        other = edge.right_table if edge.left_table == name else edge.left_table
        if other != name and other in data:
            found.add(other)
    return sorted(found)


def _sentence(text: str) -> str:
    return text if text.endswith((".", "!", "?")) else text + "."
