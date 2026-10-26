"""Bilgin şablonunun okuyucusu: doldurulmuş dosyadan veri kümesi, şema ve kurallar (PLAN R6-14).

Şablonun iki yüzü vardır: `Veri kümesi` ve `İş kuralları` Bilgin'in sabit biçimidir ve R6-12'nin
başlıklarıyla buradan okunur; `Tablolar` ve `Kolonlar` ise Run 3'ün borosundan geçer - sözlük
eşlemesi ve `convert`. Böylece şablon için LLM'e hiç gerek kalmaz. `Örnek`, `Nasıl doldurulur` ve
`_bilgin` hiçbir sonuca karışmaz: ilki biçimi gösterir, ikincisi talimat, üçüncüsü damga.

Şablon olmayan bir çalışma kitabı Run 3'ün yolundan gider: başlık önerisi modele sorulur (llm
verilmişse), sözlük eşlemesi her durumda altta yatar. İki yolda da bir `Veri kümesi` satırı
şarttır, çünkü her yükleme yeni bir veri kümesi yaratır.

Hücre hataları `MapIssue` olarak birikir ve okuma durmaz: kullanıcı hepsini aynı raporda görsün,
dosyayı düzeltip yeniden yüklemesi tek tur sürsün.

Doğrulama (R6-15) okunan sözlüğü bütün olarak ele alır: hücre kusurları okumada zaten
adreslenmiştir, buradakiler şablonun kendi bütünlüğüdür - veri kümesi satırı, Tablolar/Kolonlar
bağı, benzersiz adlar, çözülen referanslar, kurallar ve istenirse canlı veritabanının iskeleti.

ASSUMPTION: şablonun DEĞERLER başlığı sözlüğe `values` eşanlamlısı olarak eklendi (R6-13'ün
sözlüğü tekili biliyordu); okuyucu yine sözlüğü kullanır, kendine ikinci bir eşleme tablosu
çıkarmaz.
"""

from __future__ import annotations

import datetime
import re
from pathlib import Path
from typing import Any

import openpyxl

from nl2sql import config, datasets
from nl2sql.index import text
from nl2sql.schema_map import excel, merge, rules_edit
from nl2sql.schema_map.template import (
    COLUMN_HEADERS,
    DATASET_HEADERS,
    INFO_SHEET,
    RULE_HEADERS,
    SHEETS,
    TABLE_HEADERS,
    TEMPLATE_MARK,
)

# Sayfa adları yazıcıyla aynı sabitlerden gelir; biri değişirse iki taraf birden kırılır.
DATASET_SHEET, TABLE_SHEET, COLUMN_SHEET, RULE_SHEET = SHEETS[1], SHEETS[2], SHEETS[3], SHEETS[4]
_SCHEMA_SHEETS = (TABLE_SHEET, COLUMN_SHEET)
# Şema olmayan sayfalar: şablon olmayan bir dosyada da şemaya karışmazlar.
_FIXED_SHEETS = (SHEETS[0], DATASET_SHEET, RULE_SHEET, SHEETS[5], INFO_SHEET)

_AD, _GORUNEN_AD, _BAGLANTI, _VARSAYILAN_SEMA, _VERI_TARIHI = DATASET_HEADERS
_KIMLIK, _TERIM, _ES_ANLAMLILAR, _TANIM, _SQL_IPUCU, _TABLOLAR = RULE_HEADERS
# Kolonlar'ın zorunlu üç hücresi ve E/H listesi olan iki hücresi.
_TABLO, _KOLON, _TIP = COLUMN_HEADERS[:3]
_KAPALI, _REFERANS, _NULL = COLUMN_HEADERS[6], COLUMN_HEADERS[7], COLUMN_HEADERS[8]
_ACIKLAMA = TABLE_HEADERS[2]  # Kolonlar'ın açıklama başlığıyla aynı metin

_EH = ("e", "h")


class TemplateError(ValueError):
    """Yüklenen dosya bir veri kümesi tanımlamıyor: adını taşıdığı sayfa yok."""


def is_bilgin_template(path: str | Path) -> bool:
    """Gizli `_bilgin` sayfasının A1 hücresi şablonun damgasını taşıyor mu?"""
    return _stamp(path)[0]


def read_template(path: str | Path, llm=None) -> dict:
    """Doldurulmuş şablonu (ya da şema haritasını) TemplateRead sözlüğüne çevirir."""
    template, names = _stamp(path)
    if DATASET_SHEET not in names:
        raise TemplateError("Veri kümesi sayfası yok: Bilgin şablonunu kullanın.")
    converted = excel.convert(path, _schema_mapping(path, template, names, llm))
    schema = converted["schema"]
    rules = _rules(path) if RULE_SHEET in names else []
    return {
        "dataset": _dataset(path),
        "schema": schema,
        "rules": rules,
        "counts": _counts(schema, converted["columns"], rules),
        "errors": _issues(converted["skipped"]) + (_cell_issues(path, names) if template else []),
        "warnings": [],
        "template": template,
    }


def _stamp(path: str | Path) -> tuple[bool, list[str]]:
    """(şablon mu, sayfa adları): damga ile hangi sayfaların gerçekten olduğu tek açılışta çıkar."""
    book = openpyxl.load_workbook(path, data_only=True)
    try:
        names = list(book.sheetnames)
        mark = INFO_SHEET in names and _text(book[INFO_SHEET]["A1"].value) == TEMPLATE_MARK
        return mark, names
    finally:
        book.close()


def _schema_mapping(path: str | Path, template: bool, names: list[str], llm) -> dict:
    """Şemayı taşıyan sayfaların eşlemesi: şablon sözlükle geçer, harita öneri yolundan da."""
    if template:
        return excel.fallback_mapping(_preview(path, [n for n in _SCHEMA_SHEETS if n in names]))
    preview = excel.read_workbook(path)
    mapping = excel.propose(preview, llm) if llm else excel.fallback_mapping(preview)
    mapping["sheets"] = [
        sheet
        for sheet in mapping["sheets"]
        if sheet["sheet"] not in _FIXED_SHEETS and _says_anything(sheet)
    ]
    return mapping


def _preview(path: str | Path, names: list[str]) -> dict:
    """Yalnız istenen sayfaların önizlemesi; satırlar boş - sözlük başlıklara bakar, satırları
    `convert` kendisi okur.

    ASSUMPTION: `read_workbook` her sayfada başlık satırı arar; `Nasıl doldurulur` ve `_bilgin`
    başlık satırı taşımadığı için şablon yolu onları ona hiç sokmaz (R6-12'nin ASSUMPTION'ı).
    """
    sheets = []
    for name in names:
        number, headers, _ = excel.sheet_rows(path, name)
        sheets.append({"name": name, "header_row": number, "headers": headers, "rows": []})
    return {"file": str(path), "sheets": sheets}


def _says_anything(sheet: dict) -> bool:
    """Sayfa hiçbir alan iddia etmiyorsa şema sayfası değildir; boş sayfanın gürültüsü üretilmez."""
    return any(
        value
        for column in sheet.get("columns") or []
        for name, value in column.items()
        if name != "column"
    )


def _dataset(path: str | Path) -> dict:
    """Veri kümesi sayfasının tek dolu satırı; boş hücre sözleşmenin varsayılanıdır."""
    _, headers, rows = excel.sheet_rows(path, DATASET_SHEET)
    cells = next((cells for _, cells in rows if any(_text(value) for value in cells)), ())
    return {
        "name": _cell(cells, headers, _AD),
        "display_name": _cell(cells, headers, _GORUNEN_AD),
        # ASSUMPTION: boş BAĞLANTI sözleşmenin varsayılanıdır; uydurulan bir ad değil, listesi var.
        "connection": _cell(cells, headers, _BAGLANTI).lower() or "mssql",
        "default_schema": _cell(cells, headers, _VARSAYILAN_SEMA) or None,
        "as_of": _as_of(cells, headers),
    }


def _as_of(cells: tuple, headers: list[str]) -> str:
    """VERİ TARİHİ: Excel'in tarih hücresi de düz metni de aynı ISO güne iner."""
    value = _raw(cells, headers, _VERI_TARIHI)
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    return _text(value)


def _rules(path: str | Path) -> list[dict]:
    """İş kuralları sayfasının dolu satırları; EŞ ANLAMLILAR ve TABLOLAR , ; ile ayrılır."""
    _, headers, rows = excel.sheet_rows(path, RULE_SHEET)
    rules = []
    for _, cells in rows:
        if not any(_text(value) for value in cells):
            continue
        rules.append(
            rules_edit.normalize_rule(
                {
                    "id": _cell(cells, headers, _KIMLIK),
                    "term": _cell(cells, headers, _TERIM),
                    "synonyms": _list(_cell(cells, headers, _ES_ANLAMLILAR)),
                    "definition": _cell(cells, headers, _TANIM),
                    "sql_hint": _cell(cells, headers, _SQL_IPUCU),
                    "tables": _list(_cell(cells, headers, _TABLOLAR)),
                }
            )
        )
    return rules


def _counts(schema: dict, columns: int, rules: list[dict]) -> dict:
    """Raporun sayıları: kullanıcı ne yüklediğini bunlardan okur."""
    marked = [column for table in schema["tables"] for column in table["columns"]]
    return {
        "tables": len(schema["tables"]),
        "columns": columns,
        "pii": sum(1 for column in marked if column.get("pii")),
        "deny": sum(1 for column in marked if column.get("deny")),
        "references": sum(1 for column in marked if column.get("fk")),
        "rules": len(rules),
    }


def _cell_issues(path: str | Path, names: list[str]) -> list[dict]:
    """Şablonun kendi hücre kuralları: zorunlu hücreler ve E/H listeleri.

    `convert` boş TİP'i NVARCHAR(255) sayar, KAPALI'daki "Y"yi kapalı değil sayar; şablon
    ikisinde de uydurmaz, kullanıcıya sorar. KİŞİSEL VERİ sınıfını ve REFERANS biçimini zaten
    `convert` notluyor, burada yinelenmez.
    """
    issues: list[dict] = []
    for sheet, required in ((TABLE_SHEET, (_TABLO,)), (COLUMN_SHEET, (_TABLO, _KOLON, _TIP))):
        if sheet not in names:
            continue
        _, headers, rows = excel.sheet_rows(path, sheet)
        for number, cells in rows:
            if not any(_text(value) for value in cells):
                continue  # şablonun stil dolu 200 boş satırı dolgu, eksik hücresi sayılmaz
            for header in required:
                if not _cell(cells, headers, header):
                    issues.append(_issue(sheet, number, header, f"{header} boş; satır şemaya alınmadı."))
            for header in (_KAPALI, _NULL):
                value = _cell(cells, headers, header)
                if value and text.fold(value) not in _EH:
                    issues.append(_issue(sheet, number, header, f"{header} '{value}'; E ya da H olmalı."))
    return issues


def _issues(notes: list[dict]) -> list[dict]:
    """convert'in atlanan satır notları MapIssue'a döner: kullanıcı kusuru sayfada bulur."""
    return [_issue(note["sheet"], note["row"], None, note["reason"]) for note in notes]


def _issue(sheet: str, row: int | None, column: str | None, message: str) -> dict:
    return {"sheet": sheet, "row": row, "column": column, "message": message}


def _cell(cells: tuple, headers: list[str], header: str) -> str:
    return _text(_raw(cells, headers, header))


def _raw(cells: tuple, headers: list[str], header: str) -> Any:
    """Başlığın hücresi; sayfada o başlık yok ya da satır oraya ulaşmıyorsa boş."""
    index = next(
        (i for i, value in enumerate(headers) if text.fold(value) == text.fold(header)), None
    )
    return None if index is None or index >= len(cells) else cells[index]


def _list(value: str) -> list[str]:
    """'ciro, satış tutarı; hasılat' -> üç sözcük; boş hücre boş liste."""
    return [word.strip() for word in re.split(r"[,;]+", value) if word.strip()]


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


# --- Doğrulama (PLAN R6-15): errors boş değilse yükleme uygulanmaz. ---

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CONNECTIONS = ("mssql", "sqlite")
_NO_DB = "Canlı veritabanı bağlantısı yok; karşılaştırma yapılmadı."
_MAX_NAMES = 20  # bir uyarıda sıralanan kolon adı sayısı
# rules_edit.validate_rule alanlarının şablondaki başlık karşılıkları.
_RULE_FIELDS = {
    "id": _KIMLIK,
    "term": _TERIM,
    "definition": _TANIM,
    "tables": _TABLOLAR,
    "synonyms": _ES_ANLAMLILAR,
}


def validate(read: dict, db_skeleton: dict | None = None) -> tuple[list[dict], list[dict], dict]:
    """TemplateRead -> (errors, warnings, db_check): errors boşsa yükleme uygulanabilir.

    `db_skeleton` verilmezse canlı karşılaştırma yapılmaz, uydurulmaz; verilirse şablonun
    veritabanında olmayanı hata, veritabanının şablonda olmayanı uyarıdır.

    ASSUMPTION: TemplateRead satır numaralarını taşımaz; okumanın kendi hataları sayfa ve satır
    adresini korur, burada eklenenler sayfa ile sütun başlığını söyler.
    """
    errors = list(read["errors"]) + _dataset_errors(read["dataset"]) + _schema_errors(read)
    errors += _rule_errors(read)
    db_check, db_errors, db_warnings = _db_check(read["schema"], db_skeleton)
    return errors + db_errors, _meaning_warnings(read) + db_warnings, db_check


def _dataset_errors(dataset: dict) -> list[dict]:
    """Veri kümesi satırı: ad klasör adıdır, bağlantı iki lehçeden biridir, tarih ISO'dur."""
    name = dataset.get("name", "")
    errors = []
    if not name:
        errors.append(_issue(DATASET_SHEET, None, _AD, "AD boş; veri kümesinin klasör adını yazın."))
    elif not re.match(config.DATASET_NAME_RE, name):
        errors.append(_issue(
            DATASET_SHEET,
            None,
            _AD,
            f"AD '{name}' geçersiz; küçük harfle başlayan 3-31 karakter (a-z, 0-9, _).",
        ))
    elif datasets.name_taken(name):
        errors.append(_issue(DATASET_SHEET, None, _AD, f"Bu ad zaten bir veri kümesi: {name}."))
    connection = dataset.get("connection", "")
    if connection not in _CONNECTIONS:
        errors.append(_issue(
            DATASET_SHEET, None, _BAGLANTI, f"BAĞLANTI '{connection}'; mssql ya da sqlite olmalı."
        ))
    as_of = dataset.get("as_of", "")
    if not _is_iso(as_of):
        errors.append(_issue(
            DATASET_SHEET, None, _VERI_TARIHI, f"VERİ TARİHİ '{as_of}'; ISO tarih (YYYY-AA-GG) olmalı."
        ))
    return errors


def _schema_errors(read: dict) -> list[dict]:
    """Şablonun kendi bütünlüğü: en az bir tablo, bağlı sayfalar, benzersiz adlar, çözülen referanslar."""
    tables = read["schema"]["tables"]
    if not tables:
        return [_issue(TABLE_SHEET, None, None, "Şablonda hiç tablo yok.")]
    errors = []
    declared = set()
    for table in tables:
        if table["name"] in declared:
            errors.append(_issue(TABLE_SHEET, None, _TABLO, f"Tablo iki kez tanımlı: {table['name']}."))
        declared.add(table["name"])
        if read.get("template") and not _in_table_sheet(table):
            errors.append(_issue(
                COLUMN_SHEET,
                None,
                _TABLO,
                f"'{table['name']}' Tablolar sayfasında yok; her tablonun orada bir satırı olmalı.",
            ))
        columns = set()
        for column in table["columns"]:
            if column["name"] in columns:
                errors.append(_issue(
                    COLUMN_SHEET,
                    None,
                    _KOLON,
                    f"Kolon iki kez tanımlı: {table['name']}.{column['name']}.",
                ))
            columns.add(column["name"])
    known = {(table["name"], column["name"]) for table in tables for column in table["columns"]}
    for table in tables:
        for column in table["columns"]:
            fk = column.get("fk")
            if fk and _target(fk) not in known:
                errors.append(_issue(
                    COLUMN_SHEET,
                    None,
                    _REFERANS,
                    f"REFERANS '{fk}' şablonda yok; hedef kolon Kolonlar sayfasında olmalı.",
                ))
    return errors


def _in_table_sheet(table: dict) -> bool:
    """Tabloyu Tablolar'ın satırı mı açtı: convert `keywords` anahtarını yalnız ANAHTAR KELİMELER
    başlığı olan sayfada açar (R6-13), o başlık şablonda tek yerde durur.

    ASSUMPTION: böylece Kolonlar'dan doğup Tablolar'a hiç yazılmamış tablo ayırt edilir;
    TemplateRead sayfaları taşımadığı için başka bir işaret yoktur.
    """
    return "keywords" in table


def _is_iso(value: str) -> bool:
    """ISO tarih: biçim ve gerçek gün - `2026-02-30` Excel'e göre tarih, takvime göre değil."""
    if not _ISO_DATE.match(value):
        return False
    try:
        datetime.date.fromisoformat(value)
    except ValueError:
        return False
    return True


def _target(fk: str) -> tuple[str, str]:
    """'SATIS.CARI.CARIKOD' -> ('SATIS.CARI', 'CARIKOD'): referansın hedefi tablo ve kolonu."""
    table, _, column = fk.rpartition(".")
    return table, column


def _rule_errors(read: dict) -> list[dict]:
    """Kurallar okunan şemaya göre doğrulanır; her kural kendisi dışındaki kimliklere de bakar."""
    rules = read["rules"]
    errors = []
    for rule in rules:
        others = [other for other in rules if other is not rule]
        for problem in rules_edit.validate_rule(rule, read["schema"], others):
            errors.append(_issue(
                RULE_SHEET,
                None,
                _RULE_FIELDS.get(problem["field"]),
                f"Kural '{rule['id']}': {problem['message']}",
            ))
    return errors


def _meaning_warnings(read: dict) -> list[dict]:
    """Açıklamasız tablo ve kolonlar yüklemeyi durdurmaz ama model o alanı aranamaz hâle getirir."""
    tables = read["schema"]["tables"]
    warnings = [
        _issue(
            TABLE_SHEET,
            None,
            _ACIKLAMA,
            f"{table['name']} açıklamasız; model tabloyu yalnız oraya yazılan metinden bilir.",
        )
        for table in tables
        if not table.get("description")
    ]
    empty = [
        f"{table['name']}.{column['name']}"
        for table in tables
        for column in table["columns"]
        if not column.get("description")
    ]
    if empty:
        tail = "…" if len(empty) > _MAX_NAMES else ""
        warnings.append(_issue(
            COLUMN_SHEET,
            None,
            _ACIKLAMA,
            f"{len(empty)} kolon açıklamasız: {', '.join(empty[:_MAX_NAMES])}{tail}",
        ))
    return warnings


def _db_check(schema: dict, db_skeleton: dict | None) -> tuple[dict, list[dict], list[dict]]:
    """Canlı iskeletle fark (R6-15): şablonun fazlası sorgulanamaz olduğu için hata, iskeletin
    fazlası yalnız eksik tanımdır, uyarı.
    """
    if not db_skeleton:
        return {"checked": False, "missing_in_db": [], "only_in_db": [], "message": _NO_DB}, [], []
    diff = merge.diff_map(schema, db_skeleton)
    missing, only = _refs(diff, "excel_only"), _refs(diff, "db_only")
    errors = [
        _issue(sheet, None, column, f"{column.capitalize()} veritabanında yok: {name}.")
        for sheet, column, name in missing
    ]
    warnings = [
        _issue(sheet, None, column, f"{column.capitalize()} yalnız veritabanında: {name}.")
        for sheet, column, name in only
    ]
    check = {
        "checked": True,
        "missing_in_db": [name for _, _, name in missing],
        "only_in_db": [name for _, _, name in only],
        "message": None,
    }
    return check, errors, warnings


def _refs(diff: dict, side: str) -> list[tuple[str, str, str]]:
    """DiffReport'un bir tarafı: (sayfa, sütun başlığı, ad) - başlık mesajın öznesi de olur."""
    return [
        (TABLE_SHEET, _TABLO, name) for name in diff[f"{side}_tables"]
    ] + [
        (COLUMN_SHEET, _KOLON, f"{item['table']}.{item['column']}")
        for item in diff[f"{side}_columns"]
    ]
