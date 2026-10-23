# REVIEW M1 (T01-T07)

Base 6ec67c3 -> HEAD 365bc7e. Full suite: 270 passed. No fix tasks added.

- **Smoke RED (`No module named nl2sql.__main__`)**: not a regression and no stale test. `nl2sql/__main__.py` and the CLI
  are T20 (M3); `build-db`, `eval`, `ask` cannot run until then. T20/T24 already own it (T24 accept = these three commands).
- ASSUMPTION config.py:41 (model id "strata", override NL2SQL_LLM_MODEL): fine for local servers; T13 must read it via llm_settings().
- ASSUMPTION doc.py:10 (Turkish descriptions): fine, matches Turkish questions.
- ASSUMPTION generator.py:388 (cancelled invoices have no stock lines; GENELTOPLAM-vs-lines only for invoices with lines): consistent
  with Q04/Q06 (golden and naive both verified); the FK/consistency tests encode the same rule.
- ASSUMPTION test_traps.py:21 (9 traps, not 8 as TASKS T07 says): correct, PLAN Decision 5 lists Q02-Q10. TASKS wording is stale only.
- Checked: golden SQL == pure-Python reference and every naive SQL != golden for seeds 1, 7, 42, 123, 999 (tests only cover 42), so `build-db --seed N` is safe.
- Risk: `doc.allowlist(schema)`, `compact_text(schema)`, `table_detail(schema, tables)` take the schema as first arg, while TASKS T02 lists
  `allowlist()` / `table_detail(tables)`. M2/M3 workers must pass `doc.load_schema()` (T11, T15, T16 do carry a schema); no fix needed.
- Risk: `.hybrid/` run logs are tracked (only `.hybrid/agents/` is ignored); `db/mssql/build_test_db.sql` is not ignored, so
  the T24 smoke run will dirty the tree. Cosmetic.
- Missing tests: write_sqlite NOT NULL columns vs generator NULLs only covered through build tests; no test runs the generated
  .sql against a real MSSQL (sqlglot parse only) - expected until the MSSQL backend is available.
- Q08 golden excludes cancelled invoices (IPTAL='H') though the question text does not say so; documented only implicitly, label stays `review: pending`.
