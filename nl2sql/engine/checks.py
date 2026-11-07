# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Sonuç koştuktan sonra kullanıcıya söylenecekler (PLAN R5-5).

Denetimler SQL'i değiştirmez ve cevabı düşürmez: bir şeyden emin değilse hiçbir şey eklemez.
İlk dört denetim yalnız `result`a bakar; `fan_out` ayrıca `sql`i çözer ve iki sayımı
`executor`dan geçirir, o yüzden ikisi de ondan istenir (R5-5'in ikinci yarısı).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlglot import exp, parse_one

from nl2sql import config
from nl2sql.engine.result import Budget, Result

EMPTY = "Sonuç boş: bu koşullara uyan kayıt yok."
ALL_NULL = "'{col}' kolonunun tüm değerleri boş (NULL)."
TOP_LIMITED = "Sonuç {n} satırlık üst sınırda kesildi; tamamı daha fazla olabilir."
MASKED = "Maskelendi: {cols} — kişisel veri gösterilmez."
FAN_OUT = (
    "Join sonrası {joined} satır, sürücü tablo {table} {driving} satır ({ratio}x): "
    "toplamlar çoğalmış olabilir."
)

# Sayımların denetim kaydındaki adı: koşturanın sorgusu değil, denetimin kendi sorguları.
CHECK_SOURCE = "checks"


@dataclass(frozen=True)
class Warning:
    """Cevabın yanında çıkan tek satır; `column` yalnız kolon başına olan denetimlerde dolu."""

    code: str
    message: str
    column: str | None = None

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "column": self.column}


def post_checks(sql: str, result: Result, executor=None) -> list[Warning]:
    """Hata olmayan bir sonucun uyarıları: boş, tümü NULL, üst sınırda kesik, maskeli, katlanan join.

    `executor` verilmezse fan_out ölçülemez; öteki dört denetim yine yerindedir.
    """
    if result.error is not None:
        return []
    warnings = [] if result.row_count else [Warning("empty", EMPTY)]
    warnings += _all_null(result)
    if result.row_count == config.TOP_N:
        warnings.append(Warning("top_limited", TOP_LIMITED.format(n=config.TOP_N)))
    if result.masked_columns:
        # ASSUMPTION: PLAN {cols} için ayraç vermiyor; payload'da tek satır okunduğu için virgül.
        warnings.append(Warning("masked", MASKED.format(cols=", ".join(result.masked_columns))))
    warning = _fan_out(sql, executor)
    if warning:
        warnings.append(warning)
    return warnings


def _all_null(result: Result) -> list[Warning]:
    """Dönen satırların her hücresi NULL olan her kolon için bir uyarı; tek dolu hücre yeter."""
    if not result.rows:
        return []
    return [
        Warning("all_null", ALL_NULL.format(col=name), name)
        for index, name in enumerate(result.columns)
        if all(row[index] is None for row in result.rows)
    ]


# ----------------------------------------------------------------- R5-5: katlanan join


def _fan_out(sql: str, executor) -> Warning | None:
    """Joinli sayımın sürücü sayıma oranı eşiği aşıyorsa uyarı; ölçülemiyorsa hiçbir şey.

    Ölçüm iki `SELECT COUNT(*)`: birinde from+join+where'in satır sayısı, ötekinde sürücü
    tablonun kendi satır sayısı. Sayımlar executor'dan geçer, yani politikanın ve denetim
    kaydının dışına çıkmazlar; eşiğin ne olduğuna değil, oranına bakılır.
    """
    if executor is None:
        return None
    try:
        shape = _fan_out_shape(sql)
        if shape is None:
            return None
        joined = _count(executor, shape[0])
        driving = _count(executor, shape[1])
    except Exception:
        # Bir denetimin kendisi hiçbir zaman cevabı düşürmez (R5-5).
        return None
    if joined is None or not driving:
        return None
    ratio = joined / driving
    if ratio <= config.FANOUT_FACTOR:
        return None
    return Warning(
        "fan_out",
        FAN_OUT.format(
            joined=joined,
            table=shape[2],
            driving=driving,
            ratio=f"{ratio:.1f}".replace(".", ","),
        ),
    )


def _fan_out_shape(sql: str) -> tuple[str, str, str] | None:
    """(joinli sayım, sürücü sayım, sürücü tablo adı); şekil ölçülemeyecekse None.

    Yalnız dıştaki düz SELECT ölçülür: UNION ve CTE şekillerinde "sürücü tablo" tek bir
    şeye karşılık gelmez, sayım da yanlış olurdu.
    """
    tree = parse_one(sql, read="tsql")
    if not isinstance(tree, exp.Select) or tree.args.get("with_"):
        return None
    joins = tree.args.get("joins") or []
    from_ = tree.args.get("from_")
    if from_ is None or not joins:
        return None
    if not any(expression.find(exp.AggFunc) for expression in tree.expressions):
        return None
    driving = from_.this
    if not isinstance(driving, exp.Table):
        return None  # türetilmiş tablo: sürücünün kaç satırı olduğu burada bilinmiyor
    where = tree.args.get("where")
    joined_sql = _count_sql(from_.copy(), [join.copy() for join in joins], where.copy() if where else None)
    alias = (driving.alias or driving.name).upper()
    own = [conjunct.copy() for conjunct in _conjuncts(where) if _only_qualifies(conjunct, alias)]
    driving_sql = _count_sql(exp.From(this=driving.copy()), [], _where(own))
    return joined_sql, driving_sql, driving.name.upper()


def _count_sql(from_: exp.Expression, joins: list, where: exp.Expression | None) -> str:
    """Verilen from+join+where parçalarının COUNT(*) karşılığı; sıradan bir T-SQL cümlesi."""
    select = exp.select(exp.Count(this=exp.Star()))
    select.set("from_", from_)
    if joins:
        select.set("joins", joins)
    if where is not None:
        select.set("where", where)
    return select.sql(dialect="tsql")


def _count(executor, sql: str) -> int | None:
    """Tek sayı; sorgu düşerse ya da sayı yoksa None, yani denetim susar."""
    result = executor.execute(sql, Budget(max_rows=1), CHECK_SOURCE)
    if result.error is not None or not result.rows:
        return None
    value = result.rows[0][0]
    return None if value is None else int(value)


def _conjuncts(where: exp.Expression | None) -> list:
    """WHERE'un AND ile ayrılmış tekil koşulları; parantezler açılır."""
    return [] if where is None else _split_and(where.this)


def _split_and(node: exp.Expression) -> list:
    if isinstance(node, exp.Paren):
        return _split_and(node.this)
    if isinstance(node, exp.And):
        return _split_and(node.left) + _split_and(node.right)
    return [node]


def _only_qualifies(conjunct: exp.Expression, alias: str) -> bool:
    """Koşul sürücü tablonun kolonlarından başkasına bakmıyor; niteliksiz kolon belirsiz sayılır."""
    columns = list(conjunct.find_all(exp.Column))
    return bool(columns) and all(column.table.upper() == alias for column in columns)


def _where(conjuncts: list) -> exp.Expression | None:
    """Kalan koşulların AND'ı; hiç kalmadıysa süzgeç yok."""
    if not conjuncts:
        return None
    node = conjuncts[0]
    for extra in conjuncts[1:]:
        node = exp.And(this=node, expression=extra)
    return exp.Where(this=node)
