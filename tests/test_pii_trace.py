"""trace() her çıktı kolonunu gerçek kaynak kolonlarına kadar izler; izlenemeyen None döner (R3-6)."""

from nl2sql.policy import pii
from nl2sql.schema_map import doc

SCHEMA = doc.load_schema()


def one(sql: str, position: int = 0) -> pii.Trace:
    return pii.trace(sql, SCHEMA)[position]


def sources(sql: str, position: int = 0):
    return one(sql, position).sources


def test_direct_column():
    assert sources("SELECT TCKN FROM TBLPERSONEL") == [("TBLPERSONEL", "TCKN")]


def test_alias_keeps_the_source():
    trace = one("SELECT TCKN AS KIMLIK FROM TBLPERSONEL")
    assert (trace.name, trace.sources) == ("KIMLIK", [("TBLPERSONEL", "TCKN")])


def test_cte_rename_keeps_the_source():
    sql = "WITH P AS (SELECT TCKN AS KIMLIK FROM TBLPERSONEL) SELECT KIMLIK FROM P"
    assert sources(sql) == [("TBLPERSONEL", "TCKN")]


def test_cast_and_convert_keep_the_source():
    assert sources("SELECT CAST(TCKN AS VARCHAR(20)) AS X FROM TBLPERSONEL") == [("TBLPERSONEL", "TCKN")]
    assert sources("SELECT CONVERT(VARCHAR(20), IBAN) AS X FROM TBLPERSONEL") == [("TBLPERSONEL", "IBAN")]


def test_substring_left_right_keep_the_source():
    for expr in ("SUBSTRING(TCKN, 1, 4)", "LEFT(TCKN, 4)", "RIGHT(TCKN, 4)"):
        assert sources(f"SELECT {expr} AS X FROM TBLPERSONEL") == [("TBLPERSONEL", "TCKN")], expr


def test_case_when_collects_every_branch():
    sql = "SELECT CASE WHEN AKTIF = 'E' THEN TCKN ELSE IBAN END AS X FROM TBLPERSONEL"
    assert sources(sql) == [("TBLPERSONEL", "AKTIF"), ("TBLPERSONEL", "IBAN"), ("TBLPERSONEL", "TCKN")]


def test_concat_with_a_non_pii_column_keeps_the_pii_source():
    sql = "SELECT CONCAT(AD_SOYAD, ' / ', GOREV_UNVANI) AS X FROM TBLPERSONEL"
    assert sources(sql) == [("TBLPERSONEL", "AD_SOYAD"), ("TBLPERSONEL", "GOREV_UNVANI")]


def test_plus_operator_keeps_the_pii_source():
    sql = "SELECT AD_SOYAD + GOREV_UNVANI AS X FROM TBLPERSONEL"
    assert sources(sql) == [("TBLPERSONEL", "AD_SOYAD"), ("TBLPERSONEL", "GOREV_UNVANI")]


def test_union_puts_a_pii_column_into_a_clean_position():
    sql = "SELECT IL AS X FROM TBLPERSONEL UNION ALL SELECT AD_SOYAD AS X FROM TBLPERSONEL"
    assert sources(sql) == [("TBLPERSONEL", "AD_SOYAD"), ("TBLPERSONEL", "IL")]
    assert one(sql).aggregate is None


def test_union_of_two_counts_stays_a_count():
    sql = "SELECT COUNT(*) AS X FROM TBLPERSONEL UNION ALL SELECT COUNT(BRUT_TUTAR) FROM TBLMAAS"
    assert one(sql).aggregate == "count"
    assert sources(sql) == [("TBLMAAS", "BRUT_TUTAR")]


def test_scalar_subquery_is_traced():
    sql = "SELECT (SELECT MAX(BRUT_TUTAR) FROM TBLMAAS) AS X"
    assert sources(sql) == [("TBLMAAS", "BRUT_TUTAR")]
    assert one(sql).aggregate is None


def test_derived_table_is_traced():
    sql = "SELECT D.K FROM (SELECT IBAN AS K FROM TBLPERSONEL) AS D"
    assert sources(sql) == [("TBLPERSONEL", "IBAN")]


def test_max_over_a_salary_keeps_its_source():
    trace = one("SELECT MAX(BRUT_TUTAR) AS X FROM TBLMAAS")
    assert (trace.aggregate, trace.sources) == ("max", [("TBLMAAS", "BRUT_TUTAR")])


def test_count_is_the_whitelisted_aggregate():
    assert one("SELECT COUNT(*) AS X FROM TBLPERSONEL").aggregate == "count"
    assert sources("SELECT COUNT(*) AS X FROM TBLPERSONEL") == []


def test_count_distinct_keeps_the_source_for_the_whitelist_check():
    trace = one("SELECT COUNT(DISTINCT TCKN) AS X FROM TBLPERSONEL")
    assert (trace.aggregate, trace.sources) == ("count", [("TBLPERSONEL", "TCKN")])


def test_string_agg_keeps_its_source():
    trace = one("SELECT STRING_AGG(TCKN, ',') AS X FROM TBLPERSONEL")
    assert trace.aggregate != "count"
    assert trace.sources == [("TBLPERSONEL", "TCKN")]


def test_ambiguous_column_is_not_resolved():
    # IL lives in both tables of the join, so the lineage cannot pick one and says nothing.
    sql = "SELECT IL FROM TBLPERSONEL P JOIN TBLCARISUBE C ON C.CARI_KOD = P.PERSONEL_KODU"
    assert sources(sql) is None


def test_unknown_alias_is_not_resolved():
    assert sources("SELECT Z.TCKN FROM TBLPERSONEL P") is None


def test_table_outside_the_schema_doc_is_not_resolved():
    assert sources("SELECT FOO FROM TBLGIZLI") is None


def test_columns_come_back_in_select_order():
    traced = pii.trace("SELECT PERSONEL_KODU, TCKN, AD_SOYAD FROM TBLPERSONEL", SCHEMA)
    assert [trace.name for trace in traced] == ["PERSONEL_KODU", "TCKN", "AD_SOYAD"]
    assert traced[0].sources == [("TBLPERSONEL", "PERSONEL_KODU")]
    assert traced[2].sources == [("TBLPERSONEL", "AD_SOYAD")]


def test_star_expands_to_every_column_in_schema_order():
    columns = next(table["columns"] for table in SCHEMA["tables"] if table["name"] == "TBLPERSONEL")
    traced = pii.trace("SELECT * FROM TBLPERSONEL", SCHEMA)
    assert [(trace.name, trace.sources) for trace in traced] == [
        (column["name"], [("TBLPERSONEL", column["name"])]) for column in columns
    ]


def test_two_output_columns_sharing_a_name_are_not_trusted():
    assert pii.trace("SELECT IL AS X, AD_SOYAD AS X FROM TBLPERSONEL", SCHEMA) == []


def test_sql_that_is_not_a_select_cannot_be_traced():
    assert pii.trace("DROP TABLE TBLPERSONEL", SCHEMA) == []
    assert pii.trace("", SCHEMA) == []
