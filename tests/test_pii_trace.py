# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""trace() her çıktı kolonunu gerçek kaynak kolonlarına kadar izler; izlenemeyen None döner (R3-6)."""

from nl2sql.policy import pii
from nl2sql.schema_map import doc

SCHEMA = doc.load_schema()


def one(sql: str, position: int = 0) -> pii.Trace:
    return pii.trace(sql, SCHEMA)[position]


def sources(sql: str, position: int = 0):
    return one(sql, position).sources


def test_count_is_the_whitelisted_aggregate():
    assert one("SELECT COUNT(*) AS X FROM PERSONEL").aggregate == "count"
    assert sources("SELECT COUNT(*) AS X FROM PERSONEL") == []


def test_ambiguous_column_is_not_resolved():
    # IL lives in both tables of the join, so the lineage cannot pick one and says nothing.
    sql = "SELECT IL FROM PERSONEL P JOIN HESAP_SUBE C ON C.HESAP_KOD = P.PERSONEL_KODU"
    assert sources(sql) is None


def test_unknown_alias_is_not_resolved():
    assert sources("SELECT Z.TCKN FROM PERSONEL P") is None


def test_table_outside_the_schema_doc_is_not_resolved():
    assert sources("SELECT FOO FROM GIZLI_TABLO") is None


def test_two_output_columns_sharing_a_name_are_not_trusted():
    assert pii.trace("SELECT IL AS X, AD_SOYAD AS X FROM PERSONEL", SCHEMA) == []


def test_sql_that_is_not_a_select_cannot_be_traced():
    assert pii.trace("DROP TABLE PERSONEL", SCHEMA) == []
    assert pii.trace("", SCHEMA) == []
