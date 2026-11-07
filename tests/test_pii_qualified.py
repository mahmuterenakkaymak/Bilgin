# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""PII ve salt okunur giriş betiği şemalı tablo adlarında da çalışır (PLAN R4-7).

Eski şemada her tablo dbo'da durduğu için maske yolu şema adını hiç bilmiyordu; R4-5 tablo adını
`Sales.Customers` yapınca üç şey birlikte değişmeli: PII haritasının anahtarı tam ad olmalı, iz
(trace) şemayı sqlglot'a iç içe vermiş olmalı ki takma ad ve CTE arkasından da gerçek kolona
varsın, ve betiğin DENY'leri tabloyu kendi şemasında vurmalı. Dünya elle kurulur ve gerçek
`LocalExecutor`'dan geçer: maskenin kendisi, filtresi ve betiğin T-SQL'i aynı kapıdan ölçülür.
"""

import re

import pytest
import sqlglot

from nl2sql.engine import login_script
from nl2sql.engine.executor import LocalExecutor
from nl2sql.policy import pii
from nl2sql.schema_map import build, doc

SCHEMA = {
    "tables": [
        {
            "name": "Sales.Customers",
            "description": "cari kartlar",
            "module": "Satış",
            "columns": [
                {"name": "CustomerID", "type": "INT", "nullable": False},
                {"name": "Name", "type": "NVARCHAR(50)", "nullable": False},
                {"name": "PhoneNumber", "type": "VARCHAR(20)", "nullable": True, "pii": "phone"},
            ],
        },
        {
            "name": "Sales.Orders",
            "description": "satış siparişleri",
            "module": "Satış",
            "columns": [
                {"name": "OrderID", "type": "INT", "nullable": False},
                {"name": "CustomerID", "type": "INT", "nullable": False},
                {"name": "Paid", "type": "DECIMAL(18,2)", "nullable": False},
            ],
        },
    ]
}

DATASET = {
    "Sales.Customers": [
        {"CustomerID": 10, "Name": "Şok Market", "PhoneNumber": "0212 345 67 89"},
        {"CustomerID": 20, "Name": "Başak Gıda", "PhoneNumber": "0532 111 22 34"},
    ],
    "Sales.Orders": [{"OrderID": 500, "CustomerID": 10, "Paid": 1250.5}],
}

MARKS = pii.column_map(SCHEMA)
SCRIPT = login_script.readonly_login_sql(SCHEMA, "nl2sql_ro")
NOT_IN = re.compile(r"NOT IN \(([^)]*)\)")


def not_in_names(script: str) -> set[str]:
    return set(re.findall(r"'([^']*)'", NOT_IN.search(script).group(1)))


@pytest.fixture(scope="module")
def database(tmp_path_factory):
    path = tmp_path_factory.mktemp("pii-qualified") / "test.db"
    build.write_sqlite(DATASET, SCHEMA, path)
    return path


@pytest.fixture
def executor(database, tmp_path):
    return LocalExecutor("sqlite", database, doc.allowlist(SCHEMA), tmp_path / "audit.jsonl", SCHEMA)


# ----------------------------------------------------------------- the map and the trace


def test_the_map_is_keyed_by_the_full_table_name():
    assert MARKS == {("SALES.CUSTOMERS", "PHONENUMBER"): "phone"}


def test_a_qualified_column_is_traced_by_its_full_name():
    traced = pii.trace("SELECT c.PhoneNumber FROM Sales.Customers AS c", SCHEMA)
    assert [(item.name, item.sources) for item in traced] == [
        ("PHONENUMBER", [("SALES.CUSTOMERS", "PHONENUMBER")])
    ]


def test_a_cte_rename_still_reaches_the_qualified_table():
    sql = "WITH C AS (SELECT PhoneNumber AS TEL FROM Sales.Customers) SELECT TEL FROM C"
    assert pii.trace(sql, SCHEMA)[0].sources == [("SALES.CUSTOMERS", "PHONENUMBER")]


# ----------------------------------------------------------------- the mask through the real door


def test_a_qualified_pii_column_leaves_masked(executor):
    result = executor.execute("SELECT c.PhoneNumber FROM Sales.Customers c ORDER BY c.CustomerID")
    assert result.error is None, result.error
    assert result.masked_columns == ["PhoneNumber"]
    assert [row[0] for row in result.rows] == ["*** ** 789", "*** ** 234"]


def test_a_cte_rename_is_masked_too(executor):
    result = executor.execute("WITH C AS (SELECT PhoneNumber AS TEL FROM Sales.Customers) SELECT TEL FROM C")
    assert result.error is None, result.error
    assert result.masked_columns == ["TEL"]
    assert {row[0] for row in result.rows} == {"*** ** 789", "*** ** 234"}


def test_a_join_masks_the_pii_side_and_keeps_the_other_raw(executor):
    sql = (
        "SELECT c.PhoneNumber, o.Paid FROM Sales.Customers c "
        "JOIN Sales.Orders o ON o.CustomerID = c.CustomerID ORDER BY o.OrderID"
    )
    result = executor.execute(sql)
    assert result.error is None, result.error
    assert result.masked_columns == ["PhoneNumber"]
    assert result.rows == [("*** ** 789", 1250.5)]


def test_a_clean_column_of_the_same_table_stays_raw(executor):
    result = executor.execute("SELECT Name FROM Sales.Customers ORDER BY CustomerID")
    assert result.error is None, result.error
    assert result.masked_columns == []
    assert [row[0] for row in result.rows] == ["Şok Market", "Başak Gıda"]


# ----------------------------------------------------------------- the filter side channel


def test_a_qualified_pii_column_used_as_a_filter_is_rejected(executor):
    result = executor.execute("SELECT Name FROM Sales.Customers WHERE PhoneNumber = '1'")
    assert result.error is not None and result.error.kind == "policy"
    assert result.error.message == "Filtrede PII kolon: SALES.CUSTOMERS.PHONENUMBER."


# ----------------------------------------------------------------- the login script


def test_the_column_deny_names_the_tables_own_schema():
    assert "EXEC('DENY SELECT (PhoneNumber) ON [Sales].[Customers] TO [nl2sql_ro]');" in SCRIPT


def test_a_bare_name_is_denied_in_dbo():
    schema = {
        "tables": [
            {"name": "PERSONEL", "columns": [{"name": "TCKN", "type": "VARCHAR(11)", "pii": "tckn"}]}
        ]
    }
    script = login_script.readonly_login_sql(schema, "rapor_ro")
    assert "EXEC('DENY SELECT (TCKN) ON [dbo].[PERSONEL] TO [rapor_ro]');" in script


def test_the_table_deny_compares_full_names():
    assert not_in_names(SCRIPT) == {"SALES.CUSTOMERS", "SALES.ORDERS"}
    assert "SCHEMA_NAME(schema_id) + '.' + name END" in SCRIPT


def test_the_script_still_parses_as_tsql():
    sqlglot.parse(SCRIPT, read="tsql")
