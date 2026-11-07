# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""ORDER BY'da pii kolon, sonda gösterilse de reddedilir (R3-6).

Maske ve sıralama ayrı işler: maske değerin kendisini gizler, ORDER BY ise o değerin sırasını
sonuca taşır. PLAN R3-6 WHERE / JOIN ON / GROUP BY / ORDER BY için tek bir kural koyar ve
ORDER BY'a hiçbir istisna tanımaz; "kolon zaten seçilmiş" bir muafiyet üretmez. Burada
reddedilen sorgunun maskesi hiç çalışmaz - politika veritabanına dokunmadan durdurur.
"""

import pytest

from nl2sql import config
from nl2sql.policy import pii, policy
from nl2sql.schema_map import doc

SCHEMA = doc.load_schema()
ALLOWED = doc.allowlist(SCHEMA)
MARKS = pii.column_map(SCHEMA)


def check(sql):
    return policy.check(sql, ALLOWED, config.TOP_N, MARKS)


def reason(sql) -> str:
    result = check(sql)
    assert not result.ok and result.sql is None, sql
    return result.reason


# ------------------------------------------------------- showing a column buys its order nothing


def test_order_by_a_shown_pii_column_is_rejected():
    assert reason("SELECT TCKN FROM TBLPERSONEL ORDER BY TCKN") == "Filtrede PII kolon: TBLPERSONEL.TCKN."


def test_order_by_an_aliased_shown_pii_column_is_rejected():
    assert reason("SELECT P.TCKN AS KIMLIK FROM TBLPERSONEL P ORDER BY P.TCKN") == (
        "Filtrede PII kolon: TBLPERSONEL.TCKN."
    )


def test_a_shown_column_without_a_prefix_exempts_nothing():
    """Çıplak seçilen AD_SOYAD'ın tablosu çözülmez; sıralama tablolu yazılsa da muafiyet yok."""
    assert reason("SELECT AD_SOYAD FROM TBLPERSONEL P ORDER BY P.AD_SOYAD") == (
        "Filtrede PII kolon: TBLPERSONEL.AD_SOYAD."
    )


def test_order_by_a_pii_column_shown_by_a_union_is_rejected():
    assert "TBLPERSONEL.IBAN" in reason(
        "SELECT IBAN FROM TBLPERSONEL UNION ALL SELECT IBAN FROM TBLPERSONEL ORDER BY IBAN"
    )


def test_order_by_a_pii_column_under_an_aggregate_is_rejected():
    assert reason("SELECT PERSONEL_KODU FROM TBLMAAS ORDER BY NET_TUTAR") == (
        "Filtrede PII kolon: TBLMAAS.NET_TUTAR."
    )


# ----------------------------------------------------------------- what ORDER BY may still use


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT PERSONEL_KODU FROM TBLPERSONEL WHERE AKTIF = 'E' ORDER BY PERSONEL_KODU",
        # aynı ad başka tabloda pii: sıralanan kolonun kendi tablosuna bakılır
        "SELECT AD_SOYAD FROM TBLPLASIYER ORDER BY AD_SOYAD",
        "SELECT M.PERSONEL_KODU FROM TBLMAAS M JOIN TBLPERSONEL P ON P.PERSONEL_KODU = M.PERSONEL_KODU "
        "ORDER BY M.PERSONEL_KODU DESC",
    ],
)
def test_ordering_a_non_pii_column_passes(sql):
    result = check(sql)
    assert result.ok, result.reason


# ------------------------------------------------------- the other three positions keep the rule


@pytest.mark.parametrize(
    "sql,column",
    [
        ("SELECT PERSONEL_KODU FROM TBLPERSONEL WHERE TCKN LIKE '1%'", "TBLPERSONEL.TCKN"),
        (
            "SELECT M.PERSONEL_KODU FROM TBLMAAS M JOIN TBLMAASDETAY D ON D.MAAS_ID = M.MAAS_ID "
            "AND D.TUTAR > 1000",
            "TBLMAASDETAY.TUTAR",
        ),
        ("SELECT PERSONEL_KODU FROM TBLMAAS GROUP BY NET_TUTAR", "TBLMAAS.NET_TUTAR"),
    ],
)
def test_where_join_and_group_by_rejections_are_unchanged(sql, column):
    assert reason(sql) == f"Filtrede PII kolon: {column}."
