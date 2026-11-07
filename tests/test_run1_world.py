# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R2-1: the Run 1 world is frozen - seed 42 has one fingerprint, and schema.json owns the table keys."""

import hashlib
import json

from bilgin.schema_map import doc, generator

RUN1_TABLES = (
    "TBLSTGRUP",
    "TBLSTSABIT",
    "TBLDEPO",
    "TBLPLASIYER",
    "TBLCASABIT",
    "TBLFATUIRS",
    "TBLSTHAR",
    "TBLCAHAR",
    "TBLSIPAMAS",
    "TBLSIPATRA",
)

# PLAN R2-1: what the Run 1 code produced before Run 2 started. A different value here means the
# golden answers were measured against another world.
RUN1_FINGERPRINT = "30e9e06c656d60503e6fb520bd116e1a5d86af606c2e4ecd5d20ff98ad598ec9"


def fingerprint(dataset: dict) -> str:
    """The R2-1 serialization: the Run 1 tables only, sorted keys, Turkish text unescaped."""
    payload = {name: dataset[name] for name in sorted(RUN1_TABLES)}
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def test_seed_42_replays_the_pinned_run1_fingerprint():
    assert fingerprint(generator.generate(42)) == RUN1_FINGERPRINT


def test_generate_returns_a_key_for_every_schema_table():
    dataset = generator.generate(42)
    names = [table["name"] for table in doc.load_schema()["tables"]]
    assert set(names) <= set(dataset)
    assert all(isinstance(dataset[name], list) for name in names)


def test_a_schema_table_the_generator_does_not_fill_is_an_empty_list(monkeypatch):
    """schema.json grows (R2-3/R2-4) before the generator fills the new tables."""
    before = generator.generate(42)
    tables = doc.load_schema()["tables"] + [
        {
            "name": "TBLDOVKUR",
            "description": "günlük döviz kuru",
            "module": "Döviz",
            "columns": [{"name": "KUR_TARIH", "type": "DATE"}],
        }
    ]
    monkeypatch.setattr(doc, "load_schema", lambda *args, **kwargs: {"tables": tables})

    dataset = generator.generate(42)

    assert dataset["TBLDOVKUR"] == []
    assert set(dataset) == {table["name"] for table in tables}
    assert {name: dataset[name] for name in RUN1_TABLES} == {name: before[name] for name in RUN1_TABLES}
