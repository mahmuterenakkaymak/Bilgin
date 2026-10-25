"""R4-7: `deny` kolonlar modelin hiç görmediği, politikanın hiç okutmadığı kolonlardır.

WWI'nin iki sırrı (`Application.People.HashedPassword` ve `.Photo`) üç katmandan birden gizlenir:
şema metni ile indeks dokümanından düşer, politika her gönderimini ve kapalı kolonu olan bir
tablonun yıldızını reddeder, giriş betiği de veritabanında kolon düzeyinde DENY yer. Testler gerçek
wwi şeması üzerinedir; iddia üç katmanın aynı kümesi taşıdığıdır - bir katmanın unuttuğu kolon
öbüründe görünür kalırdı. Kolonun kendisi şemada durmaya devam eder: gizlenen şey adıdır, kayıt.
"""

import re

import pytest
import sqlglot

from nl2sql.datasets import load_dataset
from nl2sql.engine import login_script
from nl2sql.index.docs import build_documents
from nl2sql.policy import pii, policy
from nl2sql.schema_map import doc

SCHEMA = load_dataset("wwi").schema()
ALLOWED = doc.allowlist(SCHEMA)
DENY = pii.deny_set(SCHEMA)
SECRETS = ("HashedPassword", "Photo")

# test_login_script'in kalıbı yalnız [dbo].[Tablo] yakalar; wwi tabloları kendi şemasıyla yazılır.
COLUMN_DENY = re.compile(r"DENY SELECT \(([^)]*)\) ON \[([^\]]+)\]\.\[([^\]]+)\] TO")


def check(sql):
    return policy.check(sql, ALLOWED, 100, deny=DENY)


def denied_columns(script: str) -> set[tuple[str, str, str]]:
    return {
        (schema, table, column)
        for columns, schema, table in COLUMN_DENY.findall(script)
        for column in columns.split(", ")
    }


def people_columns() -> set[str]:
    return {
        column["name"]
        for table in SCHEMA["tables"]
        if table["name"] == "Application.People"
        for column in table["columns"]
    }


# ----------------------------------------------------------------- the set


def test_the_two_people_secrets_are_the_denied_columns():
    assert DENY == {("APPLICATION.PEOPLE", "HASHEDPASSWORD"), ("APPLICATION.PEOPLE", "PHOTO")}


def test_a_denied_column_still_lives_in_the_schema_doc():
    """Gizlenen şey kolonun adı: üreteç onu yine kuracak, okuyan olmayacak."""
    assert set(SECRETS) <= people_columns()


def test_load_schema_defaults_deny_to_false(tmp_path):
    path = tmp_path / "schema.json"
    path.write_text(
        '{"tables": [{"name": "TABLO_T", "columns": [{"name": "KOLON", "type": "INT"}]}]}', encoding="utf-8"
    )
    assert doc.load_schema(path)["tables"][0]["columns"][0]["deny"] is False


# ----------------------------------------------------------------- model-facing text


def test_no_model_text_names_a_denied_column():
    for text in (doc.compact_text(SCHEMA), doc.table_detail(SCHEMA, ["Application.People"]), doc.full_text(SCHEMA)):
        for secret in SECRETS:
            assert secret not in text, secret


def test_the_readable_columns_of_that_table_stay_in_the_text():
    """Önceki test boş bir iddia olmasın: People okunur kolonlarıyla birlikte orada duruyor."""
    text = doc.table_detail(SCHEMA, ["Application.People"])
    assert "PersonID INT NOT NULL" in text and "FullName NVARCHAR(50)" in text


def test_no_index_doc_names_a_denied_column():
    docs = build_documents(SCHEMA, [])
    assert len(docs) == len(SCHEMA["tables"])
    for doc_ in docs:
        for secret in SECRETS:
            assert secret not in doc_.text, doc_.id


def test_the_denied_column_is_out_of_the_doc_but_its_table_is_not():
    people = next(doc_ for doc_ in build_documents(SCHEMA, []) if doc_.id == "table:Application.People")
    assert "PreferredName" in people.text
    assert all(secret not in people.text for secret in SECRETS)


# ----------------------------------------------------------------- policy: a reference


DENIED_SQL = [
    "SELECT HashedPassword FROM Application.People",
    "SELECT p.HashedPassword FROM Application.People AS p",
    "SELECT PersonID, Photo FROM Application.People AS p",
    "WITH s AS (SELECT HashedPassword FROM Application.People) SELECT PersonID FROM s",
    "SELECT PersonID FROM Application.People WHERE Photo IS NOT NULL",
    "SELECT PersonID FROM Application.People p WHERE p.HashedPassword = 'x'",
    "SELECT Photo FROM Application.People UNION SELECT PhoneNumber FROM Application.People",
]


@pytest.mark.parametrize("sql", DENIED_SQL)
def test_a_denied_column_is_rejected_wherever_it_is_written(sql):
    result = check(sql)
    assert not result.ok and result.sql is None
    assert result.reason.startswith("Erişimi kapalı kolon: APPLICATION.PEOPLE."), result.reason


def test_the_rejection_names_the_full_column_the_way_the_plan_writes_it():
    assert check(DENIED_SQL[0]).reason == "Erişimi kapalı kolon: APPLICATION.PEOPLE.HASHEDPASSWORD."


def test_without_a_deny_set_the_policy_reads_it_like_any_other_column():
    """`deny` verilmezse eski davranış: diğer kümelerin şemalarında kapalı kolon zaten yok."""
    assert policy.check("SELECT HashedPassword FROM Application.People", ALLOWED, 100).ok


# ----------------------------------------------------------------- policy: the star


STAR_SQL = [
    "SELECT * FROM Application.People",
    "SELECT p.* FROM Application.People AS p",
    "SELECT p.PersonID, p.* FROM Application.People AS p WHERE p.IsSalesPerson = 1",
    "SELECT * FROM Sales.Customers c JOIN Application.People p ON c.PrimaryContactPersonID = p.PersonID",
]


@pytest.mark.parametrize("sql", STAR_SQL)
def test_a_star_over_a_table_holding_one_is_rejected(sql):
    result = check(sql)
    assert not result.ok and result.reason == "Bu tabloda kapalı kolon var; kolonları adıyla yazın."


def test_a_count_star_opens_no_column():
    result = check("SELECT COUNT(*) AS KISI_SAYISI FROM Application.People")
    assert result.ok, result.reason


ALLOWED_SQL = [
    "SELECT PersonID, FullName FROM Application.People",
    "SELECT p.PersonID, p.FullName FROM Application.People AS p WHERE p.IsSalesPerson = 1",
    "WITH s AS (SELECT PersonID FROM Application.People) SELECT PersonID FROM s",
    "SELECT CustomerName FROM Sales.Customers",
]


@pytest.mark.parametrize("sql", ALLOWED_SQL)
def test_a_named_column_of_the_same_table_still_passes(sql):
    result = check(sql)
    assert result.ok, result.reason


# ----------------------------------------------------------------- login script


def test_the_script_denies_both_secrets_on_their_own_table():
    script = login_script.readonly_login_sql(SCHEMA, "nl2sql_ro")
    assert ("Application", "People", "HashedPassword") in denied_columns(script)
    assert ("Application", "People", "Photo") in denied_columns(script)


def test_the_column_deny_set_is_the_pii_columns_plus_the_denied_ones():
    script = login_script.readonly_login_sql(SCHEMA, "nl2sql_ro")
    assert denied_columns(script) == {
        (*doc.split_name(table["name"]), column["name"])
        for table in SCHEMA["tables"]
        for column in table["columns"]
        if column["pii"] or column["deny"]
    }


def test_the_qualified_script_is_still_real_tsql():
    sqlglot.parse(login_script.readonly_login_sql(SCHEMA, "nl2sql_ro"), read="tsql")
