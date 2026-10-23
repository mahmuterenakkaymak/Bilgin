"""T77 (R3-1): altın kümenin tümü tek yerde ölçülür — policy, çeviri, executor ve Python doğrusu.

Q11-Q20 / Q21-Q30 / Q31-Q40 için üç ayrı dosyanın aynı üç kontrolü tekrarlaması kaldırıldı: tek
parametrik test eval/golden.jsonl'daki her satırı policy'den geçirir, tek bir SQLite ifadesine
çevirir, kurulu dünyada COMPARE bütçesiyle çalıştırır ve 2 haneye indirilmiş Python doğrulundan
farksız olduğunu doğrular; sıra yalnız satır `ordered` ise karşılaştırılır. Kimlikler dosyadan
okunur, sayı sabitlenmez (R3-12).
"""

from decimal import ROUND_HALF_UP, Decimal

import pytest
from sqlglot import transpile

from eval import reference
from nl2sql import config
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.eval.runner import load_golden
from nl2sql.policy import policy
from nl2sql.schema_map import build, doc, generator

GOLDEN = load_golden()
IDS = [line["id"] for line in GOLDEN]
BY_ID = {line["id"]: line for line in GOLDEN}
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
    """ordered=True sırayı da karşılaştırır; değilse çok küme olarak sıralanır."""
    values = [tuple(map(cell, row)) for row in rows]
    return values if ordered else sorted(values, key=repr)


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    return build_db(tmp_path_factory.mktemp("golden-all"))


@pytest.fixture(scope="module")
def dataset():
    return generator.generate(config.SEED)


@pytest.mark.parametrize("qid", IDS)
def test_every_golden_question_is_measured(qid, executor, dataset):
    line = BY_ID[qid]
    assert qid in reference.REFERENCES, f"{qid} için doğrul yok"

    verdict = policy.check(line["sql"], TABLES)
    assert verdict.ok, f"{qid}: {verdict.reason}"

    # ASSUMPTION (R3-1): "transpile" bir birleşim kontrolüdür ve buraya taşındı;
    # test_golden_reference.py'deki aynı parametrik test artık yok.
    statements = transpile(line["sql"], read="tsql", write="sqlite")
    assert len(statements) == 1, f"{qid} tek bir SQLite ifadesine çevrilmiyor"

    result = executor.execute(line["sql"], COMPARE, qid)
    assert result.error is None, f"{qid}: {result.error}"
    assert result.rows, f"{qid} boş döndü; soru hiçbir şey ölçmüyor"
    expected = comparable(reference.REFERENCES[qid](dataset), line["ordered"])
    assert comparable(result.rows, line["ordered"]) == expected, f"{qid} SQL sonucu Python doğrulundan farklı"
