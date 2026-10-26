"""Bir turun sonraki tura miras bıraktığı kadarı (PLAN R7-3, Contracts "TurnSummary").

Konuşmanın bağlamı sonuçların tamamı değil, modelin bir sonraki soruyu anlaması için gereken
kadarıdır: kolon adları, satır sayısı, maskelenmiş en fazla ``CONV_KEEP_ROWS`` satır ve olgular.
Satırlar yürütücünün maskesini olduğu gibi taşır - burada maske yeniden hesaplanmaz, ham bir pii
değeri bir daha hiçbir yere yazılmaz. Grafikten yalnız türü kalır; option'ın kendisi konuşmaya
girmez.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from nl2sql import config


def turn_summary(payload: dict) -> dict:
    """AskPayload'ı ``summary_json``a yazılacak öze indirir (Contracts "TurnSummary").

    ``context`` yalnız konuşma deposuyla koşan bir payloadda vardır, yoksa None kalır (Contracts
    "ContextNote"). Özet bir başka modülün sözlüğünden kurulduğu için anahtarlar ``get`` ile
    okunur: eksik bir alan ekranda ya da toplamda NaN/undefined olacağına boş kalır.
    """
    chart = payload.get("chart")
    return {
        "columns": payload.get("columns", []),
        "row_count": payload.get("row_count", 0),
        "rows": [[_cell(cell) for cell in row] for row in payload.get("rows", [])[: config.CONV_KEEP_ROWS]],
        "facts": payload.get("facts", []),
        "chart_kind": chart.get("type") if chart else None,
        "context": payload.get("context"),
        "clarification": payload.get("clarification"),
    }


def _cell(value):
    """JSONa yazılabilir hücre: Decimal ve tarih metne döner, başkası olduğu gibi kalır.

    Maskeli bir hücre çoktan metindir, o yüzden buradan ham haliyle değil yürütücünün maskesiyle
    geçer.
    """
    if isinstance(value, (Decimal, date)):
        return str(value)
    return value
