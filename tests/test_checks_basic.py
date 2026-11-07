# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R5-3 Result.tables ve R5-5 uyarıların ilk dördü: boş, tümü NULL, üst sınırda kesik, maskeli.

Dünya gerçek: ``build_db`` ile kurulmuş dosya, gerçek schema.json ve gerçek LocalExecutor, yani
uyarılar hazır bir nesneye değil kapıdan geçmiş bir sonuca bakıyor. Mesajların tamamı PLAN
Contracts satırının harfi harfine kendisi olduğu için testler düz metinle karşılaştırır.
"""

import pytest

from nl2sql import config
from nl2sql.engine import checks
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.eval import runner
from nl2sql.schema_map import build, doc

SCHEMA = doc.load_schema()
GOLDEN = runner.load_golden()
FULL = Budget(max_rows=100000)

EMPTY_SQL = "SELECT STOK_ADI FROM TBLSTSABIT WHERE STOK_ADI = 'OLMAYAN URUN'"
NULL_SQL = "SELECT CASE WHEN 1 = 2 THEN 'x' END AS BOS_KOLON FROM TBLSTSABIT"
# En büyük tek tablo 416 satır: TOP_N'e ulaşan tek şey satır sayısının çoğaldığı bir join.
CROSS_SQL = "SELECT A.STOK_KODU, B.STOK_KODU AS B_KOD FROM TBLSTHAR A, TBLSTHAR B"
TOP_SQL = "SELECT TOP 5 STOK_KODU FROM TBLSTHAR"
TCKN_SQL = "SELECT TCKN FROM TBLPERSONEL ORDER BY PERSONEL_KODU"


def build_db(tmp):
    path = tmp / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return build_db(tmp_path_factory.mktemp("checks-basic"))


@pytest.fixture
def executor(db, tmp_path):
    return LocalExecutor("sqlite", db, doc.allowlist(SCHEMA), tmp_path / "audit.jsonl", SCHEMA)


# ----------------------------------------------------------------- R5-3: okunan tablolar


@pytest.mark.parametrize("question", GOLDEN, ids=[line["id"] for line in GOLDEN])
def test_a_golden_result_names_the_tables_it_read(executor, question):
    result = executor.execute(question["sql"], FULL)
    assert result.error is None, result.error
    assert result.tables == sorted(t.upper() for t in question["requires_tables"])


def test_a_policy_reject_has_no_tables_and_no_warnings(executor):
    sql = "SELECT * FROM sys.objects"
    result = executor.execute(sql, FULL)
    assert result.error is not None and result.error.kind == "policy"
    assert result.tables == []
    assert checks.post_checks(sql, result) == []


# ----------------------------------------------------------------- R5-5: dört denetim


def test_an_empty_result_warns_only_that_it_is_empty(executor):
    result = executor.execute(EMPTY_SQL, FULL)
    assert result.error is None and result.row_count == 0
    assert checks.post_checks(EMPTY_SQL, result) == [
        checks.Warning("empty", "Sonuç boş: bu koşullara uyan kayıt yok.")
    ]


def test_a_column_that_is_always_null_is_named(executor):
    result = executor.execute(NULL_SQL, FULL)
    assert result.error is None and result.row_count > 0
    assert {row[0] for row in result.rows} == {None}
    assert checks.post_checks(NULL_SQL, result) == [
        checks.Warning(
            "all_null", "'BOS_KOLON' kolonunun tüm değerleri boş (NULL).", "BOS_KOLON"
        )
    ]


def test_the_policy_cap_warns_and_the_users_own_top_does_not(executor):
    capped = executor.execute(CROSS_SQL, FULL)
    assert capped.error is None and capped.row_count == config.TOP_N
    assert checks.post_checks(CROSS_SQL, capped) == [
        checks.Warning(
            "top_limited",
            f"Sonuç {config.TOP_N} satırlık üst sınırda kesildi; tamamı daha fazla olabilir.",
        )
    ]

    own = executor.execute(TOP_SQL, FULL)
    assert own.error is None and own.row_count == 5
    assert checks.post_checks(TOP_SQL, own) == []


def test_masked_columns_are_listed_by_one_warning(executor):
    result = executor.execute(TCKN_SQL, FULL)
    assert result.error is None and result.masked_columns == ["TCKN"]
    assert checks.post_checks(TCKN_SQL, result) == [
        checks.Warning("masked", "Maskelendi: TCKN — kişisel veri gösterilmez.")
    ]


def test_a_warning_carries_the_payload_shape():
    assert checks.Warning("all_null", "mesaj", "KOLON").to_dict() == {
        "code": "all_null",
        "message": "mesaj",
        "column": "KOLON",
    }
