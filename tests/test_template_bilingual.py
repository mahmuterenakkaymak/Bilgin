# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T416: iki dilin şablonu aynı okumaya çıkar (PLAN R8-12).

Aynı içerik iki ayrı şablona yazılır - biri Türkçe başlıklarla, biri İngilizce - ve beklenen şey
ikisinin tek bir okumaya inmesidir: aynı şema, aynı kurallar, aynı sayılar. Fark yalnız kullanıciya
görünen cümlelerdedir, o da isteğin dilinden gelir: bir İngilizce şablonu Türkçe önizlemek
serbesttir. Uygulama da aynı kanıtı diskte verir - iki şablondan doğan `schema.json` ve
`rules.json` bayt bayt aynıdır.

Evet/hayır hücreleri dosyanın kendi listesinden yargılanır: Türkçe şablon E/H sunar, İngilizce
Y/N; uzun yazımlar (Evet/Hayır, Yes/No) iki tarafta da aynı iki anlama iner. Sayfa ve sütun
adresleri testte rol adlarıyla verilir, böylece hiçbir test tek bir dile yazılmış metin taşımaz.
"""

import io
import json

import openpyxl
import pytest

from nl2sql import config
from nl2sql.i18n.scan import user_literals
from nl2sql.schema_map import onboard
from nl2sql.schema_map.template import LABELS, build_template
from nl2sql.schema_map.template_import import read_template, validate

TABLE = "Satis.Fatura"
SHEET_ROLES = ("guide", "dataset", "tables", "columns", "rules", "example")
TURKISH = "çğıöşüÇĞİÖŞÜ"

DATASET_ROW = ("cift_dil", "Çift dil", "sqlite", "dbo", "2026-10-01")
TABLE_ROW = (
    TABLE,
    "Satış",
    "Satış faturasının üst kaydı; her satır bir faturadır.",
    "fatura, satış belgesi",
)
# Son iki hücre işarettir: kapalı ve boş bırakılabilir. Yazımı şablonun kendi listesi verir.
COLUMN_ROWS = (
    (TABLE, "FaturaID", "INT", "Faturanın numarası", "", "", False, "", False),
    (TABLE, "Tutar", "DECIMAL(18,2)", "Fatura tutarı, KDV hariç", "", "", False, "", True),
    (TABLE, "IcNot", "NVARCHAR(250)", "Faturaya düşülen iç not", "", "", True, "", True),
    (TABLE, "CariKod", "NVARCHAR(20)", "Faturanın kesildiği carinin kodu", "", "", False,
     f"{TABLE}.FaturaID", False),
)
RULE_ROW = (
    "fatura_tutari",
    "Fatura tutarı",
    "ciro, satış tutarı",
    "Bir faturanın KDV hariç toplamı.",
    "SUM(Fatura.Tutar)",
    TABLE,
    "invoice amount, revenue",
)
_ROWS = {"dataset": (DATASET_ROW,), "tables": (TABLE_ROW,), "columns": COLUMN_ROWS,
         "rules": (RULE_ROW,)}
# Sayfa ve sütun adresleri: (şablon sayfasının sırası, başlık demeti, alan adları).
_ADDRESSES = {
    "dataset": (1, "dataset_headers", ("name", "display_name", "connection", "default_schema",
                                       "as_of")),
    "tables": (2, "table_headers", ("table_name", "module", "description", "keywords")),
    "columns": (3, "column_headers", ("table_name", "column_name", "data_type", "description",
                                      "values", "pii", "deny", "fk_target", "nullable")),
    "rules": (4, "rule_headers", ("id", "term", "synonyms", "definition", "sql_hint", "tables",
                                  "synonyms_en")),
}


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Küme klasörleri tmp'de: iki uygulama da kendi boş klasörüne doğar, repo anılmaz."""
    (tmp_path / "datasets").mkdir()
    (tmp_path / "real_datasets").mkdir()
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(tmp_path / "datasets"))
    monkeypatch.setenv("NL2SQL_REAL_DATASETS_DIR", str(tmp_path / "real_datasets"))
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "MAP_PREVIEWS_DIR", tmp_path / "map_previews")
    monkeypatch.setattr(config, "MAP_CHANGES_LOG", tmp_path / "logs" / "map_changes.jsonl")
    return tmp_path


def sheet_of(lang: str, role: str) -> str:
    return LABELS[lang]["sheets"][_ADDRESSES[role][0]]


def header_of(lang: str, role: str, field: str) -> str:
    index, key, fields = _ADDRESSES[role]
    return LABELS[lang][key][fields.index(field)]


def filled(tmp_path, lang: str, name: str = "cift_dil", cells=()) -> str:
    """Aynı içeriğin o dilin başlıklarıyla yazıldığı şablon.

    `cells` [(sayfa rolü, satır ya da None, alan, değer)]: None o sayfanın bütün dolu satırlarıdır.
    """
    book = openpyxl.load_workbook(io.BytesIO(build_template(lang=lang)))
    rows = {"dataset": [(name, *DATASET_ROW[1:])], "tables": [TABLE_ROW],
            "columns": [tuple(boolean(value, lang) for value in row) for row in COLUMN_ROWS],
            "rules": [RULE_ROW]}
    for role, values in rows.items():
        sheet = sheet_of(lang, role)
        for offset, row in enumerate(values, start=2):
            for column, value in enumerate(row, start=1):
                if value not in (None, ""):
                    book[sheet].cell(row=offset, column=column, value=value)
    for role, row, field, value in cells:
        sheet = sheet_of(lang, role)
        headers = [item.value for item in book[sheet][1]]
        column = headers.index(header_of(lang, role, field)) + 1
        for target in (row,) if row else range(2, 2 + len(_ROWS[role])):
            book[sheet].cell(row=target, column=column).value = value
    stream = io.BytesIO()
    book.save(stream)
    path = tmp_path / f"{lang}.xlsx"
    path.write_bytes(stream.getvalue())
    return str(path)


def boolean(value, lang: str):
    """İşaretin şablonun kendi listesindeki yazımı: E/H ya da Y/N; metin olduğu gibi kalır."""
    if not isinstance(value, bool):
        return value
    return LABELS[lang]["yes"] if value else LABELS[lang]["no"]


def report(tmp_path, lang: str, request: str, cells=()) -> dict:
    """Okuma + doğrulama: arayüzün önizlediği kontrol raporunun kendisi."""
    read = read_template(filled(tmp_path, lang, cells=cells), lang=request)
    errors, warnings, db_check = validate(read, lang=request)
    return {"read": read, "errors": errors, "warnings": warnings, "db_check": db_check}


def place(issue: dict, lang: str) -> tuple:
    """Kusurun dosyadaki yeri: sayfa rolü, satır, alan - dilin yazımı değil."""
    for role, (index, key, fields) in _ADDRESSES.items():
        if issue["sheet"] == LABELS[lang]["sheets"][index]:
            headers = LABELS[lang][key]
            column = issue["column"]
            return (role, issue["row"], fields[headers.index(column)] if column in headers
                    else column)
    return (issue["sheet"], issue["row"], issue["column"])


def marks(tmp_path, lang: str, **cells) -> dict:
    """KAPALI/NULL hücreleri elle yazılmış bir dosyanın kolonları: ad -> kolon."""
    edits = [("columns", None, field, value) for field, value in cells.items()]
    read = read_template(filled(tmp_path, lang, cells=edits))
    assert read["errors"] == []
    return {column["name"]: column for column in read["schema"]["tables"][0]["columns"]}


def applied(tmp_path, roots, lang: str) -> dict:
    """Şablonun küme klasörü olarak uygulanması: diske düşen iki dosyanın baytları."""
    read = read_template(filled(tmp_path, lang, name=f"bir_{lang}"))
    errors, warnings, db_check = validate(read)
    assert errors == []
    preview = onboard.save_preview(
        {
            "dataset": read["dataset"],
            "counts": read["counts"],
            "errors": errors,
            "warnings": warnings,
            "db_check": db_check,
            "schema": read["schema"],
            "rules": read["rules"],
        },
        "eren",
        f"{lang}.xlsx",
    )
    folder = onboard.apply_preview(onboard.load_preview(preview), "eren")
    return {name: (folder / name).read_bytes() for name in ("schema.json", "rules.json")}


def speaks_turkish(text: str) -> bool:
    return any(character in TURKISH for character in text)


def sentence(issue: dict) -> str:
    """Mesajın çevrilen yüzü: adres yazısı dosyanın kendi başlığıdır, cümlenin dili sayılmaz."""
    return issue["message"].replace(issue["column"] or "", "")


# ------------------------------------------------------------------ aynı içerik, tek okuma


def test_the_same_content_in_two_languages_reads_as_one(tmp_path):
    turkish = read_template(filled(tmp_path, "tr"))
    english = read_template(filled(tmp_path, "en"))

    assert english["schema"] == turkish["schema"]
    assert english["rules"] == turkish["rules"]
    assert english["dataset"] == turkish["dataset"]
    assert english["counts"] == turkish["counts"] == {"tables": 1, "columns": 4, "pii": 0,
                                                     "deny": 1, "references": 1, "rules": 1}
    assert english["template"] is True


def test_the_clean_content_needs_nothing_in_either_language(tmp_path):
    for lang in ("tr", "en"):
        result = report(tmp_path, lang, lang)
        assert result["errors"] == []
        assert result["warnings"] == []


def test_the_marks_land_on_the_same_columns_in_both_languages(tmp_path):
    columns = {
        lang: {column["name"]: column
               for column in read_template(filled(tmp_path, lang))["schema"]["tables"][0]["columns"]}
        for lang in ("tr", "en")
    }

    assert columns["en"] == columns["tr"]
    assert columns["en"]["ICNOT"]["deny"] is True
    assert columns["en"]["FATURAID"]["deny"] is False
    assert columns["en"]["FATURAID"]["nullable"] is False
    assert columns["en"]["TUTAR"]["nullable"] is True
    assert columns["en"]["CARIKOD"]["fk"] == f"{TABLE.upper()}.FATURAID"


def test_the_addresses_are_the_ones_the_user_sees_in_their_own_file(tmp_path):
    for lang in ("tr", "en"):
        read = read_template(filled(tmp_path, lang))
        assert {role: entry["name"] for role, entry in read["sheets"].items()} == {
            role: LABELS[lang]["sheets"][_ADDRESSES[role][0]] for role in _ADDRESSES
        }


def test_the_english_template_applies_to_the_same_bytes(tmp_path, roots):
    assert applied(tmp_path, roots, "en") == applied(tmp_path, roots, "tr")


# ------------------------------------------------------------------ rapor isteğin dilinde


def test_a_missing_type_is_reported_where_the_user_sees_it(tmp_path):
    for lang in ("tr", "en"):
        result = report(tmp_path, lang, lang, cells=(("columns", 3, "data_type", None),))
        assert len(result["errors"]) == 1
        issue = result["errors"][0]
        assert place(issue, lang) == ("columns", 3, "data_type")
        assert issue["message"].startswith(header_of(lang, "columns", "data_type"))
        assert speaks_turkish(issue["message"]) is (lang == "tr")


def test_the_report_language_is_not_the_template_language(tmp_path):
    for lang, other in (("tr", "en"), ("en", "tr")):
        cells = (("columns", 3, "data_type", None),)
        own = report(tmp_path, lang, lang, cells=cells)
        foreign = report(tmp_path, lang, other, cells=cells)

        assert [place(issue, lang) for issue in own["errors"]] == [
            place(issue, lang) for issue in foreign["errors"]
        ]
        assert all(speaks_turkish(sentence(issue)) is (lang == "tr") for issue in own["errors"])
        assert all(speaks_turkish(sentence(issue)) is (other == "tr")
                   for issue in foreign["errors"])


def test_the_database_note_follows_the_request_language(tmp_path):
    for lang in ("tr", "en"):
        message = report(tmp_path, lang, lang)["db_check"]["message"]
        assert speaks_turkish(message) is (lang == "tr")


# ------------------------------------------------------------------ evet / hayır


def test_each_template_reads_its_own_boolean_list(tmp_path):
    for lang, yes, no in (("tr", "E", "H"), ("en", "Y", "N")):
        columns = marks(tmp_path, lang, deny=yes, nullable=no)
        assert [column["deny"] for column in columns.values()] == [True] * 4
        assert [column["nullable"] for column in columns.values()] == [False] * 4


def test_the_long_spellings_mean_the_same_two_things(tmp_path):
    for lang, yes, no in (("tr", "Evet", "Hayır"), ("en", "Yes", "No")):
        assert marks(tmp_path, lang, deny=yes)["FATURAID"]["deny"] is True
        assert marks(tmp_path, lang, deny=no)["FATURAID"]["deny"] is False
        assert marks(tmp_path, lang, nullable=yes)["FATURAID"]["nullable"] is True
        assert marks(tmp_path, lang, nullable=no)["FATURAID"]["nullable"] is False


def test_a_word_from_the_other_languages_list_is_refused(tmp_path):
    for lang, value in (("tr", "Y"), ("en", "E")):
        result = report(tmp_path, lang, lang, cells=(("columns", 3, "deny", value),))
        assert len(result["errors"]) == 1
        issue = result["errors"][0]
        assert place(issue, lang) == ("columns", 3, "deny")
        assert value in issue["message"]
        assert speaks_turkish(issue["message"]) is (lang == "tr")


# ------------------------------------------------------------------ sözlük ve tarama


def test_both_languages_name_their_sheets_in_the_dictionary():
    with open(config.EXCEL_HEADERS_PATH, encoding="utf-8") as handle:
        sheets = json.load(handle)["sheets"]

    for lang in LABELS:
        for name, role in zip(LABELS[lang]["sheets"], SHEET_ROLES):
            assert sheets[name] == role


def test_every_english_schema_header_is_in_the_dictionary():
    with open(config.EXCEL_HEADERS_PATH, encoding="utf-8") as handle:
        table = json.load(handle)
    words = {
        word.casefold()
        for entries in table.values()
        if isinstance(entries, list)
        for word in entries
    }

    for header in (*LABELS["en"]["table_headers"], *LABELS["en"]["column_headers"]):
        assert header.casefold() in words


def test_no_turkish_literal_is_left_outside_the_docstrings():
    assert user_literals("nl2sql/schema_map/template_import.py") == []
