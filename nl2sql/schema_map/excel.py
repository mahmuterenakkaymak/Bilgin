"""Excel şema haritasını okuma: sayfalar, başlık satırı ve önizleme satırları (PLAN R3-2).

Başlık satırı, dolu metin hücresi sayısı eşiği geçen ilk satırdır; üstünde kalan satırlar (dosya
adı, boş satır) atılır - müşterinin haritasında başlık her zaman 1. satırda değil. Önizleme LLM'e
gittiği için satır sayısı config.EXCEL_PREVIEW_ROWS ile sınırlıdır; hücreler dönüştürülmeden, ham
değeriyle döner, böylece tip yazımı (`18,2` mi `DECIMAL(18,2)` mi) burada karara bağlanmaz.

Başlık eşleme (PLAN R3-3) başlık metnini profiles/excel_headers.json ile yapar: hangi kelimenin
hangi alan olduğunu dosya söyler, Python ERP bilgisi taşımaz. Eşleşmeyen başlık tüm alanları null
kalarak görünür kalır; uydurma alan adı sessizce geçiştirilmez.

Öneri adımı (PLAN R3-2) eşlemeyi modele sorar; model yalnızca sayfa adı, başlık ve önizleme
satırlarını görür. Sözlük her durumda çalışır ve öneriyi yoklar: iki tarafın aynı sütun için
farklı iddiası varsa uyuşmazlık sessizce çözülmez, mapping'in yanında kullanıcıya taşınır.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from nl2sql import config
from nl2sql.agent.llm import LLMError
from nl2sql.index import text

# Sayı ile dolu bir satır başlık değildir; eşik metin hücreleri üzerinden sayılır.
_HEADER_TEXT_CELLS = 3

# Mapping kaydının taşıdığı alanlar (Contracts); sözlükte sırası olmayan alan eşlenemez.
_FIELDS = (
    "table_name",
    "column_name",
    "data_type",
    "description",
    "fk_target",
    "values",
    "nullable",
    "module",
)


class SheetError(RuntimeError):
    """Sayfada başlık satırı bulunamadı: boş sayfa ya da eşiği geçen tek satır yok."""


def read_workbook(path: str | Path) -> dict:
    """Her sayfa için önizleme: 1-tabanlı başlık satırı, başlıklar ve ilk EXCEL_PREVIEW_ROWS satır."""
    book = openpyxl.load_workbook(path, data_only=True)
    try:
        sheets = [_read_sheet(sheet) for sheet in book.worksheets]
    finally:
        book.close()
    return {"file": str(path), "sheets": sheets}


def _read_sheet(sheet: Worksheet) -> dict:
    rows = list(sheet.iter_rows(values_only=True))
    for number, row in enumerate(rows, start=1):
        if _text_cells(row) >= _HEADER_TEXT_CELLS:
            return {
                "name": sheet.title,
                "header_row": number,
                "headers": [_text(value) for value in row],
                "rows": [list(item) for item in rows[number : number + config.EXCEL_PREVIEW_ROWS]],
            }
    raise SheetError(
        f"'{sheet.title}' sayfasında başlık satırı yok; en az {_HEADER_TEXT_CELLS} dolu "
        "metin hücresi olan bir satır gerekir."
    )


def _text_cells(row: tuple[Any, ...]) -> int:
    return sum(1 for value in row if isinstance(value, str) and value.strip())


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def fallback_mapping(
    preview: dict, path: str | Path = config.EXCEL_HEADERS_PATH
) -> dict:
    """Başlıkları sözlükle tanıyarak mapping üretir; LLM'e hiç ihtiyaç kalmayan deterministik yol."""
    synonyms = _synonyms(path)
    return {
        "file": preview["file"],
        "generated_by": "fallback",
        "sheets": [_fallback_sheet(sheet, synonyms) for sheet in preview["sheets"]],
        "disagreements": [],
    }


def _fallback_sheet(sheet: dict, synonyms: dict[str, set[str]]) -> dict:
    columns = []
    for index, header in enumerate(sheet["headers"]):
        field = _match(synonyms, header)
        column = {"column": header or get_column_letter(index + 1)}
        for name in _FIELDS:
            column[name] = header if name == field else None
        columns.append(column)
    return {"sheet": sheet["name"], "header_row": sheet["header_row"], "columns": columns}


def _synonyms(path: str | Path) -> dict[str, set[str]]:
    """Alan -> katlanmış başlıklar.

    ASSUMPTION: TÜR hem tip hem değer için yazılabiliyor; dosyada hangisi önce duruyorsa o alan
    kazanır (excel_headers.json'da data_type önde), böylece tek başlık iki alana bölünmüyor.
    """
    with open(path, encoding="utf-8") as handle:
        table = json.load(handle)
    for field, words in table.items():
        if field not in _FIELDS:
            raise ValueError(
                f"excel_headers bilinmeyen alan '{field}'; bilinenler {list(_FIELDS)}."
            )
    return {field: {text.fold(word) for word in words} for field, words in table.items()}


def _match(synonyms: dict[str, set[str]], header: str) -> str | None:
    folded = text.fold(header)
    if not folded:
        return None
    for field, words in synonyms.items():
        if folded in words:
            return field
    return None


# Modelin uyması gereken biçim: sekiz alanın adı ve değer olarak başlık metni. Değerler
# önizlemeden değil başlıktan gelir, böylece model satırdaki bir veriyi alan sanmaz.
PROPOSE_SYSTEM = """Aşağıda bir Excel şema haritasının sayfa adları, başlık satırı metinleri ve \
önizleme satırları JSON olarak veriliyor. Her sütunun hangi şema alanını taşıdığını belirle.

ÇIKTI - YALNIZCA JSON, başka metin yazma:
{"sheets": [{"sheet": "<sayfa adı>", "columns": [{"column": "<başlık metni veya sütun harfi>", \
"table_name": null, "column_name": null, "data_type": null, "description": null, "fk_target": \
null, "values": null, "nullable": null, "module": null}]}]}

KURALLAR
1. column alanına sütunun başlık metnini, başlığı boşsa Excel sütun harfini yaz.
2. Sütun bir alanı taşıyorsa o alanın değeri o sütunun başlık metni olsun; taşımadığı alanları \
null bırak.
3. Hiçbir alanı taşımayan sütunda bütün alanlar null olsun; yukarıdaki sekiz alanın dışına çıkma.
4. fk_target yalnızca TABLE.COL biçiminde referans veren sütundur; values kod=açıklama çiftleri \
tutan sütundur; nullable boş/dolu bilgisini taşıyan sütundur.
5. Yalnızca gördüğün sayfa ve sütunları kullan; önizleme satırları anlamak içindir, değer \
olarak yazılmaz.
"""


def propose(preview: dict, llm) -> dict:
    """Modelden başlık önerisi ister, sözlük eşlemesiyle birleştirir (PLAN R3-2, R3-3)."""
    fallback = fallback_mapping(preview)
    try:
        reply = llm.chat(
            [
                {"role": "system", "content": PROPOSE_SYSTEM},
                {"role": "user", "content": _proposal_input(preview)},
            ]
        )
    except LLMError as exc:
        print(f"Öneri modelden alınamadı; başlık sözlüğüyle ilerleniyor. {exc}")
        return fallback
    proposal = _parse_json(reply.content)
    if proposal is None:
        print("Model JSON önerisi dönmedi; başlık sözlüğüyle ilerleniyor.")
        return fallback
    return _merge(preview, proposal, fallback)


def _proposal_input(preview: dict) -> str:
    """Modelin gördüğü tek metin: sayfa adları, başlıklar ve önizleme satırları; dosya adı gitmez."""
    return json.dumps(
        {
            "sheets": [
                {"name": sheet["name"], "headers": sheet["headers"], "rows": sheet["rows"]}
                for sheet in preview["sheets"]
            ]
        },
        ensure_ascii=False,
        default=str,
    )


def _parse_json(content: str) -> dict | None:
    """Yanıtı JSON sayar; kod bloğu tırnakları ve JSON'un çevresine yazılan sözler kendiliğinden düşer."""
    body = content or ""
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        parsed = json.loads(body[start : end + 1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _merge(preview: dict, proposal: dict, fallback: dict) -> dict:
    """Öneriyi sözlüğün üstüne yazar; önerinin söylemediğini sözlük söyler, çelişkiyi ikisi de görür."""
    claimed = _claim(proposal, preview)
    sheets: list[dict] = []
    disagreements: list[dict] = []
    for sheet in fallback["sheets"]:
        columns = []
        for index, entry in enumerate(sheet["columns"]):
            fields = claimed.get((sheet["sheet"], index))
            columns.append(
                _proposed(entry, fields, sheet["sheet"], disagreements) if fields else entry
            )
        sheets.append({**sheet, "columns": columns})
    return {
        "file": preview["file"],
        "generated_by": "llm",
        "sheets": sheets,
        "disagreements": disagreements,
    }


def _proposed(entry: dict, fields: set[str], sheet: str, disagreements: list[dict]) -> dict:
    """Modelin bir sütuna verdiği alanlar; sözlüğün alanıyla çelişirse uyuşmazlık kayda geçer."""
    header = entry["column"]
    known = {name for name in _FIELDS if entry[name] is not None}
    if known and known != fields:
        for name in _FIELDS:
            if (name in fields) != (name in known):
                disagreements.append(
                    {
                        "sheet": sheet,
                        "column": header,
                        "field": name,
                        "llm": header if name in fields else None,
                        "fallback": header if name in known else None,
                    }
                )
    return {"column": header, **{name: header if name in fields else None for name in _FIELDS}}


def _claim(proposal: dict, preview: dict) -> dict[tuple[str, int], set[str]]:
    """Öneriyi önizlemeye göre doğrular: bilinmeyen sayfa ve sütun notla düşer, eksik alan null sayılır."""
    references = {sheet["name"]: _references(sheet) for sheet in preview["sheets"]}
    claim: dict[tuple[str, int], set[str]] = {}
    for entry in proposal.get("sheets") or []:
        if not isinstance(entry, dict):
            continue
        name = _text(entry.get("sheet"))
        if name not in references:
            print(f"Önerideki bilinmeyen sayfa düşürüldü: '{name}'.")
            continue
        for column in entry.get("columns") or []:
            if not isinstance(column, dict):
                continue
            ref = _text(column.get("column"))
            index = references[name].get(text.fold(ref)) if ref else None
            if index is None:
                print(f"Önerideki bilinmeyen sütun düşürüldü: '{name}.{ref}'.")
                continue
            fields = claim.setdefault((name, index), set())
            fields.update(field for field in _FIELDS if column.get(field))
    return claim


def _references(sheet: dict) -> dict[str, int]:
    """Başlık metni veya sütun harfi -> sütun indeksi; model ikisini de yazabilir."""
    refs: dict[str, int] = {}
    for index, header in enumerate(sheet["headers"]):
        refs.setdefault(text.fold(_text(header)), index)
        refs.setdefault(text.fold(get_column_letter(index + 1)), index)
    return refs
