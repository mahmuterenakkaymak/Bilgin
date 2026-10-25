"""T83: iki Excel fixture'ını config.SCHEMA_PATH'ten üretir (PLAN R3-2).

Çalıştırma: .venv/Scripts/python tests/fixtures/make_maps.py
"""

import json
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent.parent
FIXTURES = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from nl2sql import config  # noqa: E402

SCHEMA_PATH = config.SCHEMA_PATH

TIDY_HEADERS = ["TABLO", "KOLON", "TİP", "AÇIKLAMA", "REFERANS", "DEĞER", "NULL", "MODÜL"]
TAB_HEADERS = ["MODÜL", "TABLO ADI", "AÇIKLAMA"]
COL_HEADERS = ["TABLO", "ALAN", "TÜR", "AÇIKLAMA", "FK", "DEĞER", "BOŞ"]


def _vals(values: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in values.items())


def _null(nullable: bool) -> str:
    return "" if nullable else "H"


def make_tidy_map(schema: dict, path: Path) -> None:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "KOLONLAR"
    sheet.append(TIDY_HEADERS)
    for table in schema["tables"]:
        if table["description"]:
            sheet.append(
                [table["name"], "", "", table["description"], "", "", "", table["module"]]
            )
        for col in table["columns"]:
            sheet.append([
                table["name"],
                col["name"],
                col["type"],
                col["description"],
                col["fk"] or "",
                _vals(col["values"]),
                _null(col["nullable"]),
                table["module"],
            ])
    book.save(path)


def make_customer_map(schema: dict, path: Path) -> None:
    book = openpyxl.Workbook()
    book.remove(book.active)
    tab = book.create_sheet("TABLOLAR")
    tab.append(["MÜŞTERİ ŞEMA HARİTASI"])
    tab.append([])
    tab.append(TAB_HEADERS)
    for table in schema["tables"]:
        tab.append([table["module"], table["name"], table["description"]])
    kol = book.create_sheet("KOLONLAR")
    kol.append(["MÜŞTERİ ŞEMA HARİTASI"])
    kol.append([])
    kol.append(COL_HEADERS)
    for table in schema["tables"]:
        for j, col in enumerate(table["columns"]):
            kol.append([
                table["name"] if j == 0 else "",
                col["name"],
                col["type"].lower() if j % 2 == 0 else col["type"],
                "" if j % 3 == 0 else col["description"],
                col["fk"] or "",
                _vals(col["values"]),
                _null(col["nullable"]),
            ])
    book.save(path)


if __name__ == "__main__":
    with open(SCHEMA_PATH, encoding="utf-8") as handle:
        schema = json.load(handle)
    tidy = FIXTURES / "map_tidy.xlsx"
    messy = FIXTURES / "map_customer_map.xlsx"
    make_tidy_map(schema, tidy)
    make_customer_map(schema, messy)
    print(f"Üretildi: {tidy}")
    print(f"Üretildi: {messy}")
