# NL2SQL - Run 1: Phase 0 proof (kill gate) + CLI vertical slice

> Working title. Source design: "NL2SQL Asistanı - Proje Taslağı v0.1" and "Uygulama Planı: Topoloji A + C v0.1"
> (2026-10-23). This brief covers **Run 1 only** = Phase 0 of the plan (does a local model + tool calling write correct
> T-SQL?) plus the minimum around it: a deterministic eval, a safe executor and a terminal demo. Later phases are
> listed at the end so the architecture leaves room for them.

## 1. Goal

One command answers the project's kill-gate question with a **number**: on a synthetic Netsis-like test database,
how many of 10 golden Turkish questions does the local LLM answer correctly (execution accuracy), with how many tool
calls, how many tokens of context and how much time? A second command asks one free question in the terminal and
prints the steps, the generated SQL and the result table.

"Done" = `python -m bilgin eval --llm fake` is green in CI-style tests, and `python -m bilgin eval` against the local
OpenAI-compatible endpoint produces `eval_out/report.md` with a score like `7/10` and per-question details.

**Core rules (non-negotiable):**
- The LLM only writes SQL. It never computes a number itself; every number shown comes from executing SQL.
- Execution always goes through the policy inside the executor; there is no code path that runs model SQL without it.
- Golden answers are not trusted because an LLM wrote them: every golden SQL result is checked against an
  **independent Python computation** over the seed data (two derivations must agree).
- Read-only: the system never writes to a database it queries. The test database is built by a separate build step.

## 2. Users and use cases

- **Eren (developer):** runs the eval after changing prompt, model or tools and compares numbers between runs.
- **Demo viewer (Eren's colleague/manager):** watches `python -m bilgin ask "Eylül ayında en çok satan 5 ürün"`
  print the agent steps, the SQL, and a table - all on synthetic data, no company data.

## 3. Scope

**In (Run 1):**

- **Synthetic Netsis-like test database** (fictional data, Netsis-style naming), built deterministically from a seeded
  Python generator into **SQLite** (`data/test.db`), plus a generated **T-SQL script** (`db/mssql/build_test_db.sql`:
  CREATE TABLE + INSERT) so the same data can be loaded into SQL Server by hand later. ~10 tables:
  - `TBLSTSABIT` stock cards (STOK_KODU, STOK_ADI, GRUP_KODU, OLCU_BR1, KDV_ORANI, ...)
  - `TBLSTGRUP` stock groups
  - `TBLCASABIT` customer/supplier cards (CARI_KOD, CARI_ISIM, CARI_TIP alici/satici, IL, PLASIYER_KODU, ...)
  - `TBLPLASIYER` sales reps
  - `TBLDEPO` warehouses
  - `TBLFATUIRS` invoice headers (FTIRSIP type code, FATIRS_NO, CARI_KODU, TARIH, GENELTOPLAM, IPTAL flag, ...)
  - `TBLSTHAR` stock movements (STOK_KODU, STHAR_GCKOD 'G'/'C', STHAR_GCMIK qty, STHAR_NF net price, STHAR_TARIH,
    STHAR_HTUR movement type, DEPO_KODU, FISNO -> invoice, ...)
  - `TBLCAHAR` customer account movements (debit/credit)
  - `TBLSIPAMAS` / `TBLSIPATRA` order header / order lines
  Column names are short, coded and Turkish like the real ERP (that is the difficulty), but the tables and data are
  invented for this test - do not try to copy a real Netsis schema. Coded columns (G/C, type codes, flags) are
  documented with their values in the schema document.
- **Data that exposes wrong SQL.** Small, clean data lets a wrong join return the right answer by luck. The seed data
  must contain, on purpose: returns (iade movements) that must be subtracted; cancelled invoices (`IPTAL`) that must
  be excluded; the same product in several warehouses; a product with several price lines; customers that are both
  buyer and seller; movements without an invoice; NULL dates/optional fields; one 1:N join that fans out (summing
  header totals after joining lines triples the number). Data volume: a few hundred stock movements over Jun-Sep 2026,
  enough that every trap changes at least one golden answer. Fixed reference date **`AS_OF = 2026-09-30`** (config):
  "geçen ay", "bu yıl" are relative to it, never to the real clock.
- **Schema document** (`schema/schema.json`, canonical format from the design doc: table, description, module,
  columns with type, description, fk, values) and a generated compact text form for the prompt. One hand-written
  document is enough in Run 1 (no Excel import, no INFORMATION_SCHEMA merge yet).
- **10 golden questions** (`eval/golden.jsonl`): Turkish question, golden T-SQL, ordering-matters flag, notes on which
  trap it tests. Mix: simple filter, group-by top-N, date range relative to AS_OF, join of 3+ tables, returns
  subtracted, cancelled excluded, fan-out trap, coded value (G/C), customer-type filter, one HAVING/ratio question.
  For each question an **independent Python reference** (`eval/reference.py`) computes the expected rows straight
  from the generator's in-memory data (no SQL). A test asserts golden SQL result == Python reference for all 10.
  Questions are marked `review: pending` - Eren reviews the wording and intent after the run.
- **Policy** (`bilgin/policy/`, sqlglot, dialect tsql): exactly one statement; only SELECT (CTEs and UNION of SELECTs
  allowed); **default-deny table allowlist checked on the parse tree** (real table references only; CTE names and
  aliases are not tables, a CTE named like a forbidden table must not hide it); no cross-database or server names
  (`OtherDB.dbo.X`), no `sys.*` / `INFORMATION_SCHEMA` / `xp_` / `sp_` / `OPENROWSET` / `OPENQUERY` /
  `OPENDATASOURCE`, no `SELECT INTO`, no table-valued function calls; inject `TOP n` (config, default 1000) when there
  is none; reject with a clear, model-readable reason. A malicious-SQL test set of at least 20 cases (multi-statement,
  comment injection, UPDATE in a CTE, sys access through UNION, CTE shadowing, bracket/quoted names, case tricks,
  SELECT INTO, EXEC) - all must be rejected; all 10 golden SQLs must pass.
- **Executor interface** (`bilgin/engine/`): `Executor.execute(sql, budget) -> Result{columns, rows, row_count,
  truncated, elapsed_ms, error}`. Policy is called **inside** the executor. `LocalExecutor` with two backends:
  - SQLite (used by all tests and the default run): the T-SQL is transpiled with sqlglot (`read="tsql",
    write="sqlite"`) after the policy check; a transpile failure is reported as its own error kind, not as a model
    error. The SQLite connection is opened read-only (`mode=ro` URI).
  - SQL Server via pyodbc (optional, not exercised by tests): connection string only from env `BILGIN_MSSQL_CONN`,
    `ApplicationIntent=ReadOnly`, query timeout from config, `SET LOCK_TIMEOUT`. Never a hard-coded connection string.
  Query budget: max rows returned to the model (default 50, rest truncated with a note), timeout.
- **Agent loop** (`bilgin/agent/`): OpenAI-compatible chat completions with tool calling (`openai` SDK; base URL and
  model from env `BILGIN_LLM_BASE_URL` default `http://127.0.0.1:8080/v1`, `BILGIN_LLM_MODEL`, optional
  `BILGIN_LLM_API_KEY` default `local`). Tools: `get_schema(tables?: list)` (no arg = compact list of all tables with
  one-line descriptions; with tables = full columns and code values), `run_sql(sql)` (through the executor; returns
  columns, first rows, row count or the error/policy reason), `submit_sql(sql)` (final answer). System prompt states
  the dialect (T-SQL), AS_OF, and the rules. Limits: max 8 tool calls, max 3 failed `run_sql` calls, total timeout.
  Thinking: `chat_template_kwargs.enable_thinking` from config (default on); `<think>...</think>` stripped from text if
  the server returns it inline. Every step is recorded (tool, args, result summary, prompt/completion tokens from
  `usage`, latency) for the CLI and the eval report.
- **Context budget measurement:** for each question record the largest `prompt_tokens` of any call and the total;
  the report shows max/median, so the hardware tier decision (16/24/32 GB) has data.
- **Eval runner** (`bilgin/eval/`): runs each golden question through the agent, executes the submitted SQL through
  the same executor, compares with the golden result. Comparison: rows as a multiset (order ignored unless the
  question's ordering flag is set), numbers rounded to 2 decimals, strings trimmed; each golden column must match a
  distinct predicted column by values (column names and order ignored); extra predicted columns allowed but listed.
  Outcome per question: `pass` / `wrong_result` / `sql_error` / `policy_reject` / `transpile_error` /
  `no_submission` / `timeout` / `llm_error`. Output: `eval_out/<timestamp>/report.json` + `report.md` (score,
  per-question outcome, SQL, tool calls, tokens, seconds, model name, config) and `eval_out/latest` copy.
  The decision table from the plan is printed with the score: >= 7/10 continue, 5-6 revise prompt/tools, < 5
  reconsider.
- **Fake LLM** for tests and smoke: a scripted client that replays tool calls (e.g. submits the golden SQL, submits a
  wrong SQL, calls a forbidden table, never submits) so every outcome kind is tested without a model.
- **CLI** (`python -m bilgin`): `build-db [--seed n]`, `ask "<question>"` (prints numbered steps, final SQL, result as
  an aligned text table, tokens and seconds; Turkish labels), `eval [--llm fake|openai] [--only Q03]`.
- **Audit log** (`logs/audit.jsonl`): time, question id or "ask", SQL, elapsed, row count, outcome. **Result rows are
  never written to the log.**

**Out (Run 1) - later runs:** RAG/LanceDB/bge-m3, join graph (networkx), Excel schema import, INFORMATION_SCHEMA
merge, PII masking, web UI (FastAPI + React), Topology C (runner.exe, RemoteExecutor), charts, saved queries,
multi-user, auth, 40-60 question set, real SQL Server CI.

## 4. Method / architecture

```
generator (seeded) -> in-memory rows -> SQLite data/test.db  + db/mssql/build_test_db.sql
                                    \-> eval/reference.py (Python truth for golden answers)

CLI ask/eval -> agent loop -> LLM (OpenAI-compatible)          tools: get_schema | run_sql | submit_sql
                     |                                                          |
                 schema doc                       Executor (policy inside) -> SQLite (ro) / SQL Server (ro)
```
- Package layout leaves room for the plan: `bilgin/{schema_map,policy,engine,agent,eval,cli}` (+ later `index`,
  `graph`, `api`, `runner`).
- Config at the top of `bilgin/config.py` (AS_OF, seed, TOP n, row budget, timeouts, tool limits, thinking on/off,
  endpoint defaults); env vars override endpoint/model/connection.
- Deterministic everything: same seed -> identical database (checksum test).

## 5. Stack and environment

- Python 3.11, `uv`, `.venv` already created in the repo with **sqlglot 30.24.0, openai 3.37.0, pytest 9.1.1,
  pyodbc 5.3.0** installed. Use only these plus the standard library (sqlite3, json, statistics, argparse). Pin them
  in `pyproject.toml`; do not add other dependencies.
- Windows 11; tests: `.venv/Scripts/python -m pytest -q`; run: `.venv/Scripts/python -m bilgin ...`.
- LLM: local OpenAI-compatible endpoint only (Strata on `127.0.0.1:8080` during development, later llama.cpp with a
  27B model). No cloud LLM, no API keys in code. Tests never call a real model.

## 6. Data

Synthetic only, seeded, reproducible, fictional companies/products/people. No customer or employer data.
Privacy class: public/synthetic.

## 7. Interfaces

- `python -m bilgin build-db [--seed 42]` -> `data/test.db`, `db/mssql/build_test_db.sql`
- `python -m bilgin ask "<soru>"`
- `python -m bilgin eval [--llm fake|openai] [--only Q03]` -> `eval_out/latest/report.md`
- Env: `BILGIN_LLM_BASE_URL`, `BILGIN_LLM_MODEL`, `BILGIN_LLM_API_KEY`, `BILGIN_MSSQL_CONN`, `BILGIN_BACKEND`
  (`sqlite` default | `mssql`).

## 8. Constraints

- Read-only connections; nothing in `bilgin/` writes to the queried database (only `build-db` creates the SQLite file).
- No secrets in the repo; `.gitignore`: `.venv/`, `data/*.db`, `eval_out/`, `logs/`, `.env`.
- Error messages to the model are short and actionable (they are part of the prompt budget).
- Turkish user-facing CLI text; English code, comments, docs.

## 9. Acceptance tests

1. Same seed -> identical database (row counts per table + checksum); a different seed changes it.
2. Every trap from section 3 is present in the data and changes at least one golden answer (test per trap: the
   "naive" SQL that ignores the trap gives a different result than the golden SQL).
3. All 10 golden SQLs pass the policy, transpile, run on SQLite and equal the independent Python reference.
4. The malicious-SQL set (>= 20 cases) is rejected with a reason; `TOP n` is injected when missing and kept when
   present.
5. The executor cannot run SQL without the policy (no public method that skips it); SQLite opened read-only (a write
   attempt through the raw connection fails).
6. Result comparison: unit tests for row order, column order/naming, extra columns, numeric rounding, ordering flag.
7. Agent loop with the fake LLM: pass path, wrong result, policy reject then recovery, 3 failed `run_sql` -> stop,
   tool-call limit, no submission, LLM unreachable -> `llm_error` (no crash).
8. `eval --llm fake` writes report.json/report.md with all fields (score, outcomes, tokens, seconds, decision line).
9. `ask` with the fake LLM prints steps, SQL and a table; audit log has the entry without result rows.
10. Smoke: `build-db` then `eval --llm fake` on a clean checkout exits 0.

## 10. Milestones

- **M1 - Data + truth:** config, generator, SQLite + T-SQL script, schema document, golden questions, Python
  reference, tests 1-3 (policy part of 3 comes in M2).
- **M2 - Safe execution:** policy, malicious set, executor (SQLite ro + MSSQL backend), audit log, tests 3-5.
- **M3 - Agent + eval + CLI:** OpenAI-compatible client, tools, loop, fake LLM, comparison, eval runner, report,
  `ask`, README (how to run against Strata and against a llama.cpp 27B), tests 6-10.

Keep the plan small: **at most ~22 tasks**. This run is a measurement tool, not the product.

## 11. Open questions / risks

- Golden questions and SQL are written by the agents in this run; Eren reviews them afterwards (`review: pending`).
  The Python reference protects the numbers, not the question's intent.
- SQLite + transpile is a proxy for SQL Server; the real kill-gate number is measured later on SQL Server with the
  generated T-SQL script. Transpile failures are counted separately so they are not blamed on the model.
- Model for the first real run: Strata (Qwen3.8-Flash-Next) because it is what runs in agent mode; the 27B number
  needs creative mode / llama.cpp and is a follow-up run.
