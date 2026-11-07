# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

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

R8-12: şablon hangi dilde doldurulmuşsa aynı okuyucudan geçer. Sayfa adları
profiles/excel_headers.json'ın `sheets` eşlemesinden, başlıklar `template.LABELS`ın iki dilinden
tanınır; kullanıciya görünen adresler daima dosyanın kendi yazımıdır. `lang` yalnız raporu hangi
dilde yazacağını söyler: İngilizce bir şablonu Türkçe önizlemek serbesttir, yani ikisi
birbirinden bağımsızdır. Evet/hayır hücreleri ise dosyanın kendi listesinden yargılanır -
şablonun açılır listesi hangi iki yazımı sunuyorsa geçerli olan odur.

ASSUMPTION: şablonun DEĞERLER başlığı sözlüğe `values` eşanlamlısı olarak eklendi (R6-13'ün
sözlüğü tekili biliyordu); okuyucu yine sözlüğü kullanır, kendine ikinci bir eşleme tablosu
çıkarmaz.
"""

from __future__ import annotations

import datetime
import json
import re
from pathlib import Path
from typing import Any

import openpyxl

from bilgin import config, datasets
from bilgin.i18n import t
from bilgin.index import text
from bilgin.schema_map import excel, merge, rules_edit, template
from bilgin.schema_map.template import INFO_SHEET, TEMPLATE_MARK

# Şemanın sırası önce Tablolar, sonra Kolonlar gelir: convert tabloyu ilk gördüğü sayfada açar.
_SCHEMA_ROLES = ("tables", "columns")
# Adres defterinin sayfaları; `Nasıl doldurulur` ve `Örnek` hiçbir sonuca karışmaz.
_ADDRESSED = ("dataset", "tables", "columns", "rules")
_OTHER_ROLES = ("guide", "dataset", "rules", "example")

# Alan rolleri: iki şablon dili aynı sütun sırasını paylaştığı için başlık sıradan tanınır.
_ROLES = {
    "dataset": (
        "dataset_headers",
        ("name", "display_name", "connection", "default_schema", "as_of"),
    ),
    "tables": ("table_headers", ("table_name", "module", "description", "keywords")),
    "columns": (
        "column_headers",
        (
            "table_name",
            "column_name",
            "data_type",
            "description",
            "values",
            "pii",
            "deny",
            "fk_target",
            "nullable",
        ),
    ),
    "rules": (
        "rule_headers",
        ("id", "term", "synonyms", "definition", "sql_hint", "tables", "synonyms_en"),
    ),
}
# Zorunlu hücreler ve evet/hayır listesi olan hücreler (R6-14): alan adlarıyla söylenir.
_REQUIRED = {"tables": ("table_name",), "columns": ("table_name", "column_name", "data_type")}
_BOOLEAN_FIELDS = {"columns": ("deny", "nullable")}
# Şablonun iki dili kendi açılır listesini sunar; uzun yazımlar katlamadan aynı iki anlama iner.
_BOOLEAN_WORDS = {"tr": ("e", "h", "evet", "hayir"), "en": ("y", "n", "yes", "no")}
# Mesajın öznesi olan varlık sözü: (başlık demeti, sözcüğün sırası).
_ENTITIES = {"tables": ("table_headers", 0), "columns": ("column_headers", 1)}


class TemplateError(ValueError):
    """Yüklenen dosya bir veri kümesi tanımlamıyor: adını taşıdığı sayfa yok."""


def is_bilgin_template(path: str | Path) -> bool:
    """Gizli `_bilgin` sayfasının A1 hücresi şablonun damgasını taşıyor mu?"""
    return _stamp(path)[0]


def read_template(path: str | Path, llm=None, lang: str = "tr") -> dict:
    """Doldurulmuş şablonu (ya da şema haritasını) TemplateRead sözlüğüne çevirir."""
    stamped, names, declared = _stamp(path)
    sheets = _sheets(names)
    if "dataset" not in sheets:
        raise TemplateError(t("template.issue.no_dataset_sheet", lang))
    converted = excel.convert(path, _schema_mapping(path, stamped, names, sheets, llm))
    rows = _rows(path, sheets)
    schema = converted["schema"]
    rules = _rules(rows["rules"], declared) if "rules" in rows else []
    return {
        "dataset": _dataset(rows["dataset"], declared),
        "schema": schema,
        "rules": rules,
        "counts": _counts(schema, converted["columns"], rules),
        "errors": _issues(converted["skipped"])
        + (_cell_issues(rows, declared, lang) if stamped else []),
        "warnings": [],
        "template": stamped,
        "sheets": _addresses(rows, declared),
    }


def _stamp(path: str | Path) -> tuple[bool, list[str], str]:
    """(şablon mu, sayfa adları, şablonun dili): damga, hangi sayfaların gerçekten olduğu ve
    dosyanın hangi dilin listelerini taşıdığı tek açılışta çıkar.

    ASSUMPTION: dili olmayan damga Türkçe sayılır - `_bilgin`in `lang` satırı R8-12'de eklendi.
    """
    book = openpyxl.load_workbook(path, data_only=True)
    try:
        names = list(book.sheetnames)
        stamped = INFO_SHEET in names and _text(book[INFO_SHEET]["A1"].value) == TEMPLATE_MARK
        declared = _text(book[INFO_SHEET]["B2"].value) if stamped else ""
        return stamped, names, declared if declared in template.LABELS else "tr"
    finally:
        book.close()


def _profile(path: str | Path = config.EXCEL_HEADERS_PATH) -> dict:
    """Başlık sözlüğü ve sayfa adı -> görev eşlemesi: ikisi de tek dosyada durur (R8-12)."""
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _sheets(names: list[str]) -> dict[str, str]:
    """Sayfa rolleri: iki dilin şablon adı aynı göreve çıkar, o yüzden rol dile bakmaz."""
    roles = {text.fold(name): role for name, role in _profile()["sheets"].items()}
    found: dict[str, str] = {}
    for name in names:
        role = roles.get(text.fold(name))
        if role and role not in found:
            found[role] = name
    return found


def _schema_mapping(path: str | Path, stamped: bool, names: list[str], sheets: dict, llm) -> dict:
    """Şemayı taşıyan sayfaların eşlemesi: şablon sözlükle geçer, harita öneri yolundan da."""
    if stamped:
        return excel.fallback_mapping(
            _preview(path, [sheets[role] for role in _SCHEMA_ROLES if role in sheets])
        )
    preview = excel.read_workbook(path)
    mapping = excel.propose(preview, llm) if llm else excel.fallback_mapping(preview)
    fixed = {name for role, name in sheets.items() if role in _OTHER_ROLES} | {INFO_SHEET}
    mapping["sheets"] = [
        sheet
        for sheet in mapping["sheets"]
        if sheet["sheet"] not in fixed and _says_anything(sheet)
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


def _rows(path: str | Path, sheets: dict) -> dict:
    """Adreslenecek her sayfanın başlıkları ve numaralı satırları: sayfa başına tek açılış."""
    gathered: dict[str, dict] = {}
    for role in _ADDRESSED:
        if role not in sheets:
            continue
        _, headers, numbered = excel.sheet_rows(path, sheets[role])
        gathered[role] = {"name": sheets[role], "headers": headers, "rows": numbered}
    return gathered


def _roles(headers: list[str], role: str, declared: str) -> dict[str, str]:
    """Alan -> başlık yazımı: iki dilin başlığı da tanınır ve yazım dosyanın kendisinden alınır,
    çünkü kullanıcı kusuru Excel'de gördüğü adla arar.

    ASSUMPTION: sütun hiç yoksa alan şablonun dilindeki yazımıyla anılır; bir satırın eksik
    hücresini raporlamak için başka adres yoktur.
    """
    key, names = _ROLES[role]
    found = {name: template.LABELS[declared][key][index] for index, name in enumerate(names)}
    words: dict[str, str] = {}
    for labels in template.LABELS.values():
        for name, header in zip(names, labels[key]):
            words.setdefault(text.fold(header), name)
    seen: set[str] = set()
    for value in headers:
        name = words.get(text.fold(value))
        if name and name not in seen:
            seen.add(name)
            found[name] = _text(value)
    return found


def _addresses(rows: dict, declared: str) -> dict:
    """Okumanın adres defteri: her rolün sayfa adı (yoksa None) ve alanlarının başlık yazımı.
    Doğrulama (R6-15) dosyayı yeniden açmaz, kullanıciya görünecek adresi buradan okur."""
    return {
        role: {
            "name": rows[role]["name"] if role in rows else None,
            "headers": _roles(rows[role]["headers"] if role in rows else [], role, declared),
        }
        for role in _ADDRESSED
    }


def _address(read: dict, role: str) -> tuple[str | None, dict[str, str]]:
    """Adres defterinden bir sayfanın adı ve başlık yazımları."""
    entry = read["sheets"][role]
    return entry["name"], entry["headers"]


def _dataset(entry: dict, declared: str) -> dict:
    """Veri kümesi sayfasının tek dolu satırı; boş hücre sözleşmenin varsayılanıdır."""
    headers, fields = entry["headers"], _roles(entry["headers"], "dataset", declared)
    cells = next(
        (cells for _, cells in entry["rows"] if any(_text(value) for value in cells)), ()
    )
    return {
        "name": _cell(cells, headers, fields["name"]),
        "display_name": _cell(cells, headers, fields["display_name"]),
        # ASSUMPTION: boş bağlantı hücresi sözleşmenin varsayılanıdır; uydurulan bir ad değil, listesi var.
        "connection": _cell(cells, headers, fields["connection"]).lower() or "mssql",
        "default_schema": _cell(cells, headers, fields["default_schema"]) or None,
        "as_of": _as_of(cells, headers, fields["as_of"]),
    }


def _as_of(cells: tuple, headers: list[str], header: str) -> str:
    """VERİ TARİHİ: Excel'in tarih hücresi de düz metni de aynı ISO güne iner."""
    value = _raw(cells, headers, header)
    if isinstance(value, datetime.datetime):
        return value.date().isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    return _text(value)


def _rules(entry: dict, declared: str) -> list[dict]:
    """İş kuralları sayfasının dolu satırları; eş anlamlılar ve TABLOLAR , ; ile ayrılır."""
    headers, fields = entry["headers"], _roles(entry["headers"], "rules", declared)
    rules = []
    for _, cells in entry["rows"]:
        if not any(_text(value) for value in cells):
            continue
        rules.append(
            rules_edit.normalize_rule(
                {
                    "id": _cell(cells, headers, fields["id"]),
                    "term": _cell(cells, headers, fields["term"]),
                    "synonyms": _list(_cell(cells, headers, fields["synonyms"])),
                    "definition": _cell(cells, headers, fields["definition"]),
                    "sql_hint": _cell(cells, headers, fields["sql_hint"]),
                    "tables": _list(_cell(cells, headers, fields["tables"])),
                    # EŞ ANLAMLILAR (EN)/SYNONYMS (EN) hücresi kuralın `synonyms_en` alanıdır (R8-13);
                    # doluysa normalize edene girer, boşken diskte hiç görünmez.
                    "synonyms_en": _list(_cell(cells, headers, fields["synonyms_en"])),
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


def _cell_issues(rows: dict, declared: str, lang: str) -> list[dict]:
    """Şablonun kendi hücre kuralları: zorunlu hücreler ve evet/hayır listeleri.

    `convert` boş TİP'i NVARCHAR(255) sayar, KAPALI'daki "Y"yi kapalı değil sayar; şablon
    ikisinde de uydurmaz, kullanıcıya sorar. KİŞİSEL VERİ sınıfını ve REFERANS biçimini zaten
    `convert` notluyor, burada yinelenmez.
    """
    issues: list[dict] = []
    for role in _SCHEMA_ROLES:
        if role not in rows:
            continue
        sheet, headers = rows[role]["name"], rows[role]["headers"]
        fields = _roles(headers, role, declared)
        for number, cells in rows[role]["rows"]:
            if not any(_text(value) for value in cells):
                continue  # şablonun stil dolu 200 boş satırı dolgu, eksik hücresi sayılmaz
            for field in _REQUIRED[role]:
                header = fields[field]
                if not _cell(cells, headers, header):
                    issues.append(
                        _issue(
                            sheet,
                            number,
                            header,
                            t("template.issue.required_cell", lang, header=header),
                        )
                    )
            for field in _BOOLEAN_FIELDS.get(role, ()):
                header = fields[field]
                value = _cell(cells, headers, header)
                if value and not excel.is_boolean(value, _BOOLEAN_WORDS[declared]):
                    issues.append(
                        _issue(
                            sheet,
                            number,
                            header,
                            t(
                                "template.issue.boolean_cell",
                                lang,
                                header=header,
                                value=value,
                                yes=template.LABELS[declared]["yes"],
                                no=template.LABELS[declared]["no"],
                            ),
                        )
                    )
    return issues


def _issues(notes: list[dict]) -> list[dict]:
    """convert'in atlanan satır notları MapIssue'a döner: kullanıcı kusuru sayfada bulur."""
    return [_issue(note["sheet"], note["row"], None, note["reason"]) for note in notes]


def _issue(sheet: str | None, row: int | None, column: str | None, message: str) -> dict:
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
_MAX_NAMES = 20  # bir uyarıda sıralanan kolon adı sayısı


def validate(
    read: dict, db_skeleton: dict | None = None, lang: str = "tr"
) -> tuple[list[dict], list[dict], dict]:
    """TemplateRead -> (errors, warnings, db_check): errors boşsa yükleme uygulanabilir.

    `db_skeleton` verilmezse canlı karşılaştırma yapılmaz, uydurulmaz; verilirse şablonun
    veritabanında olmayanı hata, veritabanının şablonda olmayanı uyarıdır.

    ASSUMPTION: TemplateRead satır numaralarını taşımaz; okumanın kendi hataları sayfa ve satır
    adresini korur, burada eklenenler sayfa ile sütun başlığını söyler.
    """
    errors = list(read["errors"]) + _dataset_errors(read, lang) + _schema_errors(read, lang)
    errors += _rule_errors(read, lang)
    db_check, db_errors, db_warnings = _db_check(read, db_skeleton, lang)
    return errors + db_errors, _meaning_warnings(read, lang) + db_warnings, db_check


def _dataset_errors(read: dict, lang: str) -> list[dict]:
    """Veri kümesi satırı: ad klasör adıdır, bağlantı iki lehçeden biridir, tarih ISO'dur."""
    sheet, fields = _address(read, "dataset")
    dataset = read["dataset"]
    name = dataset.get("name", "")
    errors = []
    if not name:
        errors.append(_issue(
            sheet,
            None,
            fields["name"],
            t("template.issue.dataset_name_empty", lang, header=fields["name"]),
        ))
    elif not re.match(config.DATASET_NAME_RE, name):
        errors.append(_issue(
            sheet,
            None,
            fields["name"],
            t("template.issue.dataset_name_pattern", lang, header=fields["name"], value=name),
        ))
    elif datasets.name_taken(name):
        errors.append(_issue(sheet, None, fields["name"], t("map.name_taken", lang, name=name)))
    connection = dataset.get("connection", "")
    if connection not in _CONNECTIONS:
        errors.append(_issue(
            sheet,
            None,
            fields["connection"],
            t(
                "template.issue.dataset_connection",
                lang,
                header=fields["connection"],
                value=connection,
            ),
        ))
    as_of = dataset.get("as_of", "")
    if not _is_iso(as_of):
        errors.append(_issue(
            sheet,
            None,
            fields["as_of"],
            t("template.issue.dataset_as_of", lang, header=fields["as_of"], value=as_of),
        ))
    return errors


def _schema_errors(read: dict, lang: str) -> list[dict]:
    """Şablonun kendi bütünlüğü: en az bir tablo, bağlı sayfalar, benzersiz adlar, çözülen referanslar."""
    table_sheet, table_fields = _address(read, "tables")
    column_sheet, column_fields = _address(read, "columns")
    tables = read["schema"]["tables"]
    if not tables:
        return [_issue(table_sheet, None, None, t("template.issue.no_tables", lang))]
    errors = []
    declared = set()
    for table in tables:
        if table["name"] in declared:
            errors.append(_issue(
                table_sheet,
                None,
                table_fields["table_name"],
                t("template.issue.duplicate_table", lang, name=table["name"]),
            ))
        declared.add(table["name"])
        if read.get("template") and not _in_table_sheet(table):
            errors.append(_issue(
                column_sheet,
                None,
                table_fields["table_name"],
                t("template.issue.table_not_declared", lang, name=table["name"], sheet=table_sheet),
            ))
        columns = set()
        for column in table["columns"]:
            if column["name"] in columns:
                errors.append(_issue(
                    column_sheet,
                    None,
                    column_fields["column_name"],
                    t(
                        "template.issue.duplicate_column",
                        lang,
                        name=f"{table['name']}.{column['name']}",
                    ),
                ))
            columns.add(column["name"])
    known = {(table["name"], column["name"]) for table in tables for column in table["columns"]}
    for table in tables:
        for column in table["columns"]:
            fk = column.get("fk")
            if fk and _target(fk) not in known:
                errors.append(_issue(
                    column_sheet,
                    None,
                    column_fields["fk_target"],
                    t(
                        "template.issue.unknown_reference",
                        lang,
                        header=column_fields["fk_target"],
                        fk=fk,
                        sheet=column_sheet,
                    ),
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


def _rule_errors(read: dict, lang: str) -> list[dict]:
    """Kurallar okunan şemaya göre doğrulanır; her kural kendisi dışındaki kimliklere de bakar."""
    sheet, fields = _address(read, "rules")
    rules = read["rules"]
    errors = []
    for rule in rules:
        others = [other for other in rules if other is not rule]
        for problem in rules_edit.validate_rule(rule, read["schema"], others, lang=lang):
            errors.append(_issue(
                sheet,
                None,
                fields.get(problem["field"]),
                t("template.issue.rule", lang, id=rule["id"], message=problem["message"]),
            ))
    return errors


def _meaning_warnings(read: dict, lang: str) -> list[dict]:
    """Açıklamasız tablo ve kolonlar yüklemeyi durdurmaz ama model o alanı aranamaz hâle getirir."""
    table_sheet, table_fields = _address(read, "tables")
    column_sheet, column_fields = _address(read, "columns")
    tables = read["schema"]["tables"]
    warnings = [
        _issue(
            table_sheet,
            None,
            table_fields["description"],
            t("template.issue.table_no_description", lang, name=table["name"]),
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
            column_sheet,
            None,
            column_fields["description"],
            t(
                "template.issue.columns_no_description",
                lang,
                count=len(empty),
                names=", ".join(empty[:_MAX_NAMES]),
                tail=tail,
            ),
        ))
    return warnings


def _entity(lang: str, role: str) -> str:
    """Mesajın öznesi: tablo ya da kolon sözü, o dilin başlık yazımından (R8-12)."""
    key, index = _ENTITIES[role]
    return template.LABELS[lang][key][index].capitalize()


def _db_check(
    read: dict, db_skeleton: dict | None, lang: str
) -> tuple[dict, list[dict], list[dict]]:
    """Canlı iskeletle fark (R6-15): şablonun fazlası sorgulanamaz olduğu için hata, iskeletin
    fazlası yalnız eksik tanımdır, uyarı.
    """
    if not db_skeleton:
        return {
            "checked": False,
            "missing_in_db": [],
            "only_in_db": [],
            "message": t("template.issue.no_db", lang),
        }, [], []
    diff = merge.diff_map(read["schema"], db_skeleton)
    missing, only = _refs(diff, "excel_only"), _refs(diff, "db_only")
    check = {
        "checked": True,
        "missing_in_db": [name for _, name in missing],
        "only_in_db": [name for _, name in only],
        "message": None,
    }
    return check, _diff_issues(read, missing, "template.issue.db_missing", lang), _diff_issues(
        read, only, "template.issue.db_only", lang
    )


def _diff_issues(read: dict, refs: list[tuple[str, str]], key: str, lang: str) -> list[dict]:
    """İskelet farkının bir tarafı: adres ve özne dosyanın kendi dilinden, mesaj isteğin dilinden."""
    issues = []
    for role, name in refs:
        sheet, fields = _address(read, role)
        field = "table_name" if role == "tables" else "column_name"
        issues.append(
            _issue(
                sheet, None, fields[field], t(key, lang, what=_entity(lang, role), name=name)
            )
        )
    return issues


def _refs(diff: dict, side: str) -> list[tuple[str, str]]:
    """DiffReport'un bir tarafı: (sayfa rolü, ad) - adres de mesajın öznesi de oradan gelir."""
    return [
        ("tables", name) for name in diff[f"{side}_tables"]
    ] + [
        ("columns", f"{item['table']}.{item['column']}")
        for item in diff[f"{side}_columns"]
    ]
