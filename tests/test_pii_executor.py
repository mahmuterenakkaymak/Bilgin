"""Executor maskesi: pii kolonu kapıdan maskelenmiş çıkar, sayı olduğu gibi kalır (R3-6).

Dünya gerçek: ``build_db`` ile kurulmuş dosya ve gerçek şema.json, yani maskelenen değer üreticinin
yazdığı değerin kendisi. İddialar: TCKN son dört hanesine iner, maaş hiç görünmez, COUNT beyaz
listede kaldığı için sayı olarak döner, izi okunamayan kolonun tamamı gizlenir, temiz kolon ham
kalır, denetim satırı kolonun adını yazar değerini yazmaz ve hiçbir altın soru maskelenmeden döner.
"""

import json
import sqlite3

import pytest

from nl2sql import config
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.eval import runner
from nl2sql.schema_map import build, doc

SCHEMA = doc.load_schema()
GOLDEN = runner.load_golden()
# Satır bütçesi maskenin kendisiyle ilgisi yok: karşılaştırmaların tamamı satırların hepsiyle yapılır.
FULL = Budget(max_rows=100000)


def build_db(tmp):
    path = tmp / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return build_db(tmp_path_factory.mktemp("pii-executor"))


@pytest.fixture
def executor(db, tmp_path):
    return LocalExecutor("sqlite", db, doc.allowlist(SCHEMA), tmp_path / "audit.jsonl", SCHEMA)


def raw(db, sql) -> list[tuple]:
    """Satırların ham hali: veritabanından doğrudan okunur, executor'a hiç uğramaz."""
    conn = sqlite3.connect(db)
    try:
        return conn.execute(sql).fetchall()
    finally:
        conn.close()


def entries(path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


# ----------------------------------------------------------------- the mask per class


def test_tckn_keeps_only_its_last_four_digits(db, executor):
    # Ordered by the personnel code, not by TCKN: a PII column in ORDER BY is rejected by policy (PLAN R3-6,
    # tests/test_pii_order_by.py). Fixed 2026-10-24 with Eren's approval - this test predated that rule.
    result = executor.execute("SELECT TCKN FROM TBLPERSONEL ORDER BY PERSONEL_KODU", FULL)
    assert result.error is None
    assert result.masked_columns == ["TCKN"]
    expected = [row[0] for row in raw(db, "SELECT TCKN FROM TBLPERSONEL ORDER BY PERSONEL_KODU")]
    assert [row[0] for row in result.rows] == ["*******" + value[-4:] for value in expected]


def test_average_salary_is_never_shown(executor):
    result = executor.execute("SELECT AVG(BRUT_TUTAR) AS ORTALAMA FROM TBLMAAS", FULL)
    assert result.error is None
    assert result.masked_columns == ["ORTALAMA"]
    assert {row[0] for row in result.rows} == {"***"}


def test_the_clean_column_of_a_masked_row_stays_raw(db, executor):
    result = executor.execute(
        "SELECT PERSONEL_KODU, AD_SOYAD FROM TBLPERSONEL ORDER BY PERSONEL_KODU", FULL
    )
    assert result.masked_columns == ["AD_SOYAD"]
    assert [row[0] for row in result.rows] == [
        row[0] for row in raw(db, "SELECT PERSONEL_KODU FROM TBLPERSONEL ORDER BY PERSONEL_KODU")
    ]
    assert all(row[1].endswith(".") and " " in row[1] for row in result.rows), "baş harfler, ad değil"


# ----------------------------------------------------------------- the whitelist and the gate


def test_count_over_a_pii_table_stays_a_number(executor):
    result = executor.execute("SELECT COUNT(*) AS KISI_SAYISI FROM TBLPERSONEL", FULL)
    assert result.masked_columns == []
    assert result.rows[0][0] > 0 and isinstance(result.rows[0][0], int)


def test_count_distinct_of_a_pii_column_is_the_whitelisted_case(executor):
    result = executor.execute("SELECT COUNT(DISTINCT TCKN) AS KAYITLI_KIMLIK FROM TBLPERSONEL", FULL)
    assert result.masked_columns == []
    assert isinstance(result.rows[0][0], int)


def test_a_query_touching_no_pii_table_shows_its_values(executor):
    result = executor.execute("SELECT STOK_ADI FROM TBLSTSABIT", FULL)
    assert result.error is None and result.rows
    assert result.masked_columns == []


def test_two_columns_sharing_an_output_name_hide_everything(executor):
    # İki kolon aynı çıktı adını alınca iz hangi değerin nerede olduğu sözünü yitirir.
    result = executor.execute("SELECT IL AS X, AD_SOYAD AS X FROM TBLPERSONEL", FULL)
    assert result.error is None
    assert result.masked_columns == ["X", "X"]
    assert all(set(row) == {"***"} for row in result.rows)


# ----------------------------------------------------------------- audit


def test_audit_names_the_masked_columns_and_never_their_values(db, executor, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    executor.execute("SELECT TCKN, AD_SOYAD FROM TBLPERSONEL", FULL)

    assert entries(audit_path)[0]["masked"] == ["TCKN", "AD_SOYAD"]
    text = audit_path.read_text(encoding="utf-8")
    for tckn, ad_soyad in raw(db, "SELECT TCKN, AD_SOYAD FROM TBLPERSONEL"):
        assert tckn not in text and ad_soyad not in text


def test_an_unmasked_query_keeps_the_plain_audit_entry(executor, tmp_path):
    executor.execute("SELECT COUNT(*) AS KISI_SAYISI FROM TBLPERSONEL", FULL)
    assert "masked" not in entries(tmp_path / "audit.jsonl")[0]


# ----------------------------------------------------------------- the golden questions


@pytest.mark.parametrize("question", GOLDEN, ids=[line["id"] for line in GOLDEN])
def test_no_golden_question_needs_masking(executor, question):
    result = executor.execute(question["sql"], FULL)
    assert result.error is None, result.error
    assert result.masked_columns == []
