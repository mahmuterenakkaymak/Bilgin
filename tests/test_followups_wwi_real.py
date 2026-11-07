# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T304: ``wwi_real`` ardışık soru zincirleri (PLAN R7-13, Contracts "followup chain").

Kümenin satırları gerçek WideWorldImporters'ta durur ve zincirler o sunucuda tur tur ancak
elle koşulur (T312); burada ölçüm yok, satırların sözleşmesi var: şekil, tekil kimlikler,
kümenin allowlist'i + PII/red kümeleriyle policy'den geçen golden SQL, beyan edilen her etiketin
dosyada geçmesi, chart-only turun bir önceki turun SQL'ini yinelenmesi ve ``uses_turns``'in
geriye dönük işaretleridir. Test sunucuya bağlanmaz.
"""

import pytest

from nl2sql.datasets import load_dataset
from nl2sql.policy import pii, policy
from nl2sql.schema_map import doc

DATASET = load_dataset("wwi_real")
SCHEMA = DATASET.schema()
ALLOWLIST = doc.allowlist(SCHEMA)
CHAINS = DATASET.followups()
IDS = [chain["id"] for chain in CHAINS]
TURNS = [(chain, number, turn) for chain in CHAINS for number, turn in enumerate(chain["turns"], start=1)]
TURN_FIELDS = {"question", "sql", "uses_turns", "tags"}

# Etiket sözlüğü sentetik kümeyle aynı (R7-10/R7-13); ``top`` ilk turun süprülen biçimini söyler.
TURN_TAGS = {"entity", "set", "period", "filter", "chart_only", "standalone", "top"}
REQUIRED_TAGS = {"entity", "set", "period", "filter", "chart_only", "standalone"}


def used_tags() -> set[str]:
    return {tag for chain in CHAINS for turn in chain["turns"] for tag in turn["tags"]}


def test_the_set_is_wired_into_the_dataset():
    assert DATASET.followups_path == DATASET.root / "followups.jsonl"
    assert DATASET.followups_path.is_file()
    assert 8 <= len(CHAINS) <= 12, IDS


def test_every_line_has_the_contract_shape():
    for chain in CHAINS:
        assert {"id", "tags", "turns"} <= set(chain)
        assert chain["id"] and chain["tags"] and chain["turns"]
        assert 2 <= len(chain["turns"]) <= 3, f"{chain['id']}: {len(chain['turns'])} tur"
        for turn in chain["turns"]:
            assert TURN_FIELDS == set(turn), f"{chain['id']}: {sorted(turn)}"
            assert turn["question"].strip() and turn["sql"].strip()
            assert isinstance(turn["tags"], list)
            assert all(isinstance(n, int) and n >= 1 for n in turn["uses_turns"])


def test_ids_are_unique():
    assert len(set(IDS)) == len(IDS), IDS


@pytest.mark.parametrize("chain,number,turn", TURNS, ids=[f"{c['id']}/{n}" for c, n, _ in TURNS])
def test_turn_sql_passes_the_policy(chain, number, turn):
    verdict = policy.check(
        turn["sql"],
        ALLOWLIST,
        pii=pii.column_map(SCHEMA),
        deny=pii.deny_set(SCHEMA),
        keys=pii.count_keys(SCHEMA),
    )
    assert verdict.ok, f"{chain['id']} tur {number}: {verdict.reason}"
    assert verdict.tables <= ALLOWLIST, f"{chain['id']} tur {number}"


def test_tags_come_from_the_vocabulary_and_every_required_one_appears():
    used = used_tags()
    assert used <= TURN_TAGS, used - TURN_TAGS
    assert REQUIRED_TAGS <= used, REQUIRED_TAGS - used


@pytest.mark.parametrize("chain,number,turn", TURNS, ids=[f"{c['id']}/{n}" for c, n, _ in TURNS])
def test_uses_turns_point_at_earlier_turns(chain, number, turn):
    assert all(n < number for n in turn["uses_turns"]), f"{chain['id']} tur {number}"


@pytest.mark.parametrize("chain,number,turn", TURNS, ids=[f"{c['id']}/{n}" for c, n, _ in TURNS])
def test_chart_only_turns_repeat_the_previous_sql(chain, number, turn):
    if "chart_only" not in turn["tags"]:
        return
    assert turn["sql"] == chain["turns"][number - 2]["sql"], f"{chain['id']} tur {number}"
    assert turn["uses_turns"] == [number - 1], f"{chain['id']} tur {number}"


def test_the_standalone_turn_stands_alone_in_the_middle():
    # "Peki toplam müşteri sayısı?" önceki tura bakmaz; zincirin ortasında tek başına durur.
    standalone = [(chain, number) for chain, number, turn in TURNS if "standalone" in turn["tags"]]
    assert len(standalone) == 1, standalone
    chain, number = standalone[0]
    assert chain["turns"][number - 1]["question"] == "Peki toplam müşteri sayısı?"
    assert chain["turns"][number - 1]["uses_turns"] == []
    assert 1 < number < len(chain["turns"]), f"{chain['id']} tur {number}"


def test_the_entity_follow_ups_answer_a_previous_turn():
    # Varlık takibi bir önceki turun cevabına döner: müşteri, ürün, tedarikçi ve fatura zincirleri.
    follow_ups = [
        (chain["id"], number)
        for chain, number, turn in TURNS
        if "entity" in turn["tags"] and turn["uses_turns"]
    ]
    assert len(follow_ups) >= 4, follow_ups
