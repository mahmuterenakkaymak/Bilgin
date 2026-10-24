"""Sonuç koştuktan sonra kullanıcıya söylenecekler (PLAN R5-5).

Denetimler SQL'i değiştirmez ve cevabı düşürmez: bir şeyden emin değilse hiçbir şey eklemez.
`sql` ve `executor` fan_out'un kapısıdır (R5-5'in ikinci yarısı); buradaki dört denetim
ikisine de bakmaz, ikisi de sonraki görevde burada kullanılır.
"""

from __future__ import annotations

from dataclasses import dataclass

from nl2sql import config
from nl2sql.engine.result import Result

EMPTY = "Sonuç boş: bu koşullara uyan kayıt yok."
ALL_NULL = "'{col}' kolonunun tüm değerleri boş (NULL)."
TOP_LIMITED = "Sonuç {n} satırlık üst sınırda kesildi; tamamı daha fazla olabilir."
MASKED = "Maskelendi: {cols} — kişisel veri gösterilmez."


@dataclass(frozen=True)
class Warning:
    """Cevabın yanında çıkan tek satır; `column` yalnız kolon başına olan denetimlerde dolu."""

    code: str
    message: str
    column: str | None = None

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "column": self.column}


def post_checks(sql: str, result: Result, executor=None) -> list[Warning]:
    """Hata olmayan bir sonucun uyarıları: boş, tümü NULL, üst sınırda kesik, maskeli kolonlar."""
    if result.error is not None:
        return []
    warnings = [] if result.row_count else [Warning("empty", EMPTY)]
    warnings += _all_null(result)
    if result.row_count == config.TOP_N:
        warnings.append(Warning("top_limited", TOP_LIMITED.format(n=config.TOP_N)))
    if result.masked_columns:
        # ASSUMPTION: PLAN {cols} için ayraç vermiyor; payload'da tek satır okunduğu için virgül.
        warnings.append(Warning("masked", MASKED.format(cols=", ".join(result.masked_columns))))
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
