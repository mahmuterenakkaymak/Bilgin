"""T83: iki Excel fixture'ı (PLAN R3-2).

map_tidy.xlsx düzgün tek sayfalık harita; fallback_mapping + convert tam tur atıp
schema/schema.json'u birebir vermeli. map_customer_map.xlsx dağınık müşteri haritası: iki sayfa,
farklı başlık sırası, üstte başlık ve boş satır, boş TABLO hücreleri, karışık büyük/küçük harf
tipler, bazı açıklamalar silinmiş; tablo ve kolon adları aynı kalmalı.
"""

import json
from pathlib import Path

from nl2sql import config
from nl2sql.schema_map.excel import convert, fallback_mapping, read_workbook

FIXTURES = Path(__file__).parent / "fixtures"
TIDY = str(FIXTURES / "map_tidy.xlsx")
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


def test_messy_header_row_is_third():
    preview = read_workbook(MESSY)
    assert [s["name"] for s in preview["sheets"]] == ["TABLOLAR", "KOLONLAR"]
    for sheet in preview["sheets"]:
        assert sheet["header_row"] == 3, "üstte başlık ve boş satır var"


