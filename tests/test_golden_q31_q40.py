"""T44: Q31-Q40 kurulu dünyada policy kapısından geçer, satır döndürür ve Python doğrusuna eşittir.

Altın SQL'ler LocalExecutor'dan geçer (policy -> çeviri -> SQLite); doğrular eval.reference'dan
gelir. Karşılaştırma eval bütçesiyle yapılır ki ne golden'ın ne doğrunun satırı kesilmesin.
R2-15 etiket hedefleri ayrıca tüm altın küme (Q01-Q40) üzerinden burada denetlenir.
"""

import json
from decimal import ROUND_HALF_UP, Decimal

import pytest

from eval import reference
from nl2sql import config
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.eval.runner import load_golden
from nl2sql.policy import policy
from nl2sql.schema_map import build, doc, generator

IDS = [f"Q{i:02d}" for i in range(31, 41)]
GOLDEN = load_golden()
BY_ID = {line["id"]: line for line in GOLDEN}
TABLES = doc.allowlist(doc.load_schema())

# R2-15 hedefleri: Q01-Q40 bu etiketleri en az bu kadar taşır; T44 needs_values boşluğunu kapatır.
TAG_MINIMUMS = {"needs_rule": 8, "multi_join": 8, "distractor": 8, "needs_values": 8, "archive": 5}

# Eval karşılaştırma bütçesi: ne golden'ın ne doğrunun satırı kesilmesin (PLAN Decision 8).
COMPARE = Budget(max_rows=config.COMPARE_MAX_ROWS)


def build_db(tmp):
    """Tohum 42'nin SQLite dünyası ve o dünyaya bakan tek kapı."""
    path = tmp / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return LocalExecutor("sqlite", path, audit_path=tmp / "audit.jsonl")


def cell(value):
    """Sayıları 2 haneye indirir; yığma ondalık farkı doğruyu SQL ile kapıştırmasın."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    stable = Decimal(repr(round(float(value), 6)))
    return float(stable.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def comparable(rows, ordered):
    """ordered=True sırayı da karşılaştırır; değilse çok küme olarak sıralanır."""
    values = [tuple(map(cell, row)) for row in rows]
    return values if ordered else sorted(values, key=repr)


def tagged(tag):
    return {line["id"] for line in GOLDEN if tag in line["tags"]}


def trap_tags():
    text = config.TRAPS_PATH.read_text(encoding="utf-8")
    return {f"trap:{json.loads(line)['trap']}" for line in text.splitlines() if line.strip()}


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    return build_db(tmp_path_factory.mktemp("q31-q40"))


@pytest.fixture(scope="module")
def dataset():
    return generator.generate(config.SEED)


@pytest.mark.parametrize("qid", IDS)
def test_the_question_has_a_pure_python_reference(qid):
    assert qid in reference.REFERENCES, f"{qid} için doğrul yok"


@pytest.mark.parametrize("qid", IDS)
def test_golden_sql_passes_the_policy(qid):
    verdict = policy.check(BY_ID[qid]["sql"], TABLES)
    assert verdict.ok, f"{qid}: {verdict.reason}"


@pytest.mark.parametrize("qid", IDS)
def test_executor_answer_equals_the_reference(qid, executor, dataset):
    line = BY_ID[qid]
    result = executor.execute(line["sql"], COMPARE, qid)
    assert result.error is None, f"{qid}: {result.error}"
    assert result.rows, f"{qid} boş döndü; soru hiçbir şey ölçmüyor"
    expected = comparable(reference.REFERENCES[qid](dataset), line["ordered"])
    assert comparable(result.rows, line["ordered"]) == expected, f"{qid} SQL sonucu Python doğrulundan farklı"


def test_the_first_forty_questions_are_written():
    assert {f"Q{i:02d}" for i in range(1, 41)} <= set(BY_ID)


@pytest.mark.parametrize("tag", sorted(TAG_MINIMUMS))
def test_the_tag_meets_its_target(tag):
    found = len(tagged(tag))
    assert found >= TAG_MINIMUMS[tag], f"{tag} etiketi {found} soruda var, hedef {TAG_MINIMUMS[tag]}"


def test_every_trap_tag_is_measured_by_a_question():
    measured = {tag for line in GOLDEN for tag in line["tags"]}
    missing = sorted(trap_tags() - measured)
    assert not missing, f"hiçbir soru bu tuzakları ölçmüyor: {missing}"
