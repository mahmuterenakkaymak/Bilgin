"""LocalExecutor: the single public door to the databases.

The order is fixed here - policy, then transpile, then backend, then audit - so a caller
cannot reach a backend without the guardrail, and every attempt, approved or refused, leaves
one audit line. The backends are private modules for the same reason; nothing in this package
exposes a policy-free way to run SQL.
"""

from __future__ import annotations

from pathlib import Path

from sqlglot import exp, transpile
from sqlglot.dialects.sqlite import SQLite
from sqlglot.dialects.tsql import TSQL
from sqlglot.errors import SqlglotError, UnsupportedError

from nl2sql import config
from nl2sql.engine import _mssql, _sqlite, audit
from nl2sql.engine.result import Budget, ExecError, Result
from nl2sql.policy import policy
from nl2sql.schema_map import doc

TRANSPILE_MESSAGE = "SQL çalıştırılabilir bir sorguya çevrilemedi; tek bir T-SQL SELECT yazın."

# ----------------------------------------------------------------- tsql -> sqlite dates
#
# sqlglot her iki T-SQL tarih işlevini de CAST(x AS DATETIME2) üzerinden üretiyor; o katman
# SQLite'a CAST(x AS TIMESTAMP) olarak iniyor ve TIMESTAMP sayısal yakınlık taşıdığı için
# '2026-02-01' sayı 2026'ya dönüşüyor: JULIANDAY tarih göremiyor, DATEDIFF 31 yerine 0
# veriyor. CONVERT'ın tersi oluyor - SQLite CAST(x AS TEXT(7)) içindeki uzunluğu yok sayar,
# yani 'YYYY-MM' kesimi hiç yapılmaz. İkisi de çıplak ISO metin üzerine yeniden kuruluyor;
# takvim birimleri 30/365'e bölmek yerine SQL Server gibi birim sınırının geçişini sayar.

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
        if isinstance(node, exp.TimeStrToTime):
            node = node.this
        elif isinstance(node, (exp.Cast, exp.TryCast)) and node.to.this in CAST_DATE_TYPES:
            node = node.this
        else:
            return node


def _year(x: str) -> str:
    return f"CAST(STRFTIME('%Y', {x}) AS INTEGER)"


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
    """SQLite üretimi; tarih işlevleri SQL Server'ın verdiği sayıyı ve metni verir."""

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


class LocalExecutor:
    """Runs read-only T-SQL against one backend under a Budget."""

    def __init__(
        self,
        backend: str | None = None,
        db_path: str | Path = config.DB_PATH,
        allowlist: set[str] | None = None,
        audit_path: str | Path = config.AUDIT_LOG,
    ) -> None:
        self._backend = backend or config.backend()
        if self._backend not in config.BACKENDS:
            raise ValueError(f"Geçersiz yedek: {self._backend}; {list(config.BACKENDS)} olmalı.")
        self._db_path = db_path
        # ASSUMPTION: allowlist verilmezse PLAN Decision 6 gereği schema.json tabloları alınır;
        # geç çözülür, böylece testler dosyaya dokunmadan kendi listesini verebilir.
        self._allowlist = allowlist if allowlist is not None else doc.allowlist(doc.load_schema())
        self._audit_path = audit_path

    def execute(self, sql: str, budget: Budget | None = None, source: str = "") -> Result:
        """The only public entry: policy -> transpile (sqlite backend) -> backend -> audit."""
        result = self._run(sql, budget or Budget())
        audit.record(sql, source, result, self._audit_path)
        return result

    def _run(self, sql: str, budget: Budget) -> Result:
        verdict = policy.check(sql, self._allowlist, config.TOP_N)
        if not verdict.ok:
            return _error("policy", verdict.reason)
        if self._backend != "sqlite":
            return _mssql.run(verdict.sql, budget)
        try:
            statements = transpile(verdict.sql, read="tsql", write=_SQLiteDates)
        except SqlglotError as exc:
            return _error("transpile", _explain(exc))
        if len(statements) != 1:
            return _error("transpile", TRANSPILE_MESSAGE)
        return _sqlite.run(statements[0], budget, self._db_path)


def _error(kind: str, message: str) -> Result:
    return Result(error=ExecError(kind, message))


def _explain(exc: SqlglotError) -> str:
    text = " ".join(str(exc).split())
    return f"{TRANSPILE_MESSAGE} ({text})" if text else TRANSPILE_MESSAGE
