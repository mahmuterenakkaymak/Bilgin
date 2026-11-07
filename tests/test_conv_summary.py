# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T286: ``turn_summary`` (PLAN R7-3, Contracts "TurnSummary").

Özet, bir turun sonraki tura miras bıraktığı kadardır: en fazla ``CONV_KEEP_ROWS`` maskeli satır,
satır sayısı, kolonlar, olgular, grafik türü, bağlam notu ve netleştirme. Dünya gerçek, model
``--llm fake``: kurulmuş sentetik ERP dosyasında koşan ``ask_payload``. İddialar özette - 40
satırlık cevap 5 satır ve gerçek sayısını tutar, maske olduğu gibi kalır, başarısız turun satırı
boştur, özet JSONa yazılır.
"""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bilgin import config
from bilgin.agent import fake
from bilgin.agent.context import turn_summary
from bilgin.app.ask import ask_payload
from bilgin.app.session import open_session
from bilgin.schema_map import build

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"

PERSONEL_SQL = "SELECT PERSONEL_KODU, AD_SOYAD FROM TBLPERSONEL ORDER BY PERSONEL_KODU"
MOVEMENTS_SQL = "SELECT TOP 40 STOK_KODU FROM TBLSTHAR"


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(FIXTURE_ROOT))
    return tmp_path


@pytest.fixture(scope="module")
def erp_db(tmp_path_factory):
    path = tmp_path_factory.mktemp("conv-summary") / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


def scripted_session(db, project, script):
    return open_session(
        llm="fake",
        db_path=db,
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
        client_factory=lambda mode: fake.FakeLLM(script),
    )


def test_a_forty_row_answer_keeps_five_rows_and_the_true_count(project, erp_db):
    session = scripted_session(erp_db, project, fake.wrong_sql(MOVEMENTS_SQL))
    payload = ask_payload(session, "Stok hareketlerini listeler misin?", mode="full")

    assert payload["status"] == "answered"
    assert payload["row_count"] == 40 and len(payload["rows"]) == 40

    summary = turn_summary(payload)
    assert summary["row_count"] == 40
    assert len(summary["rows"]) == config.CONV_KEEP_ROWS
    assert summary["rows"] == payload["rows"][: config.CONV_KEEP_ROWS]
    assert summary["columns"] == payload["columns"]


def test_a_masked_column_keeps_the_mask_and_never_a_raw_value(project, erp_db):
    session = scripted_session(erp_db, project, fake.wrong_sql(PERSONEL_SQL))
    payload = ask_payload(session, "Kimler personel, adlarıyla?", mode="full")

    assert payload["masked_columns"] == ["AD_SOYAD"]
    summary = turn_summary(payload)
    assert summary["rows"] == payload["rows"][: config.CONV_KEEP_ROWS]
    assert all(row[1].endswith(".") for row in summary["rows"]), "ad değil, maskesi kalmalı"


def test_a_failed_turn_has_no_rows(project, erp_db):
    session = scripted_session(erp_db, project, fake.never_submit())
    payload = ask_payload(session, "Ürünlerin listesi?", mode="full")

    assert payload["status"] == "failed"
    summary = turn_summary(payload)
    assert summary["rows"] == [] and summary["row_count"] == 0
    assert summary["columns"] == [] and summary["chart_kind"] is None


def test_the_summary_is_json_serialisable(project, erp_db):
    session = scripted_session(erp_db, project, fake.wrong_sql(PERSONEL_SQL))
    payload = ask_payload(session, "Kimler personel?", mode="full")

    assert json.loads(json.dumps(turn_summary(payload), ensure_ascii=False))


def test_decimal_and_date_cells_become_text():
    payload = {
        "columns": ["TARIH", "TUTAR"],
        "row_count": 1,
        "rows": [[date(2026, 9, 30), Decimal("1234.56")]],
        "facts": [],
        "chart": {"type": "bar", "option": {"series": []}},
        "context": {"uses_turns": [1], "entities": [], "refines_sql_of": None},
        "clarification": None,
    }
    summary = turn_summary(payload)

    assert summary["rows"] == [["2026-09-30", "1234.56"]]
    assert summary["chart_kind"] == "bar"
    assert summary["context"] == payload["context"]
    assert json.loads(json.dumps(summary, ensure_ascii=False))
