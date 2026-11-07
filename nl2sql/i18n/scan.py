# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Which string literals of a source file still speak Turkish to a person (R8-4).

A migration test asks of its own module: "is anything user-facing left?" Every string constant that
writes a Turkish letter is reported, except the three shapes that never reach a user: a docstring,
an argument of a logging call, and a module-level constant the caller allows on purpose (model-facing
prompts and match tables stay Turkish).
"""

from __future__ import annotations

import ast
from pathlib import Path

from nl2sql.i18n.detect import TURKISH_LETTERS

LOG_OWNERS = frozenset({"logging", "log", "logger", "_log"})


def _is_turkish(text: str) -> bool:
    return any(ch in TURKISH_LETTERS for ch in text)


def _docstring(node) -> ast.Constant | None:
    """Only the first string of a module/class/function body, so the rest of that body stays scanned."""
    body = getattr(node, "body", ())
    if not body or not isinstance(body[0], ast.Expr):
        return None
    value = body[0].value
    return value if isinstance(value, ast.Constant) and isinstance(value.value, str) else None


def _is_log_call(node: ast.Call) -> bool:
    func = node.func
    return (
        isinstance(func, ast.Attribute)
        and isinstance(func.value, ast.Name)
        and func.value.id in LOG_OWNERS
    )


def user_literals(path, allow=()) -> list[tuple[int, str]]:
    """`(line, text)` of every Turkish literal in `path`, in source order.

    `allow` names module-level constants that stay Turkish; a dotted entry ("narrate.SYSTEM") counts
    by its last part. An allowed value is exempt whole, so a Turkish text inside its dict or f-string
    is not reported either.
    """
    tree = ast.parse(Path(path).read_text(encoding="utf-8"))
    allowed = {str(name).rsplit(".", 1)[-1] for name in allow}
    exempt: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = _docstring(node)
            if doc is not None:
                exempt.add(id(doc))
        elif isinstance(node, ast.Call) and _is_log_call(node):
            exempt.update(id(child) for child in ast.walk(node))
    for stmt in tree.body:
        if not isinstance(stmt, (ast.Assign, ast.AnnAssign)) or stmt.value is None:
            continue
        targets = stmt.targets if isinstance(stmt, ast.Assign) else [stmt.target]
        if any(isinstance(target, ast.Name) and target.id in allowed for target in targets):
            exempt.update(id(child) for child in ast.walk(stmt.value))
    found = [
        (node.lineno, node.col_offset, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in exempt
        and _is_turkish(node.value)
    ]
    return [(line, text) for line, _, text in sorted(found)]
