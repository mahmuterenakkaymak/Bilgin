"""R2-15 golden contract: her satır hangi etiketi, tabloyu ve kuralı iddia ettiğini kendisi söyler.

Satırın beyanı SQL'in kendisiyle doğrulanır: etiketler sözlükten gelir, requires_tables
sqlglot'ın CTE farkıyla bulduğu gerçek tablolardır, multi_join ve archive o tablolardan türer.
Böylece retrieval ve join-graph ölçümleri beyan edilenle değil, sorgunun gerçekten dokunduğu
şeylerle hesaplanır.
"""

import json

import pytest

from nl2sql import config
from nl2sql.eval.runner import load_golden
from nl2sql.policy import policy
from nl2sql.schema_map import doc

# ASSUMPTION: needs_values = soru modelin bakması gereken bir kayıtlı değere süzüyor (bir il
# yazımı, bir grup adı), distractor = gerçek tablonun yanında şaşırtan bir tablo duruyor; R2-15
# yalnız trap/needs_rule/multi_join/archive bağıntılarını sabitlediği için bu ikisi burada
# sözlükte durur, Q11-Q40 doldurur.
EXTRA_TAGS = ("needs_rule", "multi_join", "distractor", "needs_values", "archive")
ARCHIVE_TABLE = "STOK_HAREKET_ARSIV"


def trap_names():
    text = config.TRAPS_PATH.read_text(encoding="utf-8")
    return {json.loads(line)["trap"] for line in text.splitlines() if line.strip()}


GOLDEN = load_golden()
IDS = [line["id"] for line in GOLDEN]
BY_ID = {line["id"]: line for line in GOLDEN}
TABLES = doc.allowlist(doc.load_schema())
VOCABULARY = {f"trap:{name}" for name in trap_names()} | set(EXTRA_TAGS)


def test_ids_are_unique_and_sequential():
    assert IDS == [f"Q{number:02d}" for number in range(1, len(IDS) + 1)]


@pytest.mark.parametrize("qid", IDS)
def test_tags_come_from_the_vocabulary(qid):
    tags = BY_ID[qid]["tags"]
    assert len(tags) == len(set(tags)), f"{qid} aynı etiketi iki kez yazıyor"
    assert set(tags) <= VOCABULARY, f"{qid} sözlükte olmayan etiket taşıyor"


@pytest.mark.parametrize("qid", IDS)
def test_the_trap_tag_is_the_trap_field(qid):
    line = BY_ID[qid]
    named = [tag for tag in line["tags"] if tag.startswith("trap:")]
    expected = [f"trap:{line['trap']}"] if line["trap"] else []
    assert named == expected, qid


@pytest.mark.parametrize("qid", IDS)
def test_needs_rule_tag_is_the_rules_field(qid):
    line = BY_ID[qid]
    assert ("needs_rule" in line["tags"]) == bool(line["rules"]), qid


@pytest.mark.parametrize("qid", IDS)
def test_multi_join_tag_is_three_real_tables(qid):
    line = BY_ID[qid]
    assert ("multi_join" in line["tags"]) == (len(set(line["requires_tables"])) >= 3), qid


@pytest.mark.parametrize("qid", IDS)
def test_archive_tag_is_the_archive_table(qid):
    line = BY_ID[qid]
    assert ("archive" in line["tags"]) == (ARCHIVE_TABLE in line["requires_tables"]), qid
