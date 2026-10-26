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

Dönüşüm adımı (PLAN R3-2) eşlemeyi tüm çalışma kitabına koddan uygular; LLM satırları hiç görmez.
Tablo adı ilk görünüm sırasıyla gruplanır, tipler şemanın T-SQL adlarına çevrilir, values hücreleri
çözülür. Bozuk bir hücre sütunu düşürmez: satır olduğu gibi kalır, sorunu sheet + 1-tabanlı satır
numarasıyla raporla kullanıcıya taşınır.

Şablonun ek alanları (PLAN R6-13) aynı borunun devamıdır: KİŞİSEL VERİ ve KAPALI kolona, ANAHTAR
KELİMELER tabloya yazılır - ama yalnızca sayfa o alanı eşliyorsa, böylece Run 3'ün haritaları ek
alan anahtarı hiç görmez. Hücreyi ham hâliyle görmek isteyen (hücre düzeyinde doğrulama) satırları
`sheet_rows` ile okur.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from nl2sql import config
from nl2sql.agent.llm import LLMError
from nl2sql.index import text
from nl2sql.policy import pii

# Sayı ile dolu bir satır başlık değildir; eşik metin hücreleri üzerinden sayılır.
_HEADER_TEXT_CELLS = 3

# Mapping kaydının taşıdığı alanlar (Contracts); sözlükte sırası olmayan alan eşlenemez.
# İlk sekizi Run 3'ün haritasıdır; son üçü şablonun ek alanları (R6-13) - keywords tabloya gider.
_FIELDS = (
    "table_name",
    "column_name",
    "data_type",
    "description",
    "fk_target",
    "values",
    "nullable",
    "module",
    "pii",
    "deny",
    "keywords",
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
    number = _header_row(rows, sheet.title)
    return {
        "name": sheet.title,
        "header_row": number,
        "headers": [_text(value) for value in rows[number - 1]],
        "rows": [list(item) for item in rows[number : number + config.EXCEL_PREVIEW_ROWS]],
    }


def sheet_rows(path: str | Path, sheet: str) -> tuple[int, list[str], list[tuple[int, tuple]]]:
    """Bir sayfanın ham hâli: 1-tabanlı başlık satırı, başlıklar ve (satır numarası, hücreler).

    Dönüşümün `skipped` notu yalnız kendi gördüğü arızayı söyler; hücre düzeyinde doğrulama
    yapacak taraf (PLAN R6-14) satırları burada dönüştürülmemiş hâliyle ve Excel'de görünen
    numaralarıyla bulur - boş satır da numarasını korur.
    """
    book = openpyxl.load_workbook(path, data_only=True)
    try:
        rows = list(book[sheet].iter_rows(values_only=True))
    finally:
        book.close()
    number = _header_row(rows, sheet)
    headers = [_text(value) for value in rows[number - 1]]
    return number, headers, list(enumerate(rows[number:], start=number + 1))


def _header_row(rows: list[tuple[Any, ...]], title: str) -> int:
    """Başlık satırının 1-tabanlı numarası: eşiği geçen ilk satır (önizleme ve dönüşüm aynı satırı görür)."""
    for number, row in enumerate(rows, start=1):
        if _text_cells(row) >= _HEADER_TEXT_CELLS:
            return number
    raise SheetError(
        f"'{title}' sayfasında başlık satırı yok; en az {_HEADER_TEXT_CELLS} dolu "
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


# --- Satırdan şemaya dönüşüm (PLAN R3-2): tüm satırlar koddan geçer. ---

# Uzunluk verilmemiş serbest metnin şemadaki karşılığı.
_TEXT_TYPE = "NVARCHAR(255)"

# Türkçe tip yazımları -> taban tip adı; "sayı" hücresi ile "INT" hücresi aynı yere çıkar.
_TYPE_WORDS = {
    "sayi": "int",
    "tam sayi": "int",
    "integer": "int",
    "para": "decimal",
    "tutar": "decimal",
    "metin": "nvarchar",
    "yazi": "nvarchar",
    "string": "nvarchar",
    "tarih": "date",
}

_TYPE_RE = re.compile(
    r"^(int|bigint|smallint|bit|real|float|money|date|datetime|datetime2|uniqueidentifier"
    r"|decimal|numeric|varchar|nvarchar|char|nchar)(\(\s*\d+\s*(?:,\s*\d+\s*)?\))?$"
)

# Uzunluk verilmeyen tiplerin şema karşılığı; listesi olmayanlar kendi adıyla geçer.
_TYPE_DEFAULTS = {
    "decimal": "DECIMAL(18,2)",
    "numeric": "DECIMAL(18,2)",
    "varchar": _TEXT_TYPE,
    "nvarchar": _TEXT_TYPE,
    "char": _TEXT_TYPE,
    "nchar": _TEXT_TYPE,
}

# REFERANS iki ya da üç parçalıdır: TABLE.COL ya da SCHEMA.TABLE.COL (PLAN R6-13).
_FK_RE = re.compile(r"^(?:[A-Z0-9_]+\.){1,2}[A-Z0-9_]+$")

# Şemanın kendi şeması adlarda taşınmaz (PLAN R4-6): dbo'nun tablosu şemasız yazılır.
_DEFAULT_SCHEMA = "DBO"

# "Dolu" yazımları; geri kalan her şey (boş hücre dahil) boş bırakılabilir sayılır.
_FILLED_WORDS = frozenset({"h", "hayir", "false", "0", "dolu", "not null", "degil"})

# Katlama İ/I/ı üçünü aynı harfe indirir; tip ve boş/dolu sözcükleri iki yazımla da tanınır.
_TURKISH_LETTERS = str.maketrans("çÇğĞıİöÖşŞüÜ", "cCgGiIoOSSuU")


def convert(path: str | Path, mapping: dict) -> dict:
    """Eşlemeyi tüm çalışma kitabına uygular ve şemayı koddan üretir (PLAN R3-2).

    Adlar şemanın büyük harf kuralına çekilir; gruplama bu hâliyle yapılır, böylece aynı tablonun
    iki yazımı tek tabloda toplanır.
    """
    book = openpyxl.load_workbook(path, data_only=True)
    state: dict = {"tables": {}, "columns": 0, "skipped": []}
    try:
        for entry in mapping.get("sheets") or []:
            name = entry.get("sheet") if isinstance(entry, dict) else None
            if name not in book.sheetnames:
                print(f"Eşlemedeki bilinmeyen sayfa atlandı: '{name}'.")
                continue
            _convert_sheet(book[name], entry, state)
    finally:
        book.close()
    tables = list(state["tables"].values())
    return {
        "schema": {"tables": tables},
        "tables": len(tables),
        "columns": state["columns"],
        "skipped": state["skipped"],
    }


def _convert_sheet(sheet: Worksheet, entry: dict, state: dict) -> None:
    rows = list(sheet.iter_rows(values_only=True))
    header_row = _entry_header_row(entry, rows, sheet.title)
    fields = _field_columns(sheet.title, entry, [_text(value) for value in rows[header_row - 1]])
    table = ""
    for number, row in enumerate(rows[header_row:], start=header_row + 1):
        table = _convert_row(sheet.title, number, row, fields, state, table)


def _entry_header_row(entry: dict, rows: list[tuple[Any, ...]], title: str) -> int:
    """Eşlemedeki 1-tabanlı başlık satırı; kullanıcı düzelttiyse dönüşüm onu uygular.

    ASSUMPTION: sayı olmayan ya da sayfaya sığmayan header_row (elle düzeltilmiş JSON) yok sayılır
    ve otomatik seçim devralır; ucu açık bir numaranın satırı aranmaz.
    """
    number = entry.get("header_row")
    if isinstance(number, int) and 1 <= number <= len(rows):
        return number
    return _header_row(rows, title)


def _field_columns(sheet: str, entry: dict, headers: list[str]) -> dict[str, int]:
    """Eşlemedeki sütun referanslarını (başlık metni ya da harf) indekse çevirir: alan -> sütun."""
    references = _references({"headers": headers})
    fields: dict[str, int] = {}
    for column in entry.get("columns") or []:
        if not isinstance(column, dict):
            continue
        ref = _text(column.get("column"))
        index = references.get(text.fold(ref))
        if index is None:
            print(f"Eşlemedeki bilinmeyen sütun atlandı: '{sheet}.{ref}'.")
            continue
        for field in _FIELDS:
            if column.get(field) and field not in fields:
                fields[field] = index
    return fields


def _convert_row(
    sheet: str, number: int, row: tuple[Any, ...], fields: dict[str, int], state: dict, last: str
) -> str:
    """Bir satırı işler ve ait olduğu tablo adını döndürür; boş TABLO hücresi onu tekrarlar."""
    if not any(_text(value) for value in row):
        # ASSUMPTION: baştan sona boş satır dolgu sayılır, atlanan satır olarak raporlanmaz.
        return last
    # ASSUMPTION: boş TABLO hücresi birleşik hücre gibi bir önceki tabloyu tekrarlar (brief §2);
    # sayfanın henüz tablosu olmadığında ucu açık kalan satır atlanır.
    name = _cell(row, fields, "table_name").upper() or last
    if not name:
        _note(state, sheet, number, "TABLO boş; satır atlandı")
        return last
    table = state["tables"].setdefault(name, _new_table(name, fields))
    description = _text(_cell(row, fields, "description"))
    module = _text(_cell(row, fields, "module"))
    if module and not table["module"]:
        table["module"] = module
    if "keywords" in fields:
        words = _keywords(_cell(row, fields, "keywords"))
        if words and not table.get("keywords"):
            table["keywords"] = words
    column = _cell(row, fields, "column_name").upper()
    if not column:
        # Kolonu olmayan satır tablonun kendi satırıdır; açıklama tabloya aittir.
        if description:
            table["description"] = description
        return name
    if any(item["name"] == column for item in table["columns"]):
        _note(state, sheet, number, f"'{name}.{column}' tekrar ediyor; satır atlandı")
        return name

    raw_type = _cell(row, fields, "data_type")
    data_type = _data_type(raw_type)
    if data_type is None:
        data_type = _TEXT_TYPE
        _note(state, sheet, number, f"tip '{raw_type}' tanınmadı; {_TEXT_TYPE} kullanıldı")
    raw_fk = _cell(row, fields, "fk_target")
    fk = _fk(raw_fk)
    if raw_fk and fk is None:
        _note(
            state,
            sheet,
            number,
            f"REFERANS '{raw_fk}' TABLE.COL ya da SCHEMA.TABLE.COL biçiminde değil; referanssız kaldı",
        )
    raw_values = _cell(row, fields, "values")
    values = _values(raw_values)
    if values is None:
        values = {}
        _note(
            state,
            sheet,
            number,
            f"DEĞER '{raw_values}' çözümlenemedi ('KOD=açıklama' olmalı); değerler boş bırakıldı",
        )
    table["columns"].append(
        {
            "name": column,
            "type": data_type,
            "description": description,
            "fk": fk,
            "values": values,
            "nullable": _nullable(_cell(row, fields, "nullable")),
            **_column_extras(sheet, number, row, fields, state),
        }
    )
    state["columns"] += 1
    return name


def _new_table(name: str, fields: dict[str, int]) -> dict:
    """Yeni tablo kaydı; ANAHTAR KELİMELER anahtarı yalnız sayfa onu eşliyorsa baştan açılır."""
    table = {"name": name, "description": "", "module": ""}
    if "keywords" in fields:
        table["keywords"] = []
    table["columns"] = []
    return table


def _column_extras(
    sheet: str, number: int, row: tuple[Any, ...], fields: dict[str, int], state: dict
) -> dict:
    """Şablonun ek kolon alanları (R6-13): sayfa onları eşlemiyorsa anahtar hiç açılmaz."""
    extras: dict = {}
    if "pii" in fields:
        raw = _cell(row, fields, "pii")
        extras["pii"] = _pii(raw)
        if raw and extras["pii"] is None:
            _note(
                state,
                sheet,
                number,
                f"KİŞİSEL VERİ '{raw}' bilinmeyen bir sınıf; pii bırakılmadı",
            )
    if "deny" in fields:
        extras["deny"] = _deny(_cell(row, fields, "deny"))
    return extras


def _cell(row: tuple[Any, ...], fields: dict[str, int], field: str) -> str:
    """Alanın hücresi; alan hiç eşlenmemişse ya da satır oraya kadar gelmiyorsa boş metin."""
    index = fields.get(field)
    return "" if index is None or index >= len(row) else _text(row[index])


def _note(state: dict, sheet: str, number: int, reason: str) -> None:
    """Satır numarasıyla not: atlanan satır ya da düşen alan, kullanıcı raporda görür."""
    state["skipped"].append({"sheet": sheet, "row": number, "reason": reason})


def _data_type(value: str) -> str | None:
    """Tip hücresini şemanın T-SQL adına çevirir; şemanın kendi adları olduğu gibi geçer."""
    folded = _plain(value)
    if not folded:
        return _TEXT_TYPE
    base = _TYPE_WORDS.get(folded)
    if base is None:
        match = _TYPE_RE.match(folded)
        if not match:
            return None
        base = match.group(1)
        if match.group(2):
            return f"{base.upper()}{match.group(2).replace(' ', '')}"
    return _TYPE_DEFAULTS.get(base, base.upper())


def _fk(value: str) -> str | None:
    """REFERANS hücresi TABLE.COL ya da SCHEMA.TABLE.COL biçimindeyse büyük harfle geçer; değilse None.

    ASSUMPTION: üç parçalının şeması dbo olamaz - R4-6 dbo'nun tablosunu şemasız yazar, bu yüzden
    `DBO.TBL.COL` şemada hiçbir ada çözülmez; kısaltılıp uydurulmak yerine reddedilir ve notu gider.
    """
    upper = value.upper()
    if not _FK_RE.match(upper):
        return None
    return None if upper.startswith(f"{_DEFAULT_SCHEMA}.") else upper


def _values(value: str) -> dict[str, str] | None:
    """'G=Giriş; C=Çıkış' -> {'G': 'Giriş', 'C': 'Çıkış'}; boş hücre {}, çözülemeyen None."""
    if not value:
        return {}
    result: dict[str, str] = {}
    for part in re.split(r"[;\n]+", value):
        code, sep, meaning = part.partition("=")
        code, meaning = code.strip(), meaning.strip()
        if not sep or not code or not meaning:
            return None
        result[code] = meaning
    return result


def _pii(value: str) -> str | None:
    """KİŞİSEL VERİ hücresi; sınıfların birinin adıysa o ad, değilse None (PLAN R6-13).

    ASSUMPTION: tanınmayan yazım ("telefon") sınıf sanılmaz; boş bırakılmadığını kullanıcıya
    söyleyecek olan hücre düzeyindeki doğrulama (R6-14), buradan uydurma bir sınıf geçmez.
    """
    folded = _plain(value)
    return folded if folded in pii.CLASSES else None


def _deny(value: str) -> bool:
    """KAPALI hücresi: şablonun listesi E/H olduğu için yalnız E kolonu kapatır."""
    return _plain(value) == "e"


def _keywords(value: str) -> list[str]:
    """'fiyat, zam; liste fiyatı' -> ['fiyat', 'zam', 'liste fiyatı']; boş hücre boş liste."""
    return [word.strip() for word in re.split(r"[,;]+", value) if word.strip()]


def _nullable(value: str) -> bool:
    """Boş/dolu hücresi; hiçbir şey yazılmamışsa sütun boş bırakılabilir sayılır."""
    return _plain(value) not in _FILLED_WORDS


def _plain(value: str) -> str:
    return value.translate(_TURKISH_LETTERS).lower()
