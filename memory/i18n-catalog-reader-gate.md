---
name: i18n-catalog-reader-gate
description: A new catalog key must be read by a literal string in nl2sql/ — t(f"prefix.{k}") only passes if its prefix is already in test_i18n_catalog_use's frozen DYNAMIC_PREFIXES
metadata:
  type: feedback
---

`tests/test_i18n_catalog_use.py::test_every_key_is_read_by_the_code_or_frozen_by_a_test` fails a new
`nl2sql/i18n/*.json` key that no source file mentions as a **string constant**. Building keys at
runtime (`t(f"cli.paths.{key}", lang)`) is invisible to its AST scan unless the prefix is listed in
`DYNAMIC_PREFIXES` — and that tuple lives in an existing test, which hands-off tasks may not edit.

**Why:** the test is the catalog's "no key without a reader" hygiene gate; the dynamic list is the
only escape hatch and it is hand-curated (`facts.`, `cli.help.`, `ask.fail.`, …).

**How to apply:** when a command renders a fixed set of labels, write the full keys as literals —
e.g. a `labels = {"home": _t("cli.paths.home", lang), ...}` dict — instead of interpolating the
name. Same for a new family of keys: either literal keys, or reuse a prefix already in the tuple.
Related: [[i18n-scan-all-allow]] (the other i18n gate: Turkish literals), [[cli-help-golden-pin]]
(the other test a new subcommand trips).
