# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Did the predicted query answer the question, or did it not?

Two different queries can answer one question with different aliases, so column names and their
order carry no weight here; the data does. Rows are compared as a multiset (in order when the
golden line says so), numbers meet at two decimals, text without its padding, and a column the
model added on top is reported instead of punished.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal

from bilgin import config
from bilgin.engine.result import Result
from bilgin.i18n import t

DECIMALS = 2


@dataclass(frozen=True)
class CompareResult:
    """The verdict, why it came out that way, and how the two sets of columns lined up."""

    match: bool
    reason: str = ""
    column_map: dict[int, int] = field(default_factory=dict)  # golden column index -> predicted column index
    extra_columns: list[str] = field(default_factory=list)  # predicted columns no golden column needed


def compare(
    golden: Result, pred: Result, ordered: bool = False, lang: str = config.DEFAULT_LANG
) -> CompareResult:
    """Compare two result sets; every golden row must appear as a predicted row, in order when ``ordered``.

    ``lang`` (R8-12) is the language of the reasons a mismatch carries; the outcome itself is a bool.
    """
    golden_rows = _grid(golden)
    pred_rows = _grid(pred)
    if len(golden_rows) != len(pred_rows):
        return CompareResult(
            False,
            t(
                "eval.compare.row_count",
                lang,
                expected=len(golden_rows),
                got=len(pred_rows),
            ),
        )

    # ASSUMPTION: `ordered` decides row order only; columns are always paired by values, never by name.
    wanted = [Counter(_column(golden_rows, g)) for g in range(len(golden.columns))]
    have = [Counter(_column(pred_rows, p)) for p in range(len(pred.columns))]
    free = list(range(len(have)))
    column_map: dict[int, int] = {}
    for g, values in enumerate(wanted):
        for p in free:
            if have[p] == values:
                column_map[g] = p
                free.remove(p)
                break
    extras = [pred.columns[p] for p in free]

    if len(column_map) == len(wanted):
        pred_rows = [tuple(row[column_map[g]] for g in range(len(wanted))) for row in pred_rows]
    elif len(pred.columns) != len(golden.columns):
        missing = [golden.columns[g] for g in range(len(wanted)) if g not in column_map]
        return CompareResult(
            False,
            t("eval.compare.missing_columns", lang, columns=", ".join(missing)),
            column_map,
            extras,
        )

    same_rows = Counter(golden_rows) == Counter(pred_rows)
    if same_rows and (not ordered or golden_rows == pred_rows):
        return CompareResult(True, "", column_map, extras)
    if same_rows:
        return CompareResult(False, t("eval.compare.order_only", lang), column_map, extras)
    absent = sum((Counter(golden_rows) - Counter(pred_rows)).values())
    return CompareResult(
        False, t("eval.compare.rows_differ", lang, absent=absent), column_map, extras
    )


def _value(cell):
    """One cell reduced to what two databases agree on: an amount at two decimals, text trimmed."""
    if isinstance(cell, bool):
        return cell
    if isinstance(cell, (int, float, Decimal)):
        return round(float(cell), DECIMALS)
    return cell.strip() if isinstance(cell, str) else cell


def _grid(result: Result) -> list[tuple]:
    return [tuple(_value(cell) for cell in row) for row in result.rows]


def _column(rows: list[tuple], index: int) -> tuple:
    return tuple(row[index] for row in rows)
