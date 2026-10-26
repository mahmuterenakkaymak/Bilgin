"""T83: iki Excel fixture'ı (PLAN R3-2).

map_erp_style.xlsx düzgün tek sayfalık harita; fallback_mapping + convert tam tur atıp
schema/schema.json'u birebir vermeli. map_customer_map.xlsx dağınık müşteri haritası: iki sayfa,
farklı başlık sırası, üstte başlık ve boş satır, boş TABLO hücreleri, karışık büyük/küçük harf
tipler, bazı açıklamalar silinmiş; tablo ve kolon adları aynı kalmalı.
"""

import json
from pathlib import Path

from nl2sql import config
from nl2sql.schema_map.excel import convert, fallback_mapping, read_workbook

FIXTURES = Path(__file__).parent / "fixtures"
TIDY = str(FIXTURES / "map_erp_style.xlsx")
MESSY = str(FIXTURES / "map_customer_map.xlsx")


def _schema() -> dict:
    with open(config.SCHEMA_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _expected() -> dict:
    """convert'in ürettiği alanlar; kind/keywords Run 2, pii Run 3 ekleri — Excel başlığında karşılığı yok."""
    return {
        "tables": [
            {
                **{k: t[k] for k in ("name", "description", "module")},
                "columns": [
                    {k: column[k] for k in ("name", "type", "description", "fk", "values", "nullable")}
                    for column in t["columns"]
                ],
            }
            for t in _schema()["tables"]
        ]
    }


def test_tidy_header_row_is_first():
    preview = read_workbook(TIDY)
    assert len(preview["sheets"]) == 1
    assert preview["sheets"][0]["header_row"] == 1


def test_messy_header_row_is_third():
    preview = read_workbook(MESSY)
    assert [s["name"] for s in preview["sheets"]] == ["TABLOLAR", "KOLONLAR"]
    for sheet in preview["sheets"]:
        assert sheet["header_row"] == 3, "üstte başlık ve boş satır var"


def test_tidy_round_trip_equals_schema_json():
    report = convert(TIDY, fallback_mapping(read_workbook(TIDY)))
    assert report["skipped"] == []
    assert report["schema"] == _expected()


def test_messy_same_table_and_column_names():
    report = convert(MESSY, fallback_mapping(read_workbook(MESSY)))
    expected = _schema()["tables"]
    got = report["schema"]["tables"]
    assert [t["name"] for t in got] == [t["name"] for t in expected]
    for g, w in zip(got, expected):
        assert [c["name"] for c in g["columns"]] == [c["name"] for c in w["columns"]]


def test_messy_kept_descriptions_match_schema():
    report = convert(MESSY, fallback_mapping(read_workbook(MESSY)))
    for g, w in zip(report["schema"]["tables"], _schema()["tables"]):
        assert g["description"] == w["description"]
        for gc, wc in zip(g["columns"], w["columns"]):
            if gc["description"]:
                assert gc["description"] == wc["description"]
