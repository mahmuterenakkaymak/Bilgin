"""İş kuralları: yükleyici ve modelin okuduğu metin biçimi.

Kural, bir iş teriminin (ciro, net satış, geçen ay) bu şemada ne anlama geldiğini söyler; SQL'i
kuran yine modeldir. Bu yüzden metin hem terimi hem eş anlamlılarını hem de kalıbın kendisini
taşır - retrieval'ın bir soruyu doğru kurala bağlaması bu kelimelerle olur.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from nl2sql import config

# markers boş kalırsa R2-11'in "her işaretçi kuralı iddia eden SQL'de geçmeli" testi o kural için
# hiç çalışmıyor (boş döngü), yani kural metni ile golden SQL arasındaki bağ sessizce kopabiliyor.
# Her kural bu yüzden en az bir işaretçi taşır; tests/test_rules_markers.py bunu zorlar.
_LIST_FIELDS = ("synonyms", "tables", "markers")


def load_rules(path: str | Path = config.RULES_PATH) -> list[dict]:
    """The rules doc as a list; optional fields get their contract defaults."""
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    for rule in data["rules"]:
        rule.setdefault("sql_hint", "")
        for name in _LIST_FIELDS:
            rule.setdefault(name, [])
    return data["rules"]


def matching_rules(rules: list[dict], sql: str) -> list[str]:
    """Ids of the rules the SQL really carries: >= 1 marker and every marker hits, else never.

    The same reading R2-11 tests - markers are regexes written against the SQL the rule's author
    read, so whitespace collapses and case is ignored. A rule with no markers claims nothing,
    because nothing ties its text to any query.
    """
    text = re.sub(r"\s+", " ", sql).strip()
    return [
        rule["id"]
        for rule in rules
        if rule.get("markers")
        and all(re.search(marker, text, re.IGNORECASE) for marker in rule["markers"])
    ]


def rules_text(rules: list[dict]) -> str:
    """Every rule as its own block - the `full_rules` prompt section."""
    return "\n\n".join(rule_text(rule) for rule in rules)


def rule_text(rule: dict) -> str:
    """One rule as a block: term, synonyms in both languages, definition, SQL hint, tables.

    `synonyms_en` is optional (R8-13): a rule that does not carry it renders as it always did.
    """
    lines = [rule["term"]]
    if rule.get("synonyms"):
        lines.append("  Eş anlamlıları: " + ", ".join(rule["synonyms"]))
    if rule.get("synonyms_en"):
        lines.append("  Eş anlamlıları (İngilizce): " + ", ".join(rule["synonyms_en"]))
    if rule.get("definition"):
        lines.append("  Tanım: " + rule["definition"])
    if rule.get("sql_hint"):
        lines.append("  SQL ipucu: " + rule["sql_hint"])
    if rule.get("tables"):
        lines.append("  Tablolar: " + ", ".join(rule["tables"]))
    return "\n".join(lines)
