# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Kural düzenleme: doğrulama, normalize ve atomik kayıt (PLAN R5-16).

Bir iş kuralı elle ya da arayüzden değiştirilirken bağlandığı şemayla çelişmemeli: kimlik benzersiz,
tablolar şemada, işaretçiler derlenen birer düzenli ifade olmalı. Doğrulama tek hatada durmak yerine
bütün kusurları birden döner - arayüz hepsini aynı anda gösterebilsin.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

from nl2sql import config
from nl2sql.i18n import t
from nl2sql.schema_map import doc

_ID = re.compile(r"[a-z0-9_]+")
_LIST_FIELDS = ("synonyms", "synonyms_en", "tables", "markers")


def validate_rule(
    rule: dict, schema: dict, rules: list[dict], editing_id: str | None = None, lang: str = "tr"
) -> list[dict]:
    """Bir kuralın kusurları: ``[{"field","message"}]`` ``lang``da; temiz kuralla boş liste.

    editing_id düzenlenmekte olan kuralın kimliğidir: kendi kimliğiyle çakışması benzersizlik ihlali
    sayılmaz. Kimlik kalıbı, boş terim/tanım, liste olmayan ya da metin olmayan alanlar, şemada
    olmayan tablolar ve derlenmeyen işaretçiler tek geçişte raporlanır.
    """
    errors: list[dict] = []
    rid = str(rule.get("id", "")).strip()
    if not _ID.fullmatch(rid):
        errors.append({"field": "id", "message": t("rules.id_pattern", lang)})
    if (editing_id is None or rid != editing_id) and any(other.get("id") == rid for other in rules):
        errors.append({"field": "id", "message": t("rules.duplicate", lang, id=rid)})
    if not str(rule.get("term", "")).strip():
        errors.append({"field": "term", "message": t("rules.term_empty", lang)})
    if not str(rule.get("definition", "")).strip():
        errors.append({"field": "definition", "message": t("rules.definition_empty", lang)})

    names = [table["name"] for table in schema["tables"]]
    for field in _LIST_FIELDS:
        value = rule.get(field, [])
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            errors.append({
                "field": field,
                "message": t("rules.list", lang, label=t(f"rules.label.{field}", lang)),
            })
            continue
        if field == "tables":
            for table in value:
                if table.strip() and doc.resolve_table(table, names) is None:
                    errors.append({"field": "tables", "message": t("rules.unknown_table", lang, table=table)})
        elif field == "markers":
            for marker in value:
                try:
                    re.compile(marker)
                except re.error:
                    errors.append({
                        "field": "markers",
                        "message": t("rules.marker_uncompiled", lang, marker=marker),
                    })
    return errors


def normalize_rule(rule: dict) -> dict:
    """Kuralı kayıt biçimine indirger: metinler kırpılır, boş liste öğeleri düşer, eksik alanlar
    sözleşme varsayılanlarıyla tamamlanır (sql_hint "", listeler []).

    ASSUMPTION: `synonyms_en` (R8-13) yalnız doluysa yazılır - alanı taşımayan bir kural diskte
    bugünkü sözlüğünün ta kendisi olarak kalır; okuyan taraf anahtarı bulamayınca [] sayıyor.
    """
    normalized = {
        "id": str(rule.get("id", "")).strip(),
        "term": str(rule.get("term", "")).strip(),
        "synonyms": _clean_list(rule.get("synonyms")),
        "definition": str(rule.get("definition", "")).strip(),
        "sql_hint": str(rule.get("sql_hint", "")).strip(),
        "tables": _clean_list(rule.get("tables")),
        "markers": _clean_list(rule.get("markers")),
    }
    english = _clean_list(rule.get("synonyms_en"))
    if english:
        normalized["synonyms_en"] = english
    return normalized


def save_rules(rules: list[dict], path: str | Path = config.RULES_PATH) -> None:
    """Kuralları atomik yazar: geçici dosya + os.replace, `{"rules": [...]}`, indent 2, UTF-8, sonda
    satır sonu. Sıra korunur; `rules.load_rules` aynı listeyi geri verir."""
    path = Path(path)
    text = json.dumps({"rules": rules}, ensure_ascii=False, indent=2) + "\n"
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".json.tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except OSError:
        Path(tmp).unlink(missing_ok=True)
        raise


def _clean_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]
