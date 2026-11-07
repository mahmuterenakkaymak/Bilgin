# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Value types the execution layer passes around: what it may spend, what it got, what failed."""

from __future__ import annotations

from dataclasses import dataclass, field

from bilgin import config

ERROR_KINDS = ("policy", "transpile", "sql", "timeout")


@dataclass(frozen=True)
class Budget:
    """What one query may spend: rows the caller keeps, seconds before it is stopped."""

    max_rows: int = config.MODEL_MAX_ROWS
    timeout_s: float = config.QUERY_TIMEOUT_S


@dataclass(frozen=True)
class ExecError:
    kind: str  # one of ERROR_KINDS
    message: str  # short, readable by the model


@dataclass(frozen=True)
class Result:
    """Rows as the database returned them, PII columns already masked; row_count is the total before truncation."""

    columns: list[str] = field(default_factory=list)
    rows: list[tuple] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    elapsed_ms: float = 0.0
    error: ExecError | None = None
    masked_columns: list[str] = field(default_factory=list)  # output names, in select order
    tables: list[str] = field(default_factory=list)  # upper full names read, sorted; display only
