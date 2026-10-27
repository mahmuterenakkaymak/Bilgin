"""Catalog hygiene (R8-4): no key without a reader, no Turkish letter in the English column, and the
Turkish column still says the exact sentence every test writes down.

The three questions the catalog has to keep answering: who reads this key; is the English row really
English; and did a sentence a test froze move. The first is answered from the source of `nl2sql/` -
a key written as a string constant, or assembled at runtime behind a `DYNAMIC_PREFIXES` prefix, or
frozen by a test, which no task may un-pin by deleting the key.
"""

from __future__ import annotations

import ast
import json
from functools import lru_cache
from pathlib import Path

from nl2sql.i18n import CATALOG_DIR
from nl2sql.i18n.detect import TURKISH_LETTERS

PACKAGE_DIR = CATALOG_DIR.parent
TESTS_DIR = CATALOG_DIR.parents[1] / "tests"

# Keys the code assembles while it runs: t(f"facts.{name}"). The suffix comes from data, so no
# literal in the source carries the finished key and the prefix is the only evidence there is.
DYNAMIC_PREFIXES = (
    "facts.",  # report/facts.py
    "chart.kind.",  # report/chart.py
    "chart.problem.",  # report/chart.py
    "ask.kind.",  # app/ask.py
    "ask.fail.",  # app/ask.py, and start/cards.py adds the "exec:" step
    "refine.which.",  # agent/refine.py
    "retrieval.variant.",  # eval/retrieval.py
    "rules.label.",  # schema_map/rules_edit.py
    "cli.help.",  # cli/main.py
)


def load(lang: str) -> dict[str, str]:
    return json.loads((CATALOG_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def _strings(tree: ast.AST, *, outside_docstrings: bool = False) -> set[str]:
    docs: set[int] = set()
    if outside_docstrings:
        for node in ast.walk(tree):
            if not isinstance(
                node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ):
                continue
            body = getattr(node, "body", ())
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docs.add(id(body[0].value))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docs
    }


@lru_cache(maxsize=1)
def _usage() -> tuple[frozenset[str], tuple[tuple[str, str, bool], ...]]:
    """Keys the package writes, and the `(key, sentence, turkish_only)` sentences tests write down.

    A test freezes a sentence in two shapes: a table of `key: sentence` (the `TODAY` dictionaries of
    the language tests, always the Turkish row) or a `...["key"] == sentence` comparison, which the
    catalog tests use for both languages.
    """
    keys = frozenset(load("tr"))
    written: set[str] = set()
    for path in sorted(PACKAGE_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        written |= _strings(tree, outside_docstrings=True) & keys

    pins: list[tuple[str, str, bool]] = []
    for path in sorted(TESTS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                table = [
                    (key.value, sentence.value)
                    for key, sentence in zip(node.keys, node.values)
                    if isinstance(key, ast.Constant)
                    and isinstance(sentence, ast.Constant)
                    and isinstance(key.value, str)
                    and isinstance(sentence.value, str)
                ]
                if len(table) >= 2 and all(key in keys for key, _ in table):
                    pins.extend((key, sentence, True) for key, sentence in table)
            elif isinstance(node, ast.Compare) and isinstance(node.left, ast.Subscript):
                slot = node.left.slice
                if not (
                    isinstance(slot, ast.Constant)
                    and isinstance(slot.value, str)
                    and slot.value in keys
                ):
                    continue
                for comparator in node.comparators:
                    if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str):
                        pins.append((slot.value, comparator.value, False))
    return frozenset(written), tuple(pins)


def test_every_key_is_read_by_the_code_or_frozen_by_a_test():
    written, pins = _usage()
    frozen = {key for key, _, _ in pins}
    # ASSUMPTION: lang.tr/lang.en name the two languages for a person and no code reads them, but
    # test_i18n_core pins them by key and this task may not edit that test: a frozen key stays.
    unused = [
        key
        for key in load("tr")
        if key not in written
        and not key.startswith(DYNAMIC_PREFIXES)
        and key not in frozen
    ]
    assert unused == []


def test_english_values_hold_no_turkish_letter():
    bad = {
        key: value
        for key, value in load("en").items()
        if any(char in TURKISH_LETTERS for char in value)
    }
    assert bad == {}


def test_turkish_values_are_the_sentences_tests_pin():
    turkish, english = load("tr"), load("en")
    drifted = [
        f"{key}: test {sentence!r}, katalog {turkish[key]!r}"
        for key, sentence, turkish_only in _usage()[1]
        if sentence != turkish[key] and (turkish_only or sentence != english[key])
    ]
    assert drifted == []
