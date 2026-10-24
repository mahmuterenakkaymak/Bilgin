"""Filtre yan kanalları (R3-6): maskelenen bir kolon sorgunun filtresi olamaz.

Maske değeri göstermez ama aynı kolon üzerinden filtre sorulursa cevap değerin kendisine
döner: `WHERE TCKN LIKE '1%'` tek bir haneyi bile ele verebilir. Bu yüzden politika pii
kolonlarını WHERE, JOIN ON, GROUP BY ve ORDER BY'da reddeder; sınıfı config.PII_FILTER'dan
çıkarılan kolonlar serbest kalır. Aynı kolonun çıplak SELECT'ı burada reddedilmez - oradaki
koruma maskenin kendisidir. Neden, kolonu TABLO.KOLON diye adlandırır ki model hangi
parçayı çıkarması gerektiğini görsün.
"""

import pytest

from nl2sql import config
from nl2sql.engine.executor import LocalExecutor
from nl2sql.policy import pii, policy
from nl2sql.schema_map import doc

SCHEMA = doc.load_schema()
ALLOWED = doc.allowlist(SCHEMA)
MARKS = pii.column_map(SCHEMA)


def check(sql, marks=MARKS):
    return policy.check(sql, ALLOWED, config.TOP_N, marks)


def reason(sql) -> str:
    result = check(sql)
    assert not result.ok and result.sql is None, sql
    return result.reason


# ----------------------------------------------------------------- the four positions


FILTERED = [
    ("SELECT PERSONEL_KODU FROM TBLPERSONEL WHERE TCKN LIKE '1%'", "TBLPERSONEL.TCKN"),
    ("SELECT PERSONEL_KODU FROM TBLPERSONEL P WHERE P.TCKN = '11111111110'", "TBLPERSONEL.TCKN"),
    ("SELECT PERSONEL_KODU FROM TBLPERSONEL WHERE VKN = '1234567890'", "TBLPERSONEL.VKN"),
    ("SELECT PERSONEL_KODU FROM TBLPERSONEL ORDER BY IBAN", "TBLPERSONEL.IBAN"),
    ("SELECT PERSONEL_KODU FROM TBLPERSONEL WHERE AD_SOYAD = 'Eren Kaya'", "TBLPERSONEL.AD_SOYAD"),
    ("SELECT PERSONEL_KODU FROM TBLPERSONEL WHERE ADRES LIKE 'Kadıköy%'", "TBLPERSONEL.ADRES"),
    ("SELECT PERSONEL_KODU FROM TBLPERSONEL WHERE E_POSTA LIKE '%@ornek.com'", "TBLPERSONEL.E_POSTA"),
    ("SELECT SUBE_KODU FROM TBLCARISUBE WHERE TELEFON IS NOT NULL", "TBLCARISUBE.TELEFON"),
    ("SELECT PERSONEL_KODU FROM TBLMAAS GROUP BY NET_TUTAR", "TBLMAAS.NET_TUTAR"),
    ("SELECT PERSONEL_KODU FROM TBLMAAS ORDER BY BRUT_TUTAR DESC", "TBLMAAS.BRUT_TUTAR"),
    ("SELECT PERSONEL_KODU FROM TBLMAAS WHERE KESINTI_TUTAR > 0", "TBLMAAS.KESINTI_TUTAR"),
    (
        "SELECT M.PERSONEL_KODU FROM TBLMAAS M JOIN TBLMAASDETAY D ON D.MAAS_ID = M.MAAS_ID "
        "AND D.TUTAR > 1000",
        "TBLMAASDETAY.TUTAR",
    ),
    (
        "SELECT CARI_KOD FROM TBLCASABIT WHERE CARI_KOD IN "
        "(SELECT PERSONEL_KODU FROM TBLPERSONEL WHERE TCKN LIKE '1%')",
        "TBLPERSONEL.TCKN",
    ),
    (
        "WITH K AS (SELECT PERSONEL_KODU, TCKN FROM TBLPERSONEL) SELECT PERSONEL_KODU FROM K "
        "WHERE K.TCKN LIKE '1%'",
        "TBLPERSONEL.TCKN",
    ),
    (
        "SELECT PERSONEL_KODU FROM TBLPERSONEL WHERE IL IN "
        "(SELECT IL FROM TBLCARISUBE GROUP BY ADRES)",
        "TBLCARISUBE.ADRES",
    ),
]


@pytest.mark.parametrize("sql,column", FILTERED)
def test_a_pii_column_used_as_a_filter_is_rejected(sql, column):
    result = check(sql)
    assert not result.ok and result.sql is None
    assert result.reason == f"Filtrede PII kolon: {column}."


def test_the_reason_names_the_column_so_the_model_can_drop_it():
    assert reason("SELECT PERSONEL_KODU FROM TBLPERSONEL WHERE TCKN LIKE '1%'") == (
        "Filtrede PII kolon: TBLPERSONEL.TCKN."
    )


# ----------------------------------------------------------------- what the mask already covers


CLEAN = [
    "SELECT TCKN FROM TBLPERSONEL",
    "SELECT TCKN, AD_SOYAD, IBAN FROM TBLPERSONEL",
    "SELECT PERSONEL_KODU, NET_TUTAR FROM TBLMAAS",
    "SELECT AVG(BRUT_TUTAR) AS ORTALAMA FROM TBLMAAS",
    "SELECT COUNT(DISTINCT TCKN) AS KAYITLI FROM TBLPERSONEL",
    "SELECT PERSONEL_KODU FROM TBLPERSONEL WHERE AKTIF = 'E' ORDER BY PERSONEL_KODU",
    "SELECT M.PERSONEL_KODU FROM TBLMAAS M JOIN TBLPERSONEL P ON P.PERSONEL_KODU = M.PERSONEL_KODU "
    "WHERE M.DONEM = '2026-06'",
    "SELECT SUBE_KODU FROM TBLCARISUBE WHERE IL = 'İzmir' GROUP BY SUBE_KODU",
    # aynı ad başka tabloda pii değil: çözülen kolonun tablosuna bakılır, ada değil
    "SELECT AD_SOYAD FROM TBLPLASIYER ORDER BY AD_SOYAD",
    "SELECT TUTAR FROM TBLCAHAR WHERE TUTAR > 0 GROUP BY TUTAR",
]


@pytest.mark.parametrize("sql", CLEAN)
def test_showing_a_pii_column_is_the_mask_job_not_the_filter_rule(sql):
    result = check(sql)
    assert result.ok, result.reason


def test_without_a_map_the_policy_keeps_its_old_answer():
    assert policy.check("SELECT PERSONEL_KODU FROM TBLPERSONEL WHERE TCKN LIKE '1%'", ALLOWED, 100).ok


# ----------------------------------------------------------------- the per-class switch


def test_a_class_taken_out_of_the_config_may_be_filtered(monkeypatch):
    monkeypatch.setattr(config, "PII_FILTER", frozenset(set(config.PII_FILTER) - {"tckn"}))
    assert check("SELECT PERSONEL_KODU FROM TBLPERSONEL WHERE TCKN LIKE '1%'").ok


def test_the_other_classes_keep_their_filter_rule(monkeypatch):
    monkeypatch.setattr(config, "PII_FILTER", frozenset(set(config.PII_FILTER) - {"tckn"}))
    assert "TBLPERSONEL.IBAN" in reason("SELECT PERSONEL_KODU FROM TBLPERSONEL ORDER BY IBAN")


def test_an_empty_config_switches_the_whole_rule_off(monkeypatch):
    monkeypatch.setattr(config, "PII_FILTER", frozenset())
    assert check("SELECT PERSONEL_KODU FROM TBLMAAS GROUP BY NET_TUTAR").ok


# ----------------------------------------------------------------- the executor hands the map over


def test_the_executor_refuses_a_filtered_pii_column(tmp_path):
    """Politika reddi veritabanına dokunmadan döner; olmayan dosya bunu kanıtlar."""
    executor = LocalExecutor("sqlite", tmp_path / "yok.db", ALLOWED, tmp_path / "audit.jsonl", SCHEMA)
    result = executor.execute("SELECT PERSONEL_KODU FROM TBLPERSONEL ORDER BY TCKN")
    assert result.error.kind == "policy" and "TBLPERSONEL.TCKN" in result.error.message
