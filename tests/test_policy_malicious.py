# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Saldırı kümesi: tests/data/malicious.jsonl satırlarının hiçbiri policy'den geçmemeli.

Reddin bir nedeni olmalı (model o nedeni görüp SQL'i düzeltebilir), ama neden asla
çalıştırılacak bir SQL taşımaz.
"""

import json
from pathlib import Path

import pytest

from nl2sql import config
from nl2sql.policy import policy
from nl2sql.schema_map import doc

ALLOWED = doc.allowlist(doc.load_schema())
CASES = [
    json.loads(line)
    for line in (Path(__file__).parent / "data" / "malicious.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]

# Küme budanıp bir saldırı ailesi kaybolursa burada görünsün.
FAMILIES = {
    "multi_statement",
    "comment_injection",
    "mutation_in_cte",
    "sys_via_union",
    "cte_shadowing",
    "quoted_names",
    "case_tricks",
    "select_into",
    "exec",
    "cross_db",
    "openrowset",
    "table_valued_function",
}


def check(sql):
    return policy.check(sql, ALLOWED, config.TOP_N)


def test_the_corpus_covers_every_attack_family():
    assert len(CASES) >= 20
    assert len({case["id"] for case in CASES}) == len(CASES)
    assert FAMILIES <= {case["category"] for case in CASES}


