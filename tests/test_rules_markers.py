"""R2-11 işaretçiler boşluğa karşı: işaretcisiz kural hiçbir şeyi sınamaz.

`markers: []` olan bir kural için "her işaretçi kuralı iddia eden SQL'de geçmeli" testi boş döngüde
hiç çalışmıyor; kural metni ile golden SQL birbirinden kopabiliyordu. Burada her kural en az bir
işaretçi taşımak zorunda, her işaretçi derlenir ve kuralı cite eden her golden SQL'i (boşlukları
tek uzaya indirgenmiş, büyük/küçük harf duyarsız) vurur.
"""

import re

import pytest

from nl2sql.eval.runner import load_golden
from nl2sql.schema_map import rules

RULES = rules.load_rules()
BY_ID = {rule["id"]: rule for rule in RULES}
GOLDEN = {line["id"]: line for line in load_golden()}
CITATIONS = [(qid, rule_id) for qid, line in GOLDEN.items() for rule_id in line["rules"]]


def collapse(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


@pytest.mark.parametrize("rule_id", sorted(BY_ID))
def test_no_rule_is_left_without_a_marker(rule_id):
    assert BY_ID[rule_id]["markers"], f"{rule_id} işaretcisiz: R2-11 bu kural için hiçbir şey sınamaz"


@pytest.mark.parametrize("rule_id", sorted(BY_ID))
def test_every_marker_compiles(rule_id):
    for marker in BY_ID[rule_id]["markers"]:
        assert marker.strip(), f"{rule_id} boş işaretçi taşıyor"
        re.compile(marker)


@pytest.mark.parametrize("qid,rule_id", CITATIONS)
def test_every_marker_matches_every_golden_line_citing_the_rule(qid, rule_id):
    sql = collapse(GOLDEN[qid]["sql"])
    for marker in BY_ID[rule_id]["markers"]:
        assert re.search(marker, sql, re.IGNORECASE), f"{qid} -> {rule_id} işaretçisi SQL'de yok: {marker}"
