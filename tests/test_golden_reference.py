import json
import sqlite3
from decimal import ROUND_HALF_UP, Decimal

import pytest
from sqlglot import exp, parse, transpile

from eval import reference
from nl2sql import config
from nl2sql.schema_map import build, generator

FIELDS = {"id", "question", "sql", "ordered", "trap", "notes", "review"}


def load_golden():
    text = config.GOLDEN_PATH.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


GOLDEN = load_golden()
IDS = [line["id"] for line in GOLDEN]
BY_ID = {line["id"]: line for line in GOLDEN}


@pytest.fixture(scope="module")
def dataset():
    return generator.generate(config.SEED)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("golden") / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


def to_sqlite(sql):
    statements = transpile(sql, read="tsql", write="sqlite")
    assert len(statements) == 1
    return statements[0]


def run(path, sql):
    conn = sqlite3.connect(path)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def cell(value):
    """Sayıları 2 haneye indirir; 6 haneye yumuşatma, yığma hatanın yuvarlamayı devirmesini engeller."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return value
    stable = Decimal(repr(round(float(value), 6)))
    return float(stable.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def comparable(rows, ordered):
    """ordered=True sırayı da karşılaştırır (PLAN'da yalnız Q02); değilse çok küme."""
    values = [tuple(map(cell, row)) for row in rows]
    return values if ordered else sorted(values, key=repr)


def assert_same_result(qid, db, dataset):
    line = BY_ID[qid]
    actual = comparable(run(db, to_sqlite(line["sql"])), line["ordered"])
    expected = comparable(reference.REFERENCES[qid](dataset), line["ordered"])
    assert actual == expected, f"{qid} SQL sonucu Python doğrulundan farklı"


# ----------------------------------------------------------------- golden file shape


def test_golden_has_the_ten_planned_questions():
    assert IDS == [f"Q{i:02d}" for i in range(1, 11)]
    assert len(set(IDS)) == len(IDS)


def test_every_golden_line_is_complete_and_pending():
    for line in GOLDEN:
        assert set(line) == FIELDS, line["id"]
        assert line["question"].strip() and line["sql"].strip(), line["id"]
        assert line["notes"].strip() and line["review"] == "pending", line["id"]
        assert isinstance(line["ordered"], bool), line["id"]


def test_every_question_except_the_control_one_names_its_trap():
    trapped = {line["trap"] for line in GOLDEN if line["trap"]}
    assert len(trapped) == 9, "her tuzak tek bir soruya bağlı olmalı"
    assert BY_ID["Q01"]["trap"] == "", "Q01 PLAN'da tuzaksız kontrol sorusu"


def test_references_cover_exactly_the_golden_questions():
    assert set(reference.REFERENCES) == set(IDS)


@pytest.mark.parametrize("qid", IDS)
def test_golden_sql_is_a_single_tsql_select(qid):
    trees = parse(BY_ID[qid]["sql"], read="tsql")
    assert len(trees) == 1 and isinstance(trees[0], exp.Select), qid


@pytest.mark.parametrize("qid", IDS)
def test_golden_sql_transpiles_to_one_sqlite_statement(qid):
    assert len(transpile(BY_ID[qid]["sql"], read="tsql", write="sqlite")) == 1


# ----------------------------------------------------------------- golden == reference


@pytest.mark.parametrize("qid", IDS)
def test_every_question_actually_measures_something(qid, db, dataset):
    assert reference.REFERENCES[qid](dataset), f"{qid} boş sonuç veriyor; soru bir şey ölçmüyor"


@pytest.mark.parametrize("qid", IDS)
def test_golden_sql_matches_the_python_reference(qid, db, dataset):
    assert_same_result(qid, db, dataset)


def test_the_whole_set_is_reproducible_on_a_fresh_build(tmp_path, dataset):
    """Aynı tohumla ikinci bir kurulum da doğrula eşit olmalı (build -> SQL -> reference)."""
    path = tmp_path / "again.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    for qid in IDS:
        assert_same_result(qid, path, dataset)
