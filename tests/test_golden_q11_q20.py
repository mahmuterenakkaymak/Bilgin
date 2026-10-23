"""T42: Q11-Q20 kurulu dünyada policy kapısından geçer, satır döndürür ve Python doğrusuna eşittir.

Altın SQL'ler LocalExecutor'dan geçer (policy -> çeviri -> SQLite); doğrular eval.reference'dan
gelir. Karşılaştırma eval bütçesiyle yapılır ki ne golden'ın ne doğrunun satırı kesilmesin.
"""

from decimal import ROUND_HALF_UP, Decimal

import pytest

from eval import reference
from nl2sql import config
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.eval.runner import load_golden
from nl2sql.policy import policy
from nl2sql.schema_map import build, doc, generator

IDS = [f"Q{i:02d}" for i in range(11, 21)]
BY_ID = {line["id"]: line for line in load_golden()}
TABLES = doc.allowlist(doc.load_schema())

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
    """ordered=True sırayı da karşılaştırır (Q13); değilse çok küme olarak sıralanır."""
    values = [tuple(map(cell, row)) for row in rows]
    return values if ordered else sorted(values, key=repr)


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    return build_db(tmp_path_factory.mktemp("q11-q20"))


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
