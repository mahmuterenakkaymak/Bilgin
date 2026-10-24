"""T175: Türkçe sayı yazımı ve sonucun biçimi (PLAN R5-6, R5-7).

İddia fmt tarafında: ekrandaki her sayı tek kaynaktan yazılır — binlik nokta, ondalık virgül,
yüzde başta, yokluk "–"; yuvarlama gösterilir ama -0 gösterilmez. shape tarafında: bir kolonun
türü değerlerinden ve adından anlaşılır, grafiğin ne çizeceği sorunun sözcüklerine değil dönen
hücrelere bağlıdır. Yol tarafında bunu Q02'nin gerçek cevabı taşır: STOK_ADI kategori,
SATIS_MIKTARI sayıdır.
"""

import pytest

from nl2sql import config, datasets
from nl2sql.engine.executor import LocalExecutor
from nl2sql.report import fmt, shape
from nl2sql.schema_map import build

NULL = "–"

COLUMNS = ["TARIH", "DONEM", "AY", "STOK_KODU", "STOK_ADI", "MIKTAR", "IPTAL", "NOT"]
ROWS = [
    ("2026-09-01", "2026-09", 9, "STK0001", "Çay", 12.5, True, None),
    ("2026-09-02", "2026-10", 10, "STK0002", "Şeker", 3.0, False, None),
]


@pytest.fixture
def db(tmp_path):
    """Sentetik ERP'nin gerçek dünyası: Q02'nin koşabileceği SQLite dosyası."""
    path = tmp_path / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


# ------------------------------------------------------------------ sayı yazımı


def test_tr_number_groups_thousands_and_swaps_the_decimal_mark():
    assert fmt.tr_number(1234.56) == "1.234,56"
    assert fmt.tr_number(12345) == "12.345", "tam sayı ondalık taşımaz"
    assert fmt.tr_number(-1234.5) == "-1.234,5"
    assert fmt.tr_number(1234.0) == "1.234", "gereksiz ondalık yazılmaz"
    assert fmt.tr_number(1234.56, 2) == "1.234,56", "basamak verilince para gibi sabit yazılır"
    assert fmt.tr_number(1234567890) == "1.234.567.890", "büyük tam sayı üçlü gruplanır"
    assert fmt.tr_number(None) == NULL, "yokluk sıfır değildir"


def test_tr_number_shows_exactly_the_requested_decimals():
    assert fmt.tr_number(1234.567, 2) == "1.234,57"
    assert fmt.tr_number(1234.567, 0) == "1.235"
    assert fmt.tr_number(1234.567, 4) == "1.234,5670"
    assert fmt.tr_number(0) == "0"


def test_a_value_that_rounds_to_zero_is_not_shown_as_negative_zero():
    assert fmt.tr_number(-0.004, 2) == "0,00"
    assert fmt.tr_number(-0.5, 0) == "0"
    assert fmt.tr_number(-0.006, 2) == "-0,01", "gerçek eksi işaretini kaybetmez"


def test_tr_percent_writes_the_sign_before_the_number():
    assert fmt.tr_percent(12.3) == "%12,3"
    assert fmt.tr_percent(12.25, 2) == "%12,25"
    assert fmt.tr_percent(-1.5) == "-%1,5"
    assert fmt.tr_percent(0) == "%0,0"
    assert fmt.tr_percent(None) == NULL


def test_tr_compact_scales_big_numbers_and_leaves_small_ones():
    assert fmt.tr_compact(12500) == "12,5 bin"
    assert fmt.tr_compact(3_200_000) == "3,2 milyon"
    assert fmt.tr_compact(1_100_000_000) == "1,1 milyar"
    assert fmt.tr_compact(-12500) == "-12,5 bin"
    assert fmt.tr_compact(10_000) == "10,0 bin"
    assert fmt.tr_compact(9999) == "9.999", "10.000'dan küçüğü ölçeklenmez"
    assert fmt.tr_compact(None) == NULL


# ------------------------------------------------------------------ kolon türleri


def test_kinds_are_read_from_the_values_and_the_column_name():
    assert shape.column_kinds(COLUMNS, ROWS) == [
        "date",  # ISO YYYY-MM-DD yazan metin
        "date",  # ISO YYYY-MM yazan metin
        "date",  # AY adı + tam sayı değerleri
        "code",  # KODU ile biten ad: sayı taşasa da sayı değil
        "category",  # düz metin
        "number",
        "category",  # bool sayı değildir
        "category",  # hepsi NULL: ortada tür yok
    ]


def test_pick_lists_date_number_and_code_columns_and_picks_one_category():
    assert shape.pick(COLUMNS, ROWS) == {
        "date": [0, 1, 2],
        "number": [5],
        "category": 4,
        "code": [3],
    }


def test_the_category_falls_back_to_the_first_code_column():
    picked = shape.pick(["STOK_KODU", "FIS_NO"], [("STK0001", 7), ("STK0002", 8)])

    assert picked["category"] == 0
    assert picked["code"] == [0, 1]
    assert picked["number"] == [], "kod benzeri ad toplamaya açılmaz"


def test_a_result_without_any_text_has_no_category():
    assert shape.pick(["MIKTAR", "TUTAR"], [(1, 2.5), (3, 4.5)])["category"] is None


# ------------------------------------------------------------------ yol: gerçek cevap


def test_the_q02_answer_picks_its_name_as_category_and_its_quantity_as_number(db, tmp_path):
    line = next(item for item in datasets.load_dataset("synthetic_erp").golden() if item["id"] == "Q02")
    executor = LocalExecutor(backend="sqlite", db_path=db, audit_path=tmp_path / "audit.jsonl")

    result = executor.execute(line["sql"], None, "test")

    assert not result.error, result.error
    picked = shape.pick(result.columns, result.rows)
    assert result.columns[picked["category"]] == "STOK_ADI"
    assert picked["number"] == [result.columns.index("SATIS_MIKTARI")]
    assert picked["code"] == [result.columns.index("STOK_KODU")]
    assert picked["date"] == []
