# NL2SQL - Run 3: schema map import (Excel + live DB) and PII protection

> DRAFT - waiting for Eren's approval of the scope. Builds on Run 1 (Phase 0) and Run 2 (Phase 2 retrieval + A/B
> eval). This run = the rest of Phase 1 (getting a customer's schema in without hand-writing `schema.json`) and the
> rest of Phase 4 (PII masking, DB-level read-only script), plus a test clean-up. Web UI, charts and written reports
> are Run 4.

## 0. Input from earlier runs

- Run 1: 7/10 on Strata; all failures = business-definition ambiguity -> rules matter.
- Run 2: `schema/schema.json` (83 tables, hand-made by the agents) is the only way a schema enters the system today.
  A customer will bring an Excel map (any layout) and a live SQL Server. The plan's promise is "5 dakikada bağlıyorum":
  a skeleton from the live DB works without Excel; Excel only enriches.
- Run 2 cost: tests that pinned a count of a growing set (`Q01..Q20`, `10/10`) or assumed every table has rows broke
  4 tasks and burnt 4 cloud rescues. **Rule for this run: tests over a growing or configurable set assert structure
  (ids sequential and unique, every item checked), never a fixed count; a test that depends on data volume reads it
  from the dataset/config.**

## 1. Goal

From an Excel schema map (two very different layouts) and/or a database connection, produce the canonical
`schema.json` deterministically, show what differs between the two, build the index from it, and answer questions
with the same agent - with personal data masked before any row reaches the model or the screen.

"Done" =
- `python -m nl2sql import-map tests/fixtures/map_netsis_style.xlsx` proposes a column mapping, `--accept` writes a
  canonical schema, and for the generated fixture that schema equals `schema/schema.json` (round trip).
- `python -m nl2sql introspect` builds a skeleton schema from the live DB (SQLite in tests, SQL Server by hand) and
  `diff-map` lists Excel-only / DB-only tables and columns and type mismatches.
- `eval --mode rag --schema skeleton` vs `--schema full` measures how much the descriptions are worth (this is the
  data behind the plan's "Excel opsiyonel" decision).
- A PII bypass test set (>= 20 cases) is masked or rejected.

**Core rules (unchanged):** LLM only proposes (the Excel mapping, never the rows); every transformation of rows is
code; every execution goes through the policy inside the executor; read-only; tests never call a real model or a real
SQL Server.

## 2. Scope

**In (Run 3):**

- **Test clean-up first (M7, first task).** The golden-vs-reference check exists in 5-6 files
  (`tests/test_golden_reference.py`, `test_golden_q11_q20.py`, `test_golden_q21_q30.py`, `test_golden_q31_q40.py`,
  parts of `test_integration_m2.py`, `test_integration_m4.py`). Merge it into one parametrized file over all golden
  lines with the same per-question checks (policy pass, transpile, run, equals reference, >=1 row, ordering), keep every
  distinct assertion, delete the duplicates. The task names every file it edits or deletes. Report the test count
  before/after; coverage of behaviours must not shrink.
- **Excel import** (`nl2sql/schema_map/excel.py`), `openpyxl` only (no pandas):
  - Read sheets, header row detection (first row with >= 3 text cells), first 20 rows preview.
  - **Mapping proposal**: the LLM gets only sheet names, headers and 20 sample rows and returns JSON
    `{sheet, header_row, table_name, column_name, data_type, description, fk_target, values, nullable, module}`
    (column letters or header names; missing = null). A **deterministic fallback** (header synonym table in
    `profiles/excel_headers.json`: TABLO/TABLE/TABLO ADI, KOLON/ALAN/FIELD, TİP/TYPE, AÇIKLAMA/DESCRIPTION, ...) is
    used when the LLM is unreachable and to sanity-check the LLM proposal (disagreements are shown).
  - CLI: `import-map <file.xlsx> [--llm fake|openai]` prints the proposal and writes `schema/mapping.<name>.json`;
    the user edits it if needed; `import-map <file.xlsx> --accept [--mapping m.json] [--out schema/imported.json]`
    converts **all** rows with code (never the LLM): group rows by table, normalise types, parse `values` cells like
    `G=Giriş; C=Çıkış`, keep row order, report skipped/invalid rows with sheet+row number.
  - Fixtures generated from `schema/schema.json` by a script (`tests/fixtures/make_maps.py`): (a) a tidy
    "Netsis-style" map (one sheet, one row per column), (b) a messy "customer" map (two sheets: tables and columns,
    Turkish headers in a different order, a title row and an empty row above the header, merged-looking blank cells
    repeating the table name, mixed-case type names, a few rows with missing descriptions). Both round-trip to the same
    tables/columns; (a) round-trips exactly.
- **Live schema introspection** (`nl2sql/schema_map/introspect.py`):
  - SQLite: `sqlite_master` + `PRAGMA table_info` / `foreign_key_list`.
  - SQL Server (written, not exercised by tests): `INFORMATION_SCHEMA.TABLES/COLUMNS` + `sys.foreign_keys`, through a
    read-only connection from `NL2SQL_MSSQL_CONN`; query text kept in one place and unit-tested by parsing with sqlglot.
  - Skeleton schema: names, types, nullability, fks; descriptions empty; inferred join edges from the ERP profile;
    `kind` = "unknown". Optional `--sample` adds up to 5 distinct values per short text column (through the executor
    and policy, PII columns excluded) as hints.
- **Merge + diff** (`nl2sql/schema_map/merge.py`): live DB is the truth for existence and types, Excel for meaning
  (description, values, module, keywords). `diff-map --excel schema/imported.json --db` writes
  `schema/diff.md|json`: tables/columns only in Excel, only in DB, type mismatches, fks in Excel missing in DB.
  `merge-map` writes the merged canonical schema. A schema version (content hash) is stored in the index meta; the
  index refuses a schema it was not built from (already in Run 2 - keep it working with imported schemas).
- **Eval on imported/skeleton schemas:** `eval --schema <path|full|skeleton>` (default the current `schema/schema.json`)
  so the same 40 questions measure: hand schema vs imported-from-messy-Excel vs skeleton. Report shows which schema
  (path + hash) was used.
- **PII protection** (`nl2sql/policy/pii.py`):
  - Schema columns get an optional `pii` class: `tckn`, `vkn`, `iban`, `phone`, `email`, `address`, `salary`,
    `person_name`. The synthetic world gets real PII-shaped (fake, checksum-valid where a checksum exists) data in the
    personnel tables (`TBLPERSONEL`, `TBLMAAS`, `TBLMAASDETAY` get rows) and address/phone/email in `TBLCARISUBE`
    - added with their own random stream; Run 1/Run 2 rows and golden answers unchanged.
  - Masking is done **inside the executor, after execution, before the result is returned** (to the model, the CLI and
    the eval): output columns are traced back to source columns with sqlglot lineage; any output that depends on a PII
    column is masked per class (`tckn` -> `*******1234`, `iban` -> `TR** **** ... 1234`, `salary` -> `***`, address ->
    city only), except whitelisted aggregates (`COUNT`, `COUNT(DISTINCT)`), which stay. If lineage cannot be resolved
    for an output column, the whole column is masked (fail closed).
  - Policy additions: PII columns in `WHERE`/`JOIN`/`GROUP BY`/`ORDER BY` are rejected by default (they leak through
    filters, e.g. `WHERE TCKN LIKE '1%'`), configurable per class.
  - **PII bypass test set** (`tests/data/pii_bypass.jsonl`, >= 20): aliases, CTE renames, `CONCAT`/`+` with another
    column, `CAST`/`CONVERT`, `SUBSTRING`/`LEFT`/`RIGHT`, `CASE WHEN`, `UNION` into a non-PII column position, scalar
    subqueries, derived tables, `MAX(MAAS)`, `AVG(MAAS)` (salary aggregates are masked too), `STRING_AGG`, filter side
    channels. Each case: expected `masked` (with which output columns) or `rejected`.
  - The audit log records which columns were masked (names only).
- **DB-level protection script** (the primary control, the sqlglot policy is the second layer):
  `python -m nl2sql make-login-script [--login nl2sql_ro]` writes `db/mssql/readonly_login.sql`: CREATE LOGIN with a
  password **placeholder** (never a real one), CREATE USER, `db_datareader`, `DENY SELECT` on every table not in the
  allowlist and on PII columns (column-level DENY), `DENY VIEW DEFINITION`, `DENY EXECUTE`; header comments explain
  that views/synonyms/TVFs can bypass a parser allowlist, so this script is what really limits access. Tests parse the
  script with sqlglot tsql and check the DENY lines match the schema.
- **Real-data checklist** in README: how Eren runs `introspect`, `import-map`, `diff-map`, `ask`, `eval` against a
  Netsis **copy** with the generated read-only login; nothing in this run connects to a real server.

**Out (Run 3) -> Run 4:** web UI (FastAPI + React), charts (spec + ECharts), written Turkish report with a number
guard, Excel/CSV export, saved queries. **Out (later):** Topology C (runner.exe), multi-user/auth, reranker,
bge-m3 switch (config change, measured with `eval-retrieval`), real SQL Server CI.

## 3. Method / architecture

```
Excel map --(LLM proposes mapping, user accepts)--> code converts rows --> imported.json --\
live DB --introspect--> skeleton.json -----------------------------------------------------> merge --> schema.json
                                                                       diff.md <-----------/            |
                                                                                                  build-index
ask/eval --> agent --> Executor: policy (tables, PII filters) -> run -> PII masking (lineage) -> Result
```

## 4. Stack and environment

- Python 3.11 `.venv` as before (sqlglot 30.24.0, openai 3.37.0, pytest 9.1.1, pyodbc 5.3.0) **plus openpyxl**
  (MIT, pure Python; installed into `.venv` before the run, version pinned in pyproject). No pandas, no other new
  dependency.
- LLM / embeddings as Run 2 (Strata :8080, EmbeddingGemma on CPU :8891). Tests: fakes only.

## 5. Data

Synthetic, seeded, fictional; PII-shaped values are fake (checksum-valid TCKN/IBAN generated, never real people).
Privacy class: public/synthetic.

## 6. Interfaces

- `import-map <xlsx> [--llm ...] [--accept] [--mapping ...] [--out ...]`
- `introspect [--out schema/skeleton.json] [--sample]`, `diff-map --excel <json> --db`, `merge-map ... --out ...`
- `eval --schema <path|full|skeleton> ...`, `make-login-script [--login ...]`

## 7. Acceptance tests

1. Golden test clean-up: one parametrized file, all per-question checks kept, duplicates gone, whole suite green.
2. Excel: tidy fixture round-trips exactly; messy fixture yields the same tables/columns (descriptions may be missing
   where the fixture removed them); fallback mapping works with the LLM unreachable; invalid rows reported with
   sheet+row.
3. LLM mapping with FakeLLM: correct proposal accepted; a wrong proposal is caught by the fallback comparison and shown.
4. Introspect on the built SQLite DB equals schema.json on names/types/nullability/fks; MSSQL queries parse.
5. Diff: a fixture with 2 removed tables, 3 extra columns and 1 type change is reported exactly.
6. Eval with `--schema skeleton` and an imported schema runs with the fake LLM; report names schema path + hash.
7. PII: every bypass case masked/rejected as expected; non-PII golden questions unchanged (all 40 still pass with the
   fake LLM); audit has masked column names and no values.
8. Login script: DENY lines match allowlist and PII columns; password is a placeholder.
9. Smoke: build-db, build-index --embed fake, import-map (fixture, --accept, --llm fake), introspect, diff-map,
   eval --compare --llm fake exit 0. Smokes for later milestones tagged with "from".

## 8. Milestones

- **M7 - Clean-up + Excel import:** test merge, openpyxl reader, header detection, mapping proposal + fallback,
  accept/convert, fixtures, tests 1-3.
- **M8 - Live schema:** introspect (SQLite + MSSQL), merge, diff, `eval --schema`, tests 4-6.
- **M9 - PII + DB script:** PII classes + synthetic PII data, lineage masking, filter rules, bypass set, audit,
  login script, README real-data checklist, tests 7-9.

Keep it to **at most ~32 tasks**.

## 9. Open questions / risks

- sqlglot lineage on complex T-SQL may fail; fail closed (mask) and count how often it happens.
- Which Excel map will the first real test use? Employer contract (competition/IP clauses) must be checked before a
  company Netsis map is used.
- The read-only login must exist before any real-data test; Windows auth on this PC is sysadmin and is never used.
