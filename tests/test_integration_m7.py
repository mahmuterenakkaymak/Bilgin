# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T85: M7 entegrasyonu — depoya işlenmiş Excel fixture'larından şemaya, gerçek zincir.

Burada elle yapılmış sahte yok: iki fixture gerçek ``read_workbook`` ile okunur, başlıkları gerçek
sözlük (``fallback_mapping``) eşler, tüm satırları gerçek ``convert`` geçirir. Düzgün harita
schema/schema.json'u birebir döndürür, dağınık müşteri haritası aynı tablo ve kolon adlarını verir.
İkinci yarı aynı zinciri ``import-map --accept --llm fake`` ile gerçek alt süreçte koşar; ``--llm
fake`` CLI'ın kendi boru hattı istemcisidir, şema tmp yola yazılır (R3-2).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from bilgin import config
from bilgin.schema_map.excel import convert, fallback_mapping, read_workbook

FIXTURES = Path(__file__).parent / "fixtures"
TIDY = str(FIXTURES / "map_erp_style.xlsx")
MESSY = str(FIXTURES / "map_customer_map.xlsx")
MESSY_REL = "tests/fixtures/map_customer_map.xlsx"


def _tables() -> list[dict]:
    """Şemanın convert'in ürettiği alanları; kind/keywords Run 2, pii Run 3 ekleri — Excel'de karşılığı yok."""
    with open(config.SCHEMA_PATH, encoding="utf-8") as handle:
        tables = json.load(handle)["tables"]
    return [
        {
            **{k: t[k] for k in ("name", "description", "module")},
            "columns": [
                {k: column[k] for k in ("name", "type", "description", "fk", "values", "nullable")}
                for column in t["columns"]
            ],
        }
        for t in tables
    ]


def test_tidy_fixture_round_trips_to_the_canonical_schema():
    report = convert(TIDY, fallback_mapping(read_workbook(TIDY)))
    assert report["skipped"] == []
    assert report["schema"] == {"tables": _tables()}


def test_messy_fixture_yields_the_same_table_and_column_names():
    report = convert(MESSY, fallback_mapping(read_workbook(MESSY)))
    expected = _tables()
    assert [t["name"] for t in report["schema"]["tables"]] == [t["name"] for t in expected]
    for got, want in zip(report["schema"]["tables"], expected):
        assert [c["name"] for c in got["columns"]] == [c["name"] for c in want["columns"]]


def test_cli_import_map_accept_writes_the_schema_to_out(tmp_path):
    out = tmp_path / "imported.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bilgin",
            "import-map",
            MESSY_REL,
            "--accept",
            "--llm",
            "fake",
            "--out",
            str(out),
        ],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    assert result.returncode == 0, result.stdout + result.stderr

    tables = json.loads(out.read_text(encoding="utf-8"))["tables"]
    assert [t["name"] for t in tables] == [t["name"] for t in _tables()]
