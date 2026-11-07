# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""R4-7 yan kanal kümesi WWI üzerinde: tests/data/pii_bypass_wwi.jsonl gerçek kapıdan geçirilir.

R3-6 maskesi ve filtresi dbo-only şemada ölçülmüştü; R4-5 tablo adını `Sales.Customers` yapınca
aynı iki kural şemalı adlarla yeniden sınanmalı: maske izi şemayı iç içe vererek takma ad, CTE,
CAST/CONCAT, kesme, CASE, UNION, skaler alt sorgu ve türetilmiş tablo arkasından gerçek kolona
varıyor mu; aynı kolon WHERE/JOIN/GROUP BY/ORDER BY'a girdiğinde satır hiç dönmüyor mu; `deny`
kolonları (HashedPassword/Photo) ad, takma ad, CTE, WHERE ve `p.*` üzerinden hiç okunamıyor mu.
Bu yüzden her satır `Dataset("wwi").build_db` ile kurulmuş dünyada gerçek `LocalExecutor`'dan
geçiyor - politika, çeviri, yedek, maske ve denetim aynı sırayla işliyor. Beklenenler dosyada:
`masked` satırında maskelenen kolonların birebir listesi (COUNT boş listeyle sayı döner),
`rejected` satırında R3-6 filtre nedeni, `denied` satırında R4-7 kapalı kolon nedeni.
"""

import json
from pathlib import Path

import pytest

from nl2sql.datasets import load_dataset
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.schema_map import doc

DATASET = load_dataset("wwi")
SCHEMA = DATASET.schema()
CASES = [
    json.loads(line)
    for line in (Path(__file__).parent / "data" / "pii_bypass_wwi.jsonl")
    .read_text(encoding="utf-8")
    .splitlines()
    if line.strip()
]
MASKED = [case for case in CASES if case["expect"] == "masked"]
REJECTED = [case for case in CASES if case["expect"] == "rejected"]
DENIED = [case for case in CASES if case["expect"] == "denied"]
FULL = Budget(max_rows=100000)

# Sızıntı kontrolü maskeye giren sınıflar üzerinden: adres kolonları dışarıda.
# ASSUMPTION: adres maskesi ilk parçayı bilinçli korur; WWI adreslerinde virgül olmadığı için
# maskelenmiş adres ham değeriyle aynıdır, o yüzden "ham değer sızmıyor" iddiası ona uygulanmaz.
REDACTING = {
    "Application.People": ("FullName", "PreferredName", "LogonName", "EmailAddress", "PhoneNumber", "FaxNumber"),
    "Sales.Customers": ("PhoneNumber", "FaxNumber"),
    "Purchasing.Suppliers": ("PhoneNumber", "FaxNumber"),
}


def raw_values() -> set[str]:
    """Kümenin ham pii değerleri: üretecin satırlarından doğrudan okunur, executor'a hiç uğramaz."""
    rows = DATASET.generate()
    return {
        value
        for table, columns in REDACTING.items()
        for row in rows[table]
        for column in columns
        if isinstance((value := row.get(column)), str)
    }


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("pii-bypass-wwi") / "test.db"
    DATASET.build_db(db_path=path, sql_path=path.with_suffix(".sql"))
    return path


@pytest.fixture
def executor(db, tmp_path):
    return LocalExecutor("sqlite", db, doc.allowlist(SCHEMA), tmp_path / "audit.jsonl", SCHEMA)


# ----------------------------------------------------------------- the set itself


def test_the_set_covers_every_kind_of_case():
    assert MASKED and REJECTED and DENIED, "maske, filtre ve kapalı kolon birlikte ölçülmeli"
    assert len(CASES) >= 20, "R4-7 en az 20 yan kanal bekliyor"


def test_ids_are_unique_and_run_in_order():
    ids = [case["id"] for case in CASES]
    assert len(set(ids)) == len(ids), "id yinelenmiş"
    assert ids == [f"WPB{number:02d}" for number in range(1, len(ids) + 1)], "id dizisi bozulmuş"


@pytest.mark.parametrize("case", CASES, ids=[case["id"] for case in CASES])
def test_every_case_declares_what_it_claims(case):
    assert case["sql"].strip()
    assert case["expect"] in {"masked", "rejected", "denied"}
    assert case["note"].strip(), "neden ölçüldüğü yazılı olmalı"
    if case["expect"] == "masked":
        assert isinstance(case["masked_columns"], list)
    else:
        assert "masked_columns" not in case, "reddedilen satır maske listesi taşımaz"


# ----------------------------------------------------------------- masking through the real door


@pytest.mark.parametrize("case", MASKED, ids=[case["id"] for case in MASKED])
def test_a_masked_case_returns_exactly_the_columns_the_file_lists(case, executor):
    result = executor.execute(case["sql"], FULL, case["id"])
    assert result.error is None, result.error
    assert result.rows, f"{case['id']} boş döndü; maske hiçbir hücreyi görmedi"
    assert result.masked_columns == case["masked_columns"]


@pytest.mark.parametrize("case", MASKED, ids=[case["id"] for case in MASKED])
def test_no_masked_case_hands_a_raw_value_over(case, db, executor):
    """Maske değeri göstermez: hiçbir hücre kümedeki bir ad/telefon/e-posta ile aynı değil."""
    leaked = raw_values()
    rows = executor.execute(case["sql"], FULL, case["id"]).rows
    assert all(value not in leaked for row in rows for value in row if isinstance(value, str))


def test_count_distinct_stays_a_number(executor):
    """Beyaz liste: COUNT(DISTINCT EmailAddress) maskelenmez, sayı olarak döner."""
    result = executor.execute(
        "SELECT COUNT(DISTINCT EmailAddress) AS FARKLI_POSTA FROM Application.People", FULL, "count"
    )
    assert result.error is None, result.error
    assert result.masked_columns == []
    (value,) = result.rows[0]
    assert isinstance(value, int) and value > 0


# ----------------------------------------------------------------- the filter side channels (R3-6)


@pytest.mark.parametrize("case", REJECTED, ids=[case["id"] for case in REJECTED])
def test_a_filtered_pii_column_never_reaches_the_database(case, executor):
    result = executor.execute(case["sql"], FULL, case["id"])
    assert result.error is not None and result.error.kind == "policy"
    assert "PII kolon:" in result.error.message, "neden kolonu adlandırmıyor"
    assert result.rows == [] and result.masked_columns == []


# ----------------------------------------------------------------- denied columns (R4-7)


@pytest.mark.parametrize("case", DENIED, ids=[case["id"] for case in DENIED])
def test_a_denied_column_never_reaches_the_database(case, executor):
    result = executor.execute(case["sql"], FULL, case["id"])
    assert result.error is not None and result.error.kind == "policy"
    assert "kapalı kolon" in result.error.message, "neden kolonun kapalı olduğunu söylemiyor"
    assert result.rows == [] and result.masked_columns == []
