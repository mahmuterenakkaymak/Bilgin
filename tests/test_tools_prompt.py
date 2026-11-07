# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Araç şemaları, dispatch'in modele gösterdiği metin ve sistem istemi.

Burada sınanan şey sözleşmenin kendisi: modelin üç araçtan fazlasını görememesi, her aracın
modele geri dönüşün okunabilir bir metin olması (kolonlar + ilk satırlar + satır sayısı ya da
hata türü + gerekçe) ve istemin dört kuralı taşıması. Veritabanı gerçek: build_db ile kurulmuş
SQLite dosyası üzerinde LocalExecutor çalışıyor, böylece metne giren sayılar uydurma olmuyor.
"""

import json
import re

import pytest

from bilgin import config
from bilgin.agent import prompt, tools
from bilgin.engine.executor import LocalExecutor
from bilgin.schema_map import build, doc

Q01_SQL = (
    "SELECT CARI_KOD, CARI_ISIM FROM TBLCASABIT "
    "WHERE IL = 'ANKARA' AND CARI_TIP IN ('A', 'H') ORDER BY CARI_KOD"
)
Q03_SQL = (
    "SELECT SUM(s.STHAR_GCMIK * s.STHAR_NF) AS NET_CIRO FROM TBLSTHAR s "
    "WHERE s.STHAR_HTUR = 'S' AND s.STHAR_TARIH >= '2026-08-01' AND s.STHAR_TARIH < '2026-09-01'"
)
MANY_ROWS_SQL = "SELECT STOK_KODU, STHAR_TARIH FROM TBLSTHAR ORDER BY STOK_KODU, STHAR_TARIH"
INVOICE_TOTAL_SQL = (
    "SELECT SUM(GENELTOPLAM) AS TOPLAM FROM TBLFATUIRS WHERE FTIRSIP = '1' AND IPTAL = 'H'"
)
FORBIDDEN_SQL = "SELECT name FROM sys.objects"
BROKEN_SQL = "SELECT OLMAKOLAN_KOLON FROM TBLSTSABIT"
EMPTY_SQL = "SELECT CARI_KOD FROM TBLCASABIT WHERE IL = 'YOKILI'"


@pytest.fixture(scope="module")
def schema():
    return doc.load_schema()


@pytest.fixture(scope="module")
def executor(tmp_path_factory):
    paths = tmp_path_factory.mktemp("tools")
    db = paths / "test.db"
    build.build_db(config.SEED, db, paths / "test.sql")
    return LocalExecutor("sqlite", db, audit_path=paths / "audit.jsonl")


# ------------------------------------------------------------------ tool declarations


def test_the_model_sees_exactly_three_tools():
    assert tools.TOOL_NAMES == ["get_schema", "run_sql", "submit_sql"]


def test_every_tool_is_declared_in_openai_form():
    for tool in tools.TOOLS:
        assert tool["type"] == "function"
        function = tool["function"]
        assert function["description"].strip()
        assert function["parameters"]["type"] == "object"
        assert set(function["parameters"]["properties"])


def test_only_the_sql_tools_require_an_argument():
    parameters = {tool["function"]["name"]: tool["function"]["parameters"] for tool in tools.TOOLS}
    assert "required" not in parameters["get_schema"]  # tables opsiyonel
    assert parameters["get_schema"]["properties"]["tables"]["items"] == {"type": "string"}
    assert parameters["run_sql"]["required"] == ["sql"]
    assert parameters["submit_sql"]["required"] == ["sql"]


def test_the_schemas_survive_json_serialisation():
    assert json.loads(json.dumps(tools.TOOLS, ensure_ascii=False))[0]["function"]["name"] == "get_schema"


# ------------------------------------------------------------------ get_schema


def test_get_schema_without_tables_is_an_overview_of_every_table(schema):
    answer = tools.dispatch("get_schema", {}, None, schema)
    for table in schema["tables"]:
        assert table["name"] in answer
        assert table["description"] in answer
    assert "STHAR_GCMIK" not in answer, "özet kolon listeliyor; ayrıntı için get_schema çağrılmaz"


def test_get_schema_with_tables_returns_columns_and_codes(schema):
    answer = tools.dispatch("get_schema", {"tables": ["TBLSTHAR"]}, None, schema)
    assert "STHAR_GCMIK" in answer
    assert "G=giriş" in answer, "kod anlamları modele join ipucu verir"
    assert "CARI_ISIM" not in answer, "istenmeyen tablonun kolonları gelmesin"


def test_get_schema_accepts_one_table_name_written_as_text(schema):
    assert "STHAR_GCMIK" in tools.dispatch("get_schema", {"tables": "tblsthar"}, None, schema)


def test_get_schema_answers_an_unknown_table_with_the_known_ones(schema):
    answer = tools.dispatch("get_schema", {"tables": ["TBLYOYK"]}, None, schema)
    assert "Bilinmeyen tablo: TBLYOYK" in answer
    assert "TBLSTHAR" in answer


# ------------------------------------------------------------------ run_sql


def test_run_sql_shows_columns_rows_and_the_row_count(executor):
    answer = tools.dispatch("run_sql", {"sql": Q01_SQL}, executor, {})
    lines = answer.splitlines()
    assert lines[0] == "Kolonlar: CARI_KOD, CARI_ISIM"
    assert lines[1].count(" | ") == 1
    assert lines[-1] == f"Satır sayısı: {executor.execute(Q01_SQL).row_count}"


def test_run_sql_prints_a_money_total_with_two_decimals(executor):
    answer = tools.dispatch("run_sql", {"sql": INVOICE_TOTAL_SQL}, executor, {})
    assert re.fullmatch(r"\d+\.\d{2}", answer.splitlines()[1]), answer


def test_run_sql_keeps_the_precision_of_a_fractional_answer(executor):
    """Tutar sanılan sayı aslında küsuratlı bir toplam olabiliyor; iki haneye indirilemez."""
    answer = tools.dispatch("run_sql", {"sql": Q03_SQL}, executor, {})
    assert re.fullmatch(r"\d+\.\d{3,}", answer.splitlines()[1]), answer


def test_run_sql_prints_a_missing_value_as_null(executor):
    answer = tools.dispatch("run_sql", {"sql": "SELECT TOP 3 FISNO FROM TBLSTHAR WHERE FISNO IS NULL"}, executor, {})
    assert answer.splitlines()[1] == "NULL"


def test_run_sql_shows_the_first_fifty_rows_and_keeps_the_total(executor):
    answer = tools.dispatch("run_sql", {"sql": MANY_ROWS_SQL}, executor, {})
    total = executor.execute(MANY_ROWS_SQL).row_count
    assert total > config.MODEL_MAX_ROWS
    assert sum(1 for line in answer.splitlines() if " | " in line) == config.MODEL_MAX_ROWS
    assert f"Satır sayısı: {total}" in answer
    assert f"İlk {config.MODEL_MAX_ROWS} satır gösteriliyor (toplam {total})." in answer


def test_run_sql_says_when_there_is_nothing_to_show(executor):
    answer = tools.dispatch("run_sql", {"sql": EMPTY_SQL}, executor, {})
    assert answer == "Kolonlar: CARI_KOD\nSonuç boş (0 satır)."


def test_run_sql_names_the_guardrail_and_the_reason(executor):
    answer = tools.dispatch("run_sql", {"sql": FORBIDDEN_SQL}, executor, {})
    assert answer.startswith(f"{tools.ERROR_PREFIX} (policy): ")
    assert answer.removeprefix(f"{tools.ERROR_PREFIX} (policy): ").strip()


def test_run_sql_names_a_database_error(executor):
    answer = tools.dispatch("run_sql", {"sql": BROKEN_SQL}, executor, {})
    assert answer.startswith(f"{tools.ERROR_PREFIX} (sql): ")


@pytest.mark.parametrize("args", [{"sql": "   "}, {}])
def test_a_query_that_was_not_written_never_reaches_the_database(args, executor):
    assert tools.dispatch("run_sql", args, executor, {}) == "Sorgu boş: tek bir T-SQL SELECT yazın."


# ------------------------------------------------------------------ submit_sql


def test_submit_sql_runs_the_query_and_says_it_was_accepted(executor):
    answer = tools.dispatch("submit_sql", {"sql": Q01_SQL}, executor, {})
    assert answer.startswith("Sorgu cevap olarak alındı")
    assert "Kolonlar: CARI_KOD, CARI_ISIM" in answer


def test_submit_sql_refuses_a_query_the_guardrail_rejects(executor):
    answer = tools.dispatch("submit_sql", {"sql": FORBIDDEN_SQL}, executor, {})
    assert answer.startswith(f"{tools.ERROR_PREFIX} (policy): ")


# ------------------------------------------------------------------ unknown tool


def test_an_invented_tool_is_answered_with_the_tools_that_exist():
    answer = tools.dispatch("drop_table", {}, None, {})
    assert "Bilinmeyen araç: drop_table" in answer
    assert "get_schema, run_sql, submit_sql" in answer


# ------------------------------------------------------------------ system prompt


def test_the_prompt_names_the_dialect_and_the_reference_date():
    text = prompt.system_prompt(config.AS_OF, "TABLO — açıklama")
    assert "T-SQL" in text
    assert config.AS_OF in text
    assert "{as_of}" not in text and "{compact_schema}" not in text


def test_the_prompt_carries_the_schema_the_loop_handed_it():
    compact = "TBLSTHAR — Stok hareketleri"
    assert prompt.system_prompt(config.AS_OF, compact).rstrip().endswith(compact)


def test_the_prompt_takes_the_numbers_away_from_the_model():
    assert "Sayıları asla sen hesaplamazsın" in prompt.system_prompt(config.AS_OF, "")


def test_the_prompt_makes_submit_sql_the_only_way_to_finish():
    assert "submit_sql çağrılmadan biten çalışma başarısız sayılır" in prompt.system_prompt(
        config.AS_OF, ""
    )


def test_the_prompt_splits_the_month_with_ranges_not_functions():
    text = prompt.system_prompt(config.AS_OF, "")
    assert "MONTH, YEAR veya DATEPART" in text
    assert "TARIH >=" in text
