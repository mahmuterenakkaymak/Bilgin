# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R3-6 yan kanal kümesi: tests/data/pii_bypass.jsonl gerçek kapıdan geçirilir.

Maske ve filtre kuralları birim testlerinde ayrı ayrı ölçüldü; asıl soru ikisinin **executor'da**
birlikte ne yaptığı: pii kolonu takma ad, CTE, CAST/CONVERT, kesme işlevi, CASE, UNION, skaler alt
sorgu ya da türetilmiş tablo arkasına saklandığında değer yine maskeleniyor mu, yoksa kolon pii
olduğunu mu unutuyor; aynı kolon WHERE/JOIN/GROUP BY/ORDER BY'a girdiğinde ise satır hiç
dönmeden mi reddediliyor. Bu yüzden her satır ``build_db`` ile kurulmuş dünyada gerçek
``LocalExecutor``'dan geçiyor - politika, çeviri, yedek, maske ve denetim aynı sırayla işliyor.
Beklenenler dosyada: ``masked`` satırında maskelenen kolonların birebir listesi (beyaz listedeki
COUNT boş listeyle döner), ``rejected`` satırında hatanın ``policy`` olması. Denetim satırı
maskelenen kolonların adını yazar, değerini yazmaz; hiçbir altın soru maske gerektirmez.
"""

import json
import sqlite3
from pathlib import Path

import pytest

from nl2sql import config
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.eval import runner
from nl2sql.schema_map import build, doc

SCHEMA = doc.load_schema()
GOLDEN = runner.load_golden()
CASES = [
    json.loads(line)
    for line in (Path(__file__).parent / "data" / "pii_bypass.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]
MASKED = [case for case in CASES if case["expect"] == "masked"]
REJECTED = [case for case in CASES if case["expect"] == "rejected"]
FULL = Budget(max_rows=100000)

# Sızıntı kontrolü benzersiz tanımlayıcılar üzerinden: adlar iki tabloda da aynı değeri taşıyabilir.
IDENTIFIERS = ("TCKN", "VKN", "IBAN", "E_POSTA")


def build_db(tmp):
    path = tmp / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


def raw(db, table, columns) -> list[tuple]:
    """Satırların ham hali: veritabanından doğrudan okunur, executor'a hiç uğramaz."""
    conn = sqlite3.connect(db)
    try:
        return conn.execute(f"SELECT {', '.join(columns)} FROM {table}").fetchall()
    finally:
        conn.close()


def entries(path) -> list[dict]:
    text = path.read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    return build_db(tmp_path_factory.mktemp("pii-bypass"))


@pytest.fixture
def executor(db, tmp_path):
    return LocalExecutor("sqlite", db, doc.allowlist(SCHEMA), tmp_path / "audit.jsonl", SCHEMA)


# ----------------------------------------------------------------- the set itself (R3-12)


def test_the_set_covers_both_halves_of_the_rule():
    assert MASKED and REJECTED, "kümenin iki yarısı da ölçülmeli"
    assert len(CASES) >= 20, "R3-6 en az 20 yan kanal bekliyor"


def test_ids_are_unique_and_run_in_order():
    ids = [case["id"] for case in CASES]
    assert len(set(ids)) == len(ids), "id yinelenmiş"
    assert ids == [f"PB{number:02d}" for number in range(1, len(ids) + 1)], "id dizisi bozulmuş"


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_every_case_declares_what_it_claims(case):
    assert case["sql"].strip()
    assert case["expect"] in {"masked", "rejected"}
    assert case["note"].strip(), "neden ölçüldüğü yazılı olmalı"
    if case["expect"] == "masked":
        assert isinstance(case["masked_columns"], list)
    else:
        assert "masked_columns" not in case, "reddedilen satır maske listesi taşımaz"


# ----------------------------------------------------------------- masking through the real door

# ASSUMPTION: RIGHT SQLite'a çevrilmediği için (PB11) kesme ailesi SUBSTRING/LEFT ile ölçülüyor;
# maske kararı çeviriden önce iz üzerinden veriliyor, o yüzden üç işlevde de aynı yol.


@pytest.mark.parametrize("case", MASKED, ids=[case["id"] for case in MASKED])
def test_a_masked_case_returns_exactly_the_columns_the_file_lists(case, executor):
    result = executor.execute(case["sql"], FULL, case["id"])
    assert result.error is None, result.error
    assert result.rows, f"{case['id']} boş döndü; maske hiçbir hücreyi görmedi"
    assert result.masked_columns == case["masked_columns"]


@pytest.mark.parametrize("case", MASKED, ids=[case["id"] for case in MASKED])
def test_no_masked_case_hands_a_raw_identifier_over(case, db, executor):
    """Maske değeri göstermez: hiçbir hücre kaynaktaki bir TCKN/VKN/IBAN/e-posta ile aynı değil."""
    leaked = {value for row in raw(db, "TBLPERSONEL", IDENTIFIERS) for value in row}
    rows = executor.execute(case["sql"], FULL, case["id"]).rows
    assert all(value not in leaked for row in rows for value in row if isinstance(value, str))


# ----------------------------------------------------------------- the filter side channels


@pytest.mark.parametrize("case", REJECTED, ids=[case["id"] for case in REJECTED])
def test_a_filtered_pii_column_never_reaches_the_database(case, executor):
    result = executor.execute(case["sql"], FULL, case["id"])
    assert result.error is not None and result.error.kind == "policy"
    assert "PII kolon:" in result.error.message, "neden kolonu adlandırmıyor"
    assert result.rows == [] and result.masked_columns == []


# ----------------------------------------------------------------- audit


def test_audit_carries_the_masked_names_and_never_their_values(db, tmp_path):
    audit_path = tmp_path / "audit.jsonl"
    executor = LocalExecutor("sqlite", db, doc.allowlist(SCHEMA), audit_path, SCHEMA)
    for case in CASES:
        executor.execute(case["sql"], FULL, case["id"])

    lines = entries(audit_path)
    assert len(lines) == len(CASES), "her deneme tek satır"
    by_source = {line["source"]: line for line in lines}
    for case in MASKED:
        line = by_source[case["id"]]
        assert line.get("masked", []) == case["masked_columns"]
    for case in REJECTED:
        assert by_source[case["id"]]["outcome"] == "policy"

    text = audit_path.read_text(encoding="utf-8")
    values = {
        value
        for row in raw(db, "TBLPERSONEL", (*IDENTIFIERS, "AD_SOYAD"))
        for value in row
        if isinstance(value, str)
    }
    assert all(value not in text for value in values), "denetim satırında değer var"


# ----------------------------------------------------------------- the golden questions


@pytest.mark.parametrize("question", GOLDEN, ids=[line["id"] for line in GOLDEN])
def test_no_golden_question_needs_masking(executor, question):
    result = executor.execute(question["sql"], FULL, question["id"])
    assert result.error is None, result.error
    assert result.masked_columns == []
