# NL2SQL (Bilgin) - Run 5: web UI, charts, written report, clarification

> Drafted 2026-10-24 from docs/PROJE-DOKUMANI.md v0.3 (roadmap item 5) and Eren's review decisions; chained to start
> right after Run 4 (datasets, WWI, model profiles). Builds on Run 1-4. Product name: **Bilgin** (package and CLI stay `nl2sql`).

## 0. Input from earlier runs

- Read `.hybrid/report.json`, `REVIEW.md` and the last eval reports first: Run 3 (Excel import, live schema, PII
  masking, retrieval improvements, `--mode auto`) and Run 4 (`--dataset`, WWI, `--model` profiles with context
  budgets, model comparison eval) are the base. Do not redo them; build on their interfaces. The UI works for any
  dataset and model profile (`serve --dataset ... --model ...`).
- Run 2 A/B: `full_rules` 31/40, `rag` 30/40 (6.5K tokens). Business rules are the product's moat (+8 questions).
  Retrieval recall@5 was 0.67 - losses in multi-table joins.
- The biggest product risk is a **wrong answer without an error**: at ~78 % accuracy, 1 in 5 answers can be a
  confident wrong number. This run adds the ability to ask instead of guess, and shows its evidence (SQL, tables,
  rules, warnings) on every answer.
- Rules kept from Run 3: tests over a growing or configurable set assert structure, never a fixed count; tests never
  call a real model or a real SQL Server.

## 1. Goal

A Turkish web UI where a user types a question and gets: a short written answer, a chart when the data suits one,
the result table, and the evidence (SQL, tables and rules used, masked columns, warnings) - or a clarification
question when the question is ambiguous. Plus CSV/Excel export, saved questions and a screen to define business rules.

"Done" =
- `python -m nl2sql serve` (127.0.0.1 only) serves the UI; `serve --llm fake` works with no model (golden SQL), so the
  UI can be demoed and reviewed without Strata.
- Every number in a written answer is checked against the result (number guard); a failing text is never shown.
- The eval reports, besides accuracy: answered %, accuracy when answered, wrong-answer rate and clarification
  precision/recall on a new set of ambiguous questions.

**Core rules (unchanged):** the LLM writes SQL, words and clarification options - never numbers that are not in the
result; chart type and chart data are chosen by code; every execution goes through the executor (policy, read-only,
PII masking); nothing leaves the machine.

## 2. Scope

**In (Run 5):**

- **Web API** (`nl2sql/web/`, FastAPI + uvicorn, bound to 127.0.0.1; single user, no auth - documented):
  - `POST /api/ask {question, mode?}` -> `{status: answered|needs_clarification|failed, answer_text, chart, columns,
    rows, row_count, truncated, sql, tables_used, rules_used, masked_columns, warnings, mode, timings, audit_id,
    clarification: {question, options[]}}`. Runs the same agent and executor as the CLI (no second code path).
  - `GET/POST/DELETE /api/saved` (saved questions in a local SQLite file under `data/`, not the analysed DB),
    `GET /api/history` (last N asks from the audit log, no result rows).
  - `GET /api/export/{audit_id}.csv|.xlsx` re-runs the stored SQL through the executor (rows are never stored) and
    streams CSV (UTF-8 with BOM, `;` separator for Turkish Excel) or XLSX (openpyxl).
  - `GET/POST/PUT/DELETE /api/rules`: validated edits of `rules.json` (id, name, synonyms, definition, sql_hint,
    tables); a change marks the index stale and the UI offers "indeksi yeniden kur" (`POST /api/index/rebuild`).
  - `GET /api/health`: model reachable, index fresh, schema hash, mode thresholds.
  - API tests with FastAPI's TestClient and the fake LLM.
- **Chart spec, chosen by code** (`nl2sql/report/chart.py`): from the result shape - one date/period column + numeric
  -> line; one category + one numeric and <= 20 rows -> bar (sorted); share questions with <= 6 positive parts -> pie;
  two numerics -> scatter only if asked; otherwise no chart. Output is an ECharts `option` JSON built in Python
  (labels, Turkish number format) - the LLM never picks the chart or its data. Unit tests per shape.
- **Written Turkish answer with a number guard** (`nl2sql/report/narrate.py`): the LLM gets the question, column
  names, up to N result rows and a list of **facts computed by code** (totals, top item, share %, change vs previous
  period when the result has periods) and writes 1-3 sentences. The guard extracts every number in the text (Turkish
  formats: `1.234,56`, `%12`, `12,5 bin`) and accepts it only if it equals a result cell or a fact (tolerance for
  rounding stated in config). One retry with the offending numbers named; then a deterministic template sentence.
  Tests with fake LLM outputs that invent, round and reformat numbers.
- **Clarification instead of guessing** (`nl2sql/agent`): a new tool `ask_clarification(question, options[])` the
  agent may call instead of `submit_sql` when a business term is undefined or two readings change the number (e.g.
  "satış" gross vs net of returns, cancelled invoices in or out). The CLI and API return `needs_clarification`; the
  user's choice is sent back as a follow-up with the chosen reading, which is answered normally. Prompt rules for when
  to ask (only when the readings give different numbers) and when not to (a rule already defines the term).
- **Post-execution warnings, by code** (`nl2sql/engine/checks.py`): empty result; all-NULL column; a join whose row
  count is far above the row count of its driving table (fan-out suspicion, config factor); a result truncated by
  `TOP`; masked columns. Warnings go into the result, the UI shows them; nothing is silently "fixed".
- **Eval additions** (`nl2sql/eval`):
  - `eval/ambiguous.jsonl` (>= 6 questions written for this run, each with the expected behaviour
    `clarify` and the readings that differ) plus the 40 golden questions (expected `answer`).
  - Report: accuracy (as before), answered %, accuracy when answered, wrong-answer rate (answered and wrong / all),
    clarification precision (asked when it should) and recall, per mode. Fake LLM tests cover each metric.
  - Rule for the eval: a clarification on a golden question counts as not answered (not as correct), so asking too
    often lowers the score.
- **Retrieval: table summaries** (`nl2sql/index`): one summary document per table, built deterministically from the
  schema (table description, key column names and descriptions, the rules that use the table, its join neighbours)
  and indexed next to the column documents; `eval-retrieval` reports recall@k with and without them. Keep whatever
  wins; do not tune the eval.
- **PII note:** salary aggregates are already masked (Run 3); add one bypass test that a `GROUP BY` over a one-person
  group with `AVG(MAAS)` stays masked.
- **Frontend** (`web/`, React + Vite + ECharts, built into `nl2sql/web/static` and served by FastAPI; Turkish UI):
  - Question box with examples; answer card: written answer, chart, table (first 200 rows, "tamamını indir"),
    collapsible "nasıl hesapladım" (SQL, tables, rules, mode, masked columns), warnings in amber.
  - Clarification card with the options as buttons.
  - Saved questions and history sidebar; export buttons (CSV, Excel).
  - Rules screen: list, add, edit, delete with validation messages; "indeksi yeniden kur" when stale.
  - Empty, loading (step text: "şema aranıyor", "SQL çalıştırılıyor") and error states designed, not default.
  - Frontend unit tests (vitest) for formatting and components that hold logic.
  - `.hybrid/visual.json`: start `python -m nl2sql serve --llm fake --port 8777`; flows: ask a golden question
    (answer + chart), ask an ambiguous one (clarification -> pick an option -> answer), open the rules screen, export.
- **Stack additions (pin exact versions in pyproject / package.json):** fastapi, uvicorn, httpx (tests) in `.venv`;
  react, react-dom, vite, echarts, vitest in `web/`. No other new dependency.

**Out (Run 5) -> later:** public release export (Run 6), multi-user/auth, Topology C (runner), PostgreSQL/Odoo, bge-m3 switch (config, measured by
hand), real SQL Server CI, mobile.

## 3. Method / architecture

```
Browser (React) --/api--> FastAPI --> agent (same as CLI) --> executor: policy -> run -> PII mask -> checks
                                         |                                   |
                                  ask_clarification                 result + warnings
                                         v                                   v
                                needs_clarification          chart.py (code) + narrate.py (LLM + number guard)
```

## 4. Stack and environment

- Python 3.11 `.venv` as before plus fastapi/uvicorn/httpx; Node for `web/` (npm, vite). LLM: Strata :8080 (OpenAI
  compatible), embeddings as before. Tests: fake LLM and fake embedder only.

## 5. Data

Synthetic, seeded, fictional (as Run 1-3). Saved questions and history hold question text and SQL only - never result
rows.

## 6. Interfaces

- `serve [--host 127.0.0.1] [--port 8777] [--llm openai|fake] [--dataset ...] [--model ...]`
- `ask ... --json` prints the same payload as `/api/ask`
- `eval --ambiguous` adds the ambiguous set; `eval-retrieval --summaries on|off`

## 7. Acceptance tests

1. `/api/ask` with the fake LLM returns the full payload for a golden question; masked columns and warnings present
   where expected; the CLI `ask --json` returns the same payload.
2. Chart: each result shape maps to its chart type or none; the option JSON is valid ECharts input (schema-checked).
3. Number guard: invented, mis-rounded and reformatted numbers are caught; correct Turkish formats pass; the
   template fallback is used after one failed retry.
4. Clarification: the fake LLM calling `ask_clarification` yields `needs_clarification`; a follow-up with a chosen
   option is answered; eval metrics computed correctly on a fake run.
5. Warnings: fan-out, empty, all-NULL and truncated cases each produce their warning.
6. Export: CSV (BOM, `;`) and XLSX re-run through the executor; PII stays masked in both.
7. Rules API: invalid rule rejected with a message; a valid edit marks the index stale; rebuild clears it.
8. Retrieval report includes recall@k with and without table summaries.
9. Frontend builds; vitest green; the visual review flows run against `serve --llm fake`.
10. Smoke: build-db, build-index --embed fake, eval --llm fake --ambiguous, serve --llm fake + GET /api/health
    (smokes for later milestones tagged with "from").

## 8. Milestones

- **M14 - API + evidence:** FastAPI app, `/api/ask` on the existing agent, saved/history, export, warnings
  (checks.py), `ask --json`, tests 1, 5, 6.
- **M15 - Report:** chart spec, narrate + number guard, rules API + index stale/rebuild, tests 2, 3, 7.
- **M16 - Clarification + eval + retrieval:** `ask_clarification`, follow-up flow, ambiguous set, new eval metrics,
  table summaries, PII group test, tests 4, 8.
- **M17 - Frontend:** React UI (answer card, chart, table, evidence, clarification, saved/history, rules screen,
  export), states, vitest, build into static, visual flows, test 9-10.

Keep it to **at most ~42 tasks**.

## 9. Open questions / risks

- sqlglot and the agent stay the only path to the DB; the API must not grow a shortcut.
- The number guard must not make answers useless: measure how often the template fallback is used in the eval.
- Clarification can be over-used by the model; the eval rule (clarify on a golden question = not answered) keeps it
  honest.
