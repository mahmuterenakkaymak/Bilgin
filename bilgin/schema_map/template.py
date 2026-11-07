# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Bilgin'in Excel şablonu: boş hâli, iskeletle doldurulmuş hâli ve dolu örneği (PLAN R6-12, R8-12).

Şablon, yeni bir veritabanını Bilgin'e tanıtırken doldurulan tek biçimdir; içe aktarma tarafı
(R6-14) aynı sabitleri okuduğu için sayfa adları ve başlıklar burada tek yerde durur. Anlam
sütunları (AÇIKLAMA, DEĞERLER, KİŞİSEL VERİ) boş verilir - onları yalnız şemayı bilen kişi
yazar, program uydurmaz. `Örnek` sayfası biçimi gösterir ve hiç içe aktarılmaz.

R8-12: şablonun her dili `LABELS` sözlüğündedir - sayfa adları, başlıklar, E/H ya da Y/N listeleri,
anlatım satırları ve örnek satırları. İki dilin biçimi aynıdır: aynı sütun sırası, aynı listeler;
yalnız cümleleri çevrilidir.

ASSUMPTION: `Nasıl doldurulur` ve `_bilgin` sayfaları başlık satırı taşımayan sayfalardır
(cümleler tek sütunda, damga iki hücrede); okuyucu R6-14 yalnız Tablolar/Kolonlar'ı şema sayfası
sayar, bu sayfaları `read_workbook`'a sokmaz.
"""

from __future__ import annotations

import io
from collections.abc import Sequence

import openpyxl
from openpyxl.styles import Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from bilgin import config
from bilgin.policy import pii

# Örnek tablo adı: görsel testler dolu örneğin hangi tabloyu ürettiğini buradan okur.
EXAMPLE_TABLE = "Satis.Fatura"
_EXAMPLE_TABLE_EN = "Sales.Invoice"

# Şablonun dilleri (R8-12). Sayfa sırası kullanıcının okuma sırasıdır: önce nasıl doldurulur,
# sonra doldurulacak sayfalar. `yes`/`no` E/H ya da Y/N listesinin iki hücresidir.
LABELS = {
    "tr": {
        "sheets": ("Nasıl doldurulur", "Veri kümesi", "Tablolar", "Kolonlar", "İş kuralları", "Örnek"),
        "dataset_headers": ("AD", "GÖRÜNEN AD", "BAĞLANTI", "VARSAYILAN ŞEMA", "VERİ TARİHİ"),
        "table_headers": ("TABLO", "MODÜL", "AÇIKLAMA", "ANAHTAR KELİMELER"),
        "column_headers": (
            "TABLO",
            "KOLON",
            "TİP",
            "AÇIKLAMA",
            "DEĞERLER",
            "KİŞİSEL VERİ",
            "KAPALI",
            "REFERANS",
            "NULL",
        ),
        "rule_headers": (
            "KİMLİK",
            "TERİM",
            "EŞ ANLAMLILAR",
            "TANIM",
            "SQL İPUCU",
            "TABLOLAR",
            "EŞ ANLAMLILAR (EN)",
        ),
        "yes": "E",
        "no": "H",
        "how_to": (
            "BİLGİN - YENİ VERİTABANI ŞABLONU: bu dosyayı doldurup Bilgin'e yükleyin; veritabanınızı "
            "tanıması için başka bir şey gerekmez.",
            "'Veri kümesi' sayfası tek satırdır: AD klasörün adı (küçük harf, rakam, alt çizgi; 3-31 "
            "karakter), GÖRÜNEN AD arayüzde görünen ad, BAĞLANTI mssql ya da sqlite, VARSAYILAN ŞEMA "
            "(örn. dbo), VERİ TARİHİ ISO tarih - 'bu yıl' gibi ifadeler o tarihe göre hesaplanır.",
            "'Tablolar' sayfası veritabanındaki her tablo için bir satırdır: TABLO, MODÜL, AÇIKLAMA, "
            "ANAHTAR KELİMELER.",
            "'Kolonlar' sayfası her kolon için bir satırdır: TABLO, KOLON, TİP, AÇIKLAMA, DEĞERLER, "
            "KİŞİSEL VERİ, KAPALI, REFERANS, NULL.",
            "TABLO, KOLON ve TİP zorunludur; bir satırda üçünden biri boşsa o kolon şemaya alınmaz.",
            "AÇIKLAMA en önemli sütundur: model tabloyu ve kolonu yalnız oraya yazdığınız metinden bilir; "
            "boş bırakılan açıklama, sorunuzda o alanın hiç bulunamaması demektir.",
            "ANAHTAR KELİMELER tabloyu aratan sözcüklerdir; virgül ya da noktalı virgülle ayırın: "
            "sipariş, satış fişi.",
            "TİP olarak veritabanındaki adını yazın: int, nvarchar(50), decimal(18,2), datetime. Uzunluk "
            "verilmemiş metin nvarchar(255) olur.",
            "DEĞERLER kodlu kolonlarda kodların anlamıdır: A=Alıcı; S=Satıcı gibi yazın; 'alıcı cariler' "
            "sorusunun doğru filtreye dönmesi bu sayede olur.",
            f"KİŞİSEL VERİ sütununu listeden seçin ({', '.join(pii.CLASSES)}): işaretli kolonun değeri "
            "ekranda maskelenir ve sorguda filtre olarak kullanılamaz.",
            "KAPALI = E olan kolon hiç okunmaz: şemada durur ama hiçbir sorguya girmez (parola, iç not).",
            "NULL = H kolonun boş bırakılamayacağını söyler; hücreyi boş bırakırsanız kolon boş "
            "bırılabilir sayılır.",
            "REFERANS başka bir tablonun kolonuna gider: Tablo.Kolon ya da Şema.Tablo.Kolon (örn. "
            "Satis.Cari.CariKod); iki tablonun doğru birleştirilmesi bu referanstan gelir.",
            "Tablo adlarını veritabanında gördüğünüz gibi yazın; şema ön eki olabilir (Sales.Orders) ve "
            "büyük/küçük harf fark etmez.",
            "'İş kuralları' sayfası isteğe bağlıdır: iş terimlerinin tanımı ve SQL ipucu oraya yazılır. "
            "'Örnek' sayfası tek bir tablonun eksiksiz doldurulmuş hâlidir; o sayfa hiç içe aktarılmaz.",
        ),
        "example_title": "ÖRNEK - tek bir tablonun eksiksiz doldurulmuş hâli. Bu sayfa içe aktarılmaz.",
        "example_dataset": ("satis_fatura", "Satış Faturaları", "sqlite", "dbo", "2026-10-01"),
        "example_table": (
            EXAMPLE_TABLE,
            "Satış",
            "Satış faturasının üst kaydı; her satır bir faturadır.",
            "fatura, satış belgesi",
        ),
        "example_columns": (
            (EXAMPLE_TABLE, "FaturaID", "INT", "Faturanın numarası", "", "", "", "", "H"),
            (EXAMPLE_TABLE, "FaturaTarihi", "DATE", "Faturanın kesildiği tarih", "", "", "", "", "H"),
            (
                EXAMPLE_TABLE,
                "CariKod",
                "NVARCHAR(20)",
                "Faturanın kesildiği carinin kodu",
                "",
                "",
                "",
                "Satis.Cari.CariKod",
                "H",
            ),
            (
                EXAMPLE_TABLE,
                "FaturaTipi",
                "CHAR(1)",
                "Faturanın tipi",
                "S=Satış; I=İade",
                "",
                "",
                "",
                "H",
            ),
            (EXAMPLE_TABLE, "Tutar", "DECIMAL(18,2)", "Fatura tutarı, KDV hariç", "", "", "", "", "H"),
            (
                EXAMPLE_TABLE,
                "YetkiliAdi",
                "NVARCHAR(100)",
                "Faturayı kesen yetkili",
                "",
                "person_name",
                "",
                "",
                "E",
            ),
            (EXAMPLE_TABLE, "IcNot", "NVARCHAR(250)", "Faturaya düşülen iç not", "", "", "E", "", "E"),
        ),
        "example_rule": (
            "fatura_tutari",
            "Fatura tutarı",
            "ciro, satış tutarı",
            "Bir faturanın KDV hariç toplamı; iade faturaları eksi olarak sayılır.",
            "SUM(Fatura.Tutar)",
            "Satis.Fatura",
            "invoice amount, revenue",
        ),
    },
    "en": {
        "sheets": ("How to fill in", "Dataset", "Tables", "Columns", "Business rules", "Example"),
        "dataset_headers": ("NAME", "DISPLAY NAME", "CONNECTION", "DEFAULT SCHEMA", "DATA DATE"),
        "table_headers": ("TABLE", "MODULE", "DESCRIPTION", "KEYWORDS"),
        "column_headers": (
            "TABLE",
            "COLUMN",
            "TYPE",
            "DESCRIPTION",
            "VALUES",
            "PERSONAL DATA",
            "CLOSED",
            "REFERENCE",
            "NULL",
        ),
        "rule_headers": ("ID", "TERM", "SYNONYMS", "DEFINITION", "SQL HINT", "TABLES", "SYNONYMS (EN)"),
        "yes": "Y",
        "no": "N",
        "how_to": (
            "BILGIN - NEW DATABASE TEMPLATE: fill this file in and upload it to Bilgin; nothing else is "
            "needed for it to learn your database.",
            "'Dataset' is a single row: NAME is the folder name (lower-case letters, digits, underscore; "
            "3-31 characters), DISPLAY NAME is what the interface shows, CONNECTION is mssql or sqlite, "
            "DEFAULT SCHEMA (e.g. dbo), DATA DATE an ISO date - 'this year' is computed against that date.",
            "'Tables' is one row per table in the database: TABLE, MODULE, DESCRIPTION, KEYWORDS.",
            "'Columns' is one row per column: TABLE, COLUMN, TYPE, DESCRIPTION, VALUES, PERSONAL DATA, "
            "CLOSED, REFERENCE, NULL.",
            "TABLE, COLUMN and TYPE are required; if any of the three is empty that column does not enter "
            "the schema.",
            "DESCRIPTION is the most important column: the model knows a table and a column only from the "
            "text you write there; a description left empty means a question can never find that field.",
            "KEYWORDS are the words that make a table findable in a search; separate them with a comma or "
            "a semicolon: order, sales slip.",
            "TYPE is the name as your database spells it: int, nvarchar(50), decimal(18,2), datetime. "
            "Text without a length becomes nvarchar(255).",
            "VALUES is what the codes of a coded column mean: write it as A=Customer; S=Supplier; that is "
            "how 'customers' turns into the right filter.",
            f"Pick PERSONAL DATA from the list ({', '.join(pii.CLASSES)}): the value of a marked column is "
            "masked on screen and cannot be used as a filter in a query.",
            "A column with CLOSED = Y is never read: it stays in the schema but enters no query "
            "(password, internal note).",
            "NULL = N says the column cannot be left empty; leave the cell blank and the column counts as "
            "nullable.",
            "REFERENCE points at a column of another table: Table.Column or Schema.Table.Column (e.g. "
            "Sales.Customer.CustomerCode); the correct join between two tables comes from this reference.",
            "Write table names exactly as you see them in the database; they may carry a schema prefix "
            "(Sales.Orders) and upper/lower case does not matter.",
            "'Business rules' is optional: the definitions of business terms and their SQL hints go there. "
            "'Example' is one table filled in completely; that sheet is never imported.",
        ),
        "example_title": "EXAMPLE - one table filled in completely. This sheet is never imported.",
        "example_dataset": ("sales_invoice", "Sales Invoices", "sqlite", "dbo", "2026-10-01"),
        "example_table": (
            _EXAMPLE_TABLE_EN,
            "Sales",
            "Header record of a sales invoice; each row is one invoice.",
            "invoice, sales document",
        ),
        "example_columns": (
            (_EXAMPLE_TABLE_EN, "InvoiceID", "INT", "Invoice number", "", "", "", "", "N"),
            (
                _EXAMPLE_TABLE_EN,
                "InvoiceDate",
                "DATE",
                "Date the invoice was issued",
                "",
                "",
                "",
                "",
                "N",
            ),
            (
                _EXAMPLE_TABLE_EN,
                "CustomerCode",
                "NVARCHAR(20)",
                "Code of the customer the invoice was issued to",
                "",
                "",
                "",
                "Sales.Customer.CustomerCode",
                "N",
            ),
            (
                _EXAMPLE_TABLE_EN,
                "InvoiceType",
                "CHAR(1)",
                "Type of the invoice",
                "S=Sale; R=Return",
                "",
                "",
                "",
                "N",
            ),
            (
                _EXAMPLE_TABLE_EN,
                "Amount",
                "DECIMAL(18,2)",
                "Invoice amount, VAT excluded",
                "",
                "",
                "",
                "",
                "N",
            ),
            (
                _EXAMPLE_TABLE_EN,
                "ManagerName",
                "NVARCHAR(100)",
                "The manager who issued the invoice",
                "",
                "person_name",
                "",
                "",
                "Y",
            ),
            (
                _EXAMPLE_TABLE_EN,
                "InternalNote",
                "NVARCHAR(250)",
                "Internal note added to the invoice",
                "",
                "",
                "Y",
                "",
                "Y",
            ),
        ),
        "example_rule": (
            "invoice_amount",
            "Invoice amount",
            "revenue, sales amount",
            "The VAT-excluded total of an invoice; return invoices count as negative.",
            "SUM(Invoice.Amount)",
            "Sales.Invoice",
            "",
        ),
    },
}

# Türkçe şablonun sabitleri: içe aktaran taraf (R6-14) ve testler bu adları okur.
SHEETS = LABELS["tr"]["sheets"]
DATASET_HEADERS = LABELS["tr"]["dataset_headers"]
TABLE_HEADERS = LABELS["tr"]["table_headers"]
COLUMN_HEADERS = LABELS["tr"]["column_headers"]
RULE_HEADERS = LABELS["tr"]["rule_headers"]

INFO_SHEET = "_bilgin"
TEMPLATE_MARK = "bilgin-sablon"

_DATASET_WIDTHS = (20, 30, 12, 18, 14)
_TABLE_WIDTHS = (28, 14, 60, 34)
_COLUMN_WIDTHS = (28, 24, 18, 60, 26, 16, 10, 30, 8)
_RULE_WIDTHS = (22, 26, 30, 70, 40, 26, 30)

# Yazıya hazır satır sayısı: şablon sonuna kadar dolu görünmesin ama kullanıcı satır aramasın.
_BLANK_ROWS = 200

# Arayüzün vurgu rengi (styles.css --accent): başlık satırı koyu mavi, yazısı beyaz ve kalın.
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor="1F5FAD")
_CELL_BORDER = Border(bottom=Side(style="thin", color="D9D9D9"))

_CONNECTIONS = '"mssql,sqlite"'
_PII_CLASSES = '"' + ",".join(pii.CLASSES) + '"'


def build_template(skeleton: dict | None = None, lang: str = "tr") -> bytes:
    """Doldurulacak boş şablon; `skeleton` Tablolar/Kolonlar'ı ad, tip, NULL ve REFERANS ile doldurur."""
    tables, columns = _skeleton_rows(skeleton, LABELS[lang])
    return _workbook(lang, (), tables, columns, ())


def filled_example_workbook(
    name: str, connection: str = "sqlite", with_rule: bool = True, lang: str = "tr"
) -> bytes:
    """Örnek tablonun ve kuralın gerçek sayfalara kopyalandığı şablon: testlerin, smoke'un ve
    arayüzdeki "Örnek dolu şablonla dene"nin indirdiği dosya.

    ASSUMPTION: Örneğin REFERANS'ı kopyalanmayan Satis.Cari'ya gittiği için burada düşer;
    kopyalanan tek tablo doğrulamadan geçebilsin (R6-15 referansı şablonda olmayan kolona vermez).
    """
    labels = LABELS[lang]
    dataset = [(name, name, connection, "", labels["example_dataset"][4])]
    columns = [row[:7] + ("", row[8]) for row in labels["example_columns"]]
    rules = [labels["example_rule"]] if with_rule else []
    return _workbook(lang, dataset, [labels["example_table"]], columns, rules)


def _skeleton_rows(skeleton: dict | None, labels: dict) -> tuple[list[tuple], list[tuple]]:
    """İskelet -> Tablolar/Kolonlar satırları: yapı dolu, anlamlar boş (dolduracak olan kişi bilir)."""
    tables: list[tuple] = []
    columns: list[tuple] = []
    for table in (skeleton or {}).get("tables") or []:
        name = str(table.get("name", "")).strip()
        if not name:
            continue
        tables.append((name, "", "", ""))
        for column in table.get("columns") or []:
            column_name = str(column.get("name", "")).strip()
            if not column_name:
                continue
            columns.append(
                (
                    name,
                    column_name,
                    str(column.get("type", "")).strip(),
                    "",
                    "",
                    "",
                    "",
                    str(column.get("fk") or ""),
                    labels["yes"] if column.get("nullable", True) else labels["no"],
                )
            )
    return tables, columns


def _workbook(
    lang: str, dataset: Sequence, tables: Sequence, columns: Sequence, rules: Sequence
) -> bytes:
    labels = LABELS[lang]
    sheets = labels["sheets"]
    yes_no = f'"{labels["yes"]},{labels["no"]}"'
    dataset_headers = labels["dataset_headers"]
    column_headers = labels["column_headers"]
    book = openpyxl.Workbook()
    book.remove(book.active)
    _how_to_sheet(book.create_sheet(sheets[0]), labels)
    _grid(
        book.create_sheet(sheets[1]),
        dataset_headers,
        dataset,
        _DATASET_WIDTHS,
        ((dataset_headers[2], _CONNECTIONS),),
    )
    _grid(book.create_sheet(sheets[2]), labels["table_headers"], tables, _TABLE_WIDTHS)
    _grid(
        book.create_sheet(sheets[3]),
        column_headers,
        columns,
        _COLUMN_WIDTHS,
        (
            (column_headers[0], f"{sheets[2]}!$A$2:$A${max(len(tables), _BLANK_ROWS) + 1}"),
            (column_headers[5], _PII_CLASSES),
            (column_headers[6], yes_no),
            (column_headers[8], yes_no),
        ),
    )
    _grid(book.create_sheet(sheets[4]), labels["rule_headers"], rules, _RULE_WIDTHS)
    _example_sheet(book.create_sheet(sheets[5]), labels)
    _info_sheet(book.create_sheet(INFO_SHEET), lang)
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def _how_to_sheet(sheet: Worksheet, labels: dict) -> None:
    """Bir sütunluk anlatım: Excel'de boş komşu hücrelere taştığı için satır yüksekliğiyle oynanmaz."""
    sheet.column_dimensions["A"].width = 120
    for number, line in enumerate(labels["how_to"], start=1):
        cell = sheet.cell(row=number, column=1, value=line)
        if number == 1:
            cell.font = Font(bold=True)


def _grid(
    sheet: Worksheet,
    headers: Sequence[str],
    rows: Sequence[Sequence],
    widths: Sequence[int],
    validations: Sequence[tuple[str, str]] = (),
) -> None:
    """Başlık satırı + satırlar + yazıya hazır boş satırlar; başlık donuk, sütunlar listeli."""
    for index, (header, width) in enumerate(zip(headers, widths), start=1):
        letter = get_column_letter(index)
        cell = sheet.cell(row=1, column=index, value=header)
        cell.font, cell.fill = _HEADER_FONT, _HEADER_FILL
        sheet.column_dimensions[letter].width = width
    for offset, values in enumerate(rows, start=2):
        for index, value in enumerate(values, start=1):
            if value not in (None, ""):
                sheet.cell(row=offset, column=index, value=value)
    last = max(len(rows), _BLANK_ROWS) + 1
    for row in sheet.iter_rows(min_row=2, max_row=last, max_col=len(headers)):
        for cell in row:
            cell.border = _CELL_BORDER
    for field, formula in validations:
        letter = get_column_letter(list(headers).index(field) + 1)
        rule = DataValidation(type="list", formula1=formula, allow_blank=True)
        sheet.add_data_validation(rule)
        rule.add(f"{letter}2:{letter}{last}")
    sheet.freeze_panes = "A2"


def _example_sheet(sheet: Worksheet, labels: dict) -> None:
    """Örnek: dört blok tek sayfada, her biri kendi başlığıyla; içe aktarılmadığı için süstür."""
    column_headers = labels["column_headers"]
    for index, width in enumerate(_COLUMN_WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(column_headers))
    title = sheet.cell(row=1, column=1, value=labels["example_title"])
    title.font = Font(bold=True)
    row = 3
    for headers, block in (
        (labels["dataset_headers"], [labels["example_dataset"]]),
        (labels["table_headers"], [labels["example_table"]]),
        (column_headers, list(labels["example_columns"])),
        (labels["rule_headers"], [labels["example_rule"]]),
    ):
        row = _block(sheet, row, headers, block)


def _block(sheet: Worksheet, start: int, headers: Sequence[str], rows: Sequence[Sequence]) -> int:
    for index, header in enumerate(headers, start=1):
        cell = sheet.cell(row=start, column=index, value=header)
        cell.font, cell.fill = _HEADER_FONT, _HEADER_FILL
    for offset, values in enumerate(rows, start=start + 1):
        for index, value in enumerate(values, start=1):
            if value not in (None, ""):
                sheet.cell(row=offset, column=index, value=value)
    return start + len(rows) + 2


def _info_sheet(sheet: Worksheet, lang: str) -> None:
    """Şablonun damgası: okuyucu dosyanın Bilgin şablonu olduğunu A1'den (R6-14), hangi dilde
    yazıldığını ikinci satırdan anlar (R8-12)."""
    sheet["A1"] = TEMPLATE_MARK
    sheet["B1"] = config.TEMPLATE_VERSION
    sheet["A2"] = "lang"
    sheet["B2"] = lang
    sheet.sheet_state = "hidden"
