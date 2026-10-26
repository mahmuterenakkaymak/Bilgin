"""Bilgin'in Excel şablonu: boş hâli, iskeletle doldurulmuş hâli ve dolu örneği (PLAN R6-12).

Şablon, yeni bir veritabanını Bilgin'e tanıtırken doldurulan tek biçimdir; içe aktarma tarafı
(R6-14) aynı sabitleri okuduğu için sayfa adları ve başlıklar burada tek yerde durur. Anlam
sütunları (AÇIKLAMA, DEĞERLER, KİŞİSEL VERİ) boş verilir - onları yalnız şemayı bilen kişi
yazar, program uydurmaz. `Örnek` sayfası biçimi gösterir ve hiç içe aktarılmaz.

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

from nl2sql import config
from nl2sql.policy import pii

# Sayfa sırası kullanıcının okuma sırasıdır: önce nasıl doldurulur, sonra doldurulacak sayfalar.
SHEETS = ("Nasıl doldurulur", "Veri kümesi", "Tablolar", "Kolonlar", "İş kuralları", "Örnek")
INFO_SHEET = "_bilgin"
TEMPLATE_MARK = "bilgin-sablon"

DATASET_HEADERS = ("AD", "GÖRÜNEN AD", "BAĞLANTI", "VARSAYILAN ŞEMA", "VERİ TARİHİ")
TABLE_HEADERS = ("TABLO", "MODÜL", "AÇIKLAMA", "ANAHTAR KELİMELER")
COLUMN_HEADERS = (
    "TABLO",
    "KOLON",
    "TİP",
    "AÇIKLAMA",
    "DEĞERLER",
    "KİŞİSEL VERİ",
    "KAPALI",
    "REFERANS",
    "NULL",
)
RULE_HEADERS = ("KİMLİK", "TERİM", "EŞ ANLAMLILAR", "TANIM", "SQL İPUCU", "TABLOLAR")

_DATASET_WIDTHS = (20, 30, 12, 18, 14)
_TABLE_WIDTHS = (28, 14, 60, 34)
_COLUMN_WIDTHS = (28, 24, 18, 60, 26, 16, 10, 30, 8)
_RULE_WIDTHS = (22, 26, 30, 70, 40, 26)

# Yazıya hazır satır sayısı: şablon sonuna kadar dolu görünmesin ama kullanıcı satır aramasın.
_BLANK_ROWS = 200

# Arayüzün vurgu rengi (styles.css --accent): başlık satırı koyu mavi, yazısı beyaz ve kalın.
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_HEADER_FILL = PatternFill("solid", fgColor="1F5FAD")
_CELL_BORDER = Border(bottom=Side(style="thin", color="D9D9D9"))

_EH = '"E,H"'
_CONNECTIONS = '"mssql,sqlite"'
_PII_CLASSES = '"' + ",".join(pii.CLASSES) + '"'

_HOW_TO = (
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
)

# Örnek: genel bir satış faturası üst kaydı - hiçbir ürün ya da şirket adı taşımaz.
EXAMPLE_TABLE = "Satis.Fatura"
_EXAMPLE_DATASET = ("satis_fatura", "Satış Faturaları", "sqlite", "dbo", "2026-10-01")
_EXAMPLE_TABLE = (
    EXAMPLE_TABLE,
    "Satış",
    "Satış faturasının üst kaydı; her satır bir faturadır.",
    "fatura, satış belgesi",
)
_EXAMPLE_COLUMNS = (
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
)
_EXAMPLE_RULE = (
    "fatura_tutari",
    "Fatura tutarı",
    "ciro, satış tutarı",
    "Bir faturanın KDV hariç toplamı; iade faturaları eksi olarak sayılır.",
    "SUM(Fatura.Tutar)",
    "Satis.Fatura",
)


def build_template(skeleton: dict | None = None) -> bytes:
    """Doldurulacak boş şablon; `skeleton` Tablolar/Kolonlar'ı ad, tip, NULL ve REFERANS ile doldurur."""
    tables, columns = _skeleton_rows(skeleton)
    return _workbook((), tables, columns, ())


def filled_example_workbook(
    name: str, connection: str = "sqlite", with_rule: bool = True
) -> bytes:
    """Örnek tablonun ve kuralın gerçek sayfalara kopyalandığı şablon: testlerin, smoke'un ve
    arayüzdeki "Örnek dolu şablonla dene"nin indirdiği dosya.

    ASSUMPTION: Örneğin REFERANS'ı kopyalanmayan Satis.Cari'ya gittiği için burada düşer;
    kopyalanan tek tablo doğrulamadan geçebilsin (R6-15 referansı şablonda olmayan kolona vermez).
    """
    dataset = [(name, name, connection, "", _EXAMPLE_DATASET[4])]
    columns = [row[:7] + ("", row[8]) for row in _EXAMPLE_COLUMNS]
    rules = [_EXAMPLE_RULE] if with_rule else []
    return _workbook(dataset, [_EXAMPLE_TABLE], columns, rules)


def _skeleton_rows(skeleton: dict | None) -> tuple[list[tuple], list[tuple]]:
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
                    "E" if column.get("nullable", True) else "H",
                )
            )
    return tables, columns


def _workbook(dataset: Sequence, tables: Sequence, columns: Sequence, rules: Sequence) -> bytes:
    book = openpyxl.Workbook()
    book.remove(book.active)
    _how_to_sheet(book.create_sheet(SHEETS[0]))
    _grid(
        book.create_sheet(SHEETS[1]),
        DATASET_HEADERS,
        dataset,
        _DATASET_WIDTHS,
        ((DATASET_HEADERS[2], _CONNECTIONS),),
    )
    _grid(book.create_sheet(SHEETS[2]), TABLE_HEADERS, tables, _TABLE_WIDTHS)
    _grid(
        book.create_sheet(SHEETS[3]),
        COLUMN_HEADERS,
        columns,
        _COLUMN_WIDTHS,
        (
            (COLUMN_HEADERS[0], f"{SHEETS[2]}!$A$2:$A${max(len(tables), _BLANK_ROWS) + 1}"),
            (COLUMN_HEADERS[5], _PII_CLASSES),
            (COLUMN_HEADERS[6], _EH),
            (COLUMN_HEADERS[8], _EH),
        ),
    )
    _grid(book.create_sheet(SHEETS[4]), RULE_HEADERS, rules, _RULE_WIDTHS)
    _example_sheet(book.create_sheet(SHEETS[5]))
    _info_sheet(book.create_sheet(INFO_SHEET))
    stream = io.BytesIO()
    book.save(stream)
    return stream.getvalue()


def _how_to_sheet(sheet: Worksheet) -> None:
    """Bir sütunluk Türkçe anlatım: Excel'de boş komşu hücrelere taştığı için satır yüksekliğiyle oynanmaz."""
    sheet.column_dimensions["A"].width = 120
    for number, line in enumerate(_HOW_TO, start=1):
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


def _example_sheet(sheet: Worksheet) -> None:
    """Örnek: dört blok tek sayfada, her biri kendi başlığıyla; içe aktarılmadığı için süstür."""
    for index, width in enumerate(_COLUMN_WIDTHS, start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(COLUMN_HEADERS))
    title = sheet.cell(
        row=1,
        column=1,
        value="ÖRNEK - tek bir tablonun eksiksiz doldurulmuş hâli. Bu sayfa içe aktarılmaz.",
    )
    title.font = Font(bold=True)
    row = 3
    for headers, block in (
        (DATASET_HEADERS, [_EXAMPLE_DATASET]),
        (TABLE_HEADERS, [_EXAMPLE_TABLE]),
        (COLUMN_HEADERS, list(_EXAMPLE_COLUMNS)),
        (RULE_HEADERS, [_EXAMPLE_RULE]),
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


def _info_sheet(sheet: Worksheet) -> None:
    """Şablonun damgası: okuyucu dosyanın Bilgin şablonunu olduğunu buradan anlar (R6-14)."""
    sheet["A1"] = TEMPLATE_MARK
    sheet["B1"] = config.TEMPLATE_VERSION
    sheet.sheet_state = "hidden"
