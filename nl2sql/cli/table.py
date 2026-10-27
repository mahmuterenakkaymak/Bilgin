"""How a result set looks on screen: aligned columns, Turkish numbers, friendly notices.

Nothing here recomputes a value; the rows are exactly what the database returned and only their
rendering changes. A column whose every value is a number is right-aligned and written the Turkish
way (1.234,56), a missing value becomes "-", and a result with nothing in it says so in a sentence
instead of leaving a blank screen.
"""

from __future__ import annotations

from decimal import Decimal

from nl2sql.engine.result import Result
from nl2sql.i18n import t

NULL_TEXT = "-"
NUMERIC_TYPES = (int, float, Decimal)

_SEPARATOR = " | "
_SWAP = str.maketrans(",.", ".,")


def format_table(result: Result, lang: str = "tr") -> str:
    """The rendered table, or the notice that replaces it when there is nothing to show."""
    if not result.rows:
        return t("cli.table.empty", lang)

    grid = [[_cell(cell) for cell in row] for row in result.rows]
    numeric = [_is_numeric(result.rows, i) for i in range(len(result.columns))]
    widths = [
        max(len(header), *(len(row[i]) for row in grid))
        for i, header in enumerate(result.columns)
    ]

    def line(cells: list[str]) -> str:
        return _SEPARATOR.join(
            cell.rjust(w) if num else cell.ljust(w)
            for cell, w, num in zip(cells, widths, numeric)
        )

    lines = [line(list(result.columns)), " + ".join("-" * w for w in widths)]
    lines += [line(row) for row in grid]
    text = "\n".join(lines)
    if result.truncated:
        text += "\n" + t(
            "cli.table.truncated", lang, rows=len(result.rows), total=result.row_count
        )
    return text


def _cell(value) -> str:
    """One value as text: numbers grouped for a Turkish reader, everything else as it reads."""
    if value is None:
        return NULL_TEXT
    if isinstance(value, int):
        return f"{value:,d}".translate(_SWAP)
    if isinstance(value, (float, Decimal)):
        return f"{value:,.2f}".translate(_SWAP)
    return str(value)


def _is_numeric(rows: list[tuple], index: int) -> bool:
    """A column is numeric when it holds at least one number and nothing but numbers and NULLs."""
    seen = False
    for row in rows:
        cell = row[index]
        if cell is None:
            continue
        if not isinstance(cell, NUMERIC_TYPES):
            return False
        seen = True
    return seen
