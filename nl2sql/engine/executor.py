"""LocalExecutor: the single public door to the databases.

The order is fixed here - policy, then transpile, then backend, then masking, then audit - so a
caller cannot reach a backend without the guardrail, never sees a raw PII value, and every
attempt, approved or refused, leaves one audit line. The backends are private modules for the
same reason; nothing in this package exposes a policy-free way to run SQL.
"""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from pathlib import Path

from sqlglot import exp, transpile
from sqlglot.dialects.sqlite import SQLite
from sqlglot.dialects.tsql import TSQL
from sqlglot.errors import SqlglotError, UnsupportedError

from nl2sql import config
from nl2sql.engine import _mssql, _sqlite, audit
from nl2sql.engine.result import Budget, ExecError, Result
from nl2sql.policy import pii, policy
from nl2sql.schema_map import doc

TRANSPILE_MESSAGE = "SQL çalıştırılabilir bir sorguya çevrilemedi; tek bir T-SQL SELECT yazın."

# İzlenemeyen bir kolonun hücresi: hiçbir parçası gösterilmiyor.
HIDDEN = "***"

# ----------------------------------------------------------------- tsql -> sqlite dates
#
# sqlglot her iki T-SQL tarih işlevini de CAST(x AS DATETIME2) üzerinden üretiyor; o katman
# SQLite'a CAST(x AS TIMESTAMP) olarak iniyor ve TIMESTAMP sayısal yakınlık taşıdığı için
# '2026-02-01' sayı 2026'ya dönüşüyor: JULIANDAY tarih göremiyor, DATEDIFF 31 yerine 0
# veriyor. CONVERT'ın tersi oluyor - SQLite CAST(x AS TEXT(7)) içindeki uzunluğu yok sayar,
# yani 'YYYY-MM' kesimi hiç yapılmaz. İkisi de çıplak ISO metin üzerine yeniden kuruluyor;
# takvim birimleri 30/365'e bölmek yerine SQL Server gibi birim sınırının geçişini sayar.

# MONTH/YEAR/DAY ve DATEPART ayrı bir yerde kırılır: sqlglot MONTH(TARIH)'i MONTH(DATE(TARIH))
# bırakıyor (SQLite'ta MONTH işlevi yok), DATEPART'i EXTRACT(month FROM ...) yapıyor - o SQLite'ta
# söz dizimi olarak bile geçmez, yani create_function ile düzeltilemez - LEFT de "no such function".
# Üçü de burada STRFTIME/SUBSTR'a bağlanır.
# ASSUMPTION: görev iki yol veriyordu (create_function / çeviri öncesi yeniden yazım); EXTRACT
# create_function ile düzeltilemediği için hepsi tek yerde, aynı üreticide ele alınıyor.
DATE_PART_FORMATS = {"YEAR": "%Y", "MONTH": "%m", "DAY": "%d"}

CAST_DATE_TYPES = frozenset(
    {
        exp.DataType.Type.DATE,
        exp.DataType.Type.DATETIME,
        exp.DataType.Type.DATETIME2,
        exp.DataType.Type.SMALLDATETIME,
    }
)
CONVERT_STYLE_120 = "120"  # ODBC canonical: 'YYYY-MM-DD HH:MM:SS'


def _date_arg(node):
    """İşlev argümanını tarih CAST katmanlarından soyar; JULIANDAY ve STRFTIME ISO metni okur."""
    while True:
        if isinstance(node, (exp.TimeStrToTime, exp.TsOrDsToDate)):
            node = node.this
        elif isinstance(node, (exp.Cast, exp.TryCast)) and node.to.this in CAST_DATE_TYPES:
            node = node.this
        else:
            return node


def _strftime_int(fmt: str, x: str) -> str:
    return f"CAST(STRFTIME('{fmt}', {x}) AS INTEGER)"


def _year(x: str) -> str:
    return _strftime_int("%Y", x)


def _date_part(unit: str, x: str) -> str | None:
    """MONTH/DATEPART karşılığı; tanımadığımız birimde None, yani gürültülü red."""
    fmt = DATE_PART_FORMATS.get(unit)
    return None if fmt is None else _strftime_int(fmt, x)


def _month_index(x: str) -> str:
    return f"({_year(x)} * 12 + CAST(STRFTIME('%m', {x}) AS INTEGER))"


def _date_diff(unit: str, start: str, end: str) -> str | None:
    """DATEDIFF(unit, start, end) karşılığı; desteklenmeyen birimde None, yani gürültülü red."""
    if unit == "DAY":
        return f"CAST(JULIANDAY({end}) - JULIANDAY({start}) AS INTEGER)"
    if unit == "MONTH":
        return f"({_month_index(end)} - {_month_index(start)})"
    if unit == "YEAR":
        return f"({_year(end)} - {_year(start)})"
    return None


def _text_length(to) -> int | None:
    """varchar(n) içindeki n; uzunluk yazılmamışsa kesinti uygulanmaz."""
    # ASSUMPTION: T-SQL uzunluksuz varchar'ı 1 karakter sayar, sqlglot 30; ikisi de burada
    # üretilmiyor, o biçim taskın kapsamında değil, kesintisiz bırakılıyor.
    param = to.expressions[0] if to.expressions else None
    if param is None or not param.this.is_int:
        return None
    return int(param.this.name)


class _SQLiteDates(SQLite):
    """SQLite üretimi; tarih işlevleri SQL Server'ın verdiği sayıyı ve metni verir, LEFT SUBSTR olur."""

    class Generator(SQLite.Generator):
        def datediff_sql(self, expression: exp.DateDiff) -> str:
            unit = expression.text("unit").upper() or "DAY"
            start = self.sql(_date_arg(expression.args["expression"]))
            end = self.sql(_date_arg(expression.this))
            sql = _date_diff(unit, start, end)
            if sql is None:
                raise UnsupportedError(f"DATEDIFF için {unit} birimi yok; DAY, MONTH ya da YEAR yazın.")
            return sql

        def convert_sql(self, expression: exp.Convert) -> str:
            to = expression.this
            style = expression.args.get("style")
            length = _text_length(to) if to and to.this in self.PARAMETERIZABLE_TEXT_TYPES else None
            if not length or not (
                isinstance(style, exp.Literal) and style.is_int and style.name == CONVERT_STYLE_120
            ):
                return super().convert_sql(expression)
            fmt = TSQL.CONVERT_FORMAT_MAPPING[CONVERT_STYLE_120]
            return f"SUBSTR(STRFTIME('{fmt}', {self.sql(expression, 'expression')}), 1, {length})"

        def day_sql(self, expression: exp.Day) -> str:
            return self._date_part_sql("DAY", expression.this)

        def month_sql(self, expression: exp.Month) -> str:
            return self._date_part_sql("MONTH", expression.this)

        def year_sql(self, expression: exp.Year) -> str:
            return self._date_part_sql("YEAR", expression.this)

        def extract_sql(self, expression: exp.Extract) -> str:
            return self._date_part_sql(expression.this.name.upper(), expression.args["expression"])

        def left_sql(self, expression: exp.Left) -> str:
            this = self.sql(expression, "this")
            count = self.sql(expression, "expression")
            return f"SUBSTR({this}, 1, {count})"

        def _date_part_sql(self, unit, arg) -> str:
            sql = _date_part(unit, self.sql(_date_arg(arg)))
            if sql is None:
                raise UnsupportedError(f"Tarih parçası {unit} yok; YEAR, MONTH ya da DAY yazın.")
            return sql


class LocalExecutor:
    """Runs read-only T-SQL against one backend under a Budget."""

    def __init__(
        self,
        backend: str | None = None,
        db_path: str | Path = config.DB_PATH,
        allowlist: set[str] | None = None,
        audit_path: str | Path = config.AUDIT_LOG,
        pii_schema: dict | None = None,
    ) -> None:
        self._backend = backend or config.backend()
        if self._backend not in config.BACKENDS:
            raise ValueError(f"Geçersiz yedek: {self._backend}; {list(config.BACKENDS)} olmalı.")
        self._db_path = db_path
        # ASSUMPTION: allowlist verilmezse PLAN Decision 6 gereği schema.json tabloları alınır;
        # geç çözülür, böylece testler dosyaya dokunmadan kendi listesini verebilir.
        self._allowlist = allowlist if allowlist is not None else doc.allowlist(doc.load_schema())
        self._audit_path = audit_path
        # ASSUMPTION: pii işareti hangi şemadan okunuyorsa maskeleme o şemayı izler; kendisine
        # şema verilmeyen executor hangi kolonun pii olduğunu bilmediği için hiçbir şey maskelemez.
        self._pii_schema = pii_schema
        self._pii_map = pii.column_map(pii_schema) if pii_schema is not None else {}

    def execute(self, sql: str, budget: Budget | None = None, source: str = "") -> Result:
        """The only public entry: policy -> transpile (sqlite backend) -> backend -> mask -> audit."""
        result = self._run(sql, budget or Budget())
        audit.record(sql, source, result, self._audit_path)
        return result

    def _run(self, sql: str, budget: Budget) -> Result:
        # Filtre kuralı aynı haritayı izler: maskelenen bir kolon sorguda filtre de olamaz (R3-6).
        verdict = policy.check(sql, self._allowlist, config.TOP_N, pii=self._pii_map)
        if not verdict.ok:
            return _error("policy", verdict.reason)
        if self._backend != "sqlite":
            return self._masked(_mssql.run(verdict.sql, budget), verdict)
        try:
            statements = transpile(verdict.sql, read="tsql", write=_SQLiteDates)
        except SqlglotError as exc:
            return _error("transpile", _explain(exc))
        if len(statements) != 1:
            return _error("transpile", TRANSPILE_MESSAGE)
        return self._masked(_sqlite.run(statements[0], budget, self._db_path), verdict)

    # ----------------------------------------------------------------- masking (R3-6)

    def _masked(self, result: Result, verdict) -> Result:
        """Backend'den dönen satırlar: hiçbir çağıran kaynağı pii olan bir ham değeri görmüyor."""
        if result.error is not None or not result.rows or not self._pii_map:
            return result
        masks = self._masks(verdict, result.columns)
        if not any(masks):
            return result
        rows = [
            tuple(mask(value) if mask else value for value, mask in zip(row, masks))
            for row in result.rows
        ]
        names = [name for name, mask in zip(result.columns, masks) if mask]
        return replace(result, rows=rows, masked_columns=names)

    def _masks(self, verdict, columns: list[str]) -> list:
        """Kolon başına bir maske işlevi ya da None.

        PII işaretli bir tabloya dokunmayan sorgunun maskelenecek bir şeyi yoktur; dokunan
        sorguda ise izi okunamayan kolonun tamamı gizlenir, çünkü kaynağı bilinmiyordur.
        """
        if not any(table in verdict.tables for table, _ in self._pii_map):
            return [None] * len(columns)
        traced = pii.trace(verdict.sql, self._pii_schema)
        if len(traced) != len(columns):
            # İz hiç süzülemedi ya da iki çıktı kolonu aynı adı taşıyor: hiçbir kolonun kaynağı
            # bilinmiyor, o yüzden hiçbiri ham gösterilmiyor (fail closed).
            return [_hidden] * len(columns)
        return [_mask(trace, self._pii_map) for trace in traced]


def _error(kind: str, message: str) -> Result:
    return Result(error=ExecError(kind, message))


def _mask(trace: pii.Trace, marks: dict):
    """Bir çıktı kolonunun maskesi ya da None; R3-6 beyaz listesi COUNT'a sayıyı gösterir."""
    if trace.aggregate == "count":
        return None
    if trace.sources is None:
        return _hidden
    classes = {marks[source] for source in trace.sources if source in marks}
    if not classes:
        return None
    # İki farklı sınıfın değeri aynı kolona akıyorsa tek maske ikisini de anlatmaz.
    return _class_mask(classes.pop()) if len(classes) == 1 else _hidden


def _class_mask(cls: str):
    """Bilinen sınıfın maskesi; şemanın tanımadığı bir işaret değerin tamamını gizler."""
    return partial(pii.mask, cls) if cls in pii.CLASSES else _hidden


def _hidden(value):
    """Kaynağı okunamayan bir kolonun hücresi; boş hücre boş kalır, geri kalanın tamamı gizli."""
    return None if value is None else HIDDEN


def _explain(exc: SqlglotError) -> str:
    text = " ".join(str(exc).split())
    return f"{TRANSPILE_MESSAGE} ({text})" if text else TRANSPILE_MESSAGE
