# NL2SQL — Run 1

A measurement tool for one question: **can a local LLM write correct T-SQL over a Netsis-like
schema?** Ten golden Turkish questions run against a synthetic database through a read-only,
policy-guarded executor and are scored against golden SQL. The number in `report.md` is the
deliverable — this is the Phase 0 kill gate, not the product.

## Setup

Python 3.11. There is no install step: run everything as `python -m nl2sql` from the repo root.

```bash
uv sync                                # sqlglot, openai, pyodbc (+ pytest)
.venv\Scripts\python -m pytest -q      # full suite: no network, no model needed
```

## Three commands

```bash
python -m nl2sql build-db [--seed 42]              # data/test.db + db/mssql/build_test_db.sql
python -m nl2sql ask "Geçen ayın cirosu ne kadar?" [--llm openai|fake]
python -m nl2sql eval [--llm openai|fake] [--only Q03 Q04]
```

`build-db` comes first — it writes the SQLite file the other two read. `--llm fake` replays the
golden SQL instead of calling a model: the model-free path, and it scores 10/10 by construction.

- `ask` prints every step of the agent (✓/✗, tool, latency), the SQL it submitted and the result
  table. A policy reject shows its reason inline, so you can watch the guardrail work.
- `eval` prints one line per question as it finishes, writes the report, prints the score.

Exit codes: `0` the run completed (a low score is data, not a failure), `2` the database is
missing, `3` the endpoint answered nothing at all.

## Pointing at a model

The default endpoint is **Strata** — `http://127.0.0.1:8080/v1`, model id `strata`.

| Env var | Default | Notes |
| --- | --- | --- |
| `NL2SQL_LLM_BASE_URL` | `http://127.0.0.1:8080/v1` | OpenAI-compatible base URL, `/v1` included |
| `NL2SQL_LLM_MODEL` | `strata` | sent as the model id |
| `NL2SQL_LLM_API_KEY` | `local` | local servers ignore it; never commit a real key |
| `NL2SQL_BACKEND` | `sqlite` | `mssql` runs the same SQL against SQL Server |
| `NL2SQL_MSSQL_CONN` | — | ODBC connection string; required for `mssql` |

They are read at call time, so a one-off override needs no shell state:

```bash
NL2SQL_LLM_BASE_URL=http://127.0.0.1:8081/v1 NL2SQL_LLM_MODEL=qwen3.6-27b python -m nl2sql eval
```

On cmd.exe: `set NL2SQL_LLM_BASE_URL=http://127.0.0.1:8081/v1` before the command.

### llama.cpp serving a 27B

```bash
llama-server -m qwen3.6-27b-q4_k_m.gguf --host 127.0.0.1 --port 8081 \
  -c 32768 -ngl 99 --jinja
```

`--jinja` is not optional: without the chat template the server exposes no tool calling, and the
agent's three tools (`get_schema`, `run_sql`, `submit_sql`) never reach the model — every question
then ends `no_submission`. A Q4_K_M 27B is ~17 GB, so a 32 GB card carries it plus a 32K context;
the schema block is the bulk of the prompt, so dropping the context below 16K starts truncating it.

```bash
set NL2SQL_LLM_BASE_URL=http://127.0.0.1:8081/v1
set NL2SQL_LLM_MODEL=qwen3.6-27b
python -m nl2sql eval
```

## Reading the report

`eval_out/latest/report.md` — the same pair also lands in a timestamped `eval_out/<run>/`, so
`latest` is what the next run diffs against. In order:

1. **Skor** `7/10` and the decision that score implies (continue / rebuild / rethink).
2. **Bağlam** — peak and median prompt tokens per question: how much of the window the schema and
   the tool results eat, which is the number that decides whether a bigger model fits at all.
3. **Önceki koşuya göre** — score delta versus the previous run and which questions flipped
   (`Q04 ✗ wrong_result → ✓ pass`). Absent on the first run.
4. One table row per question, then a section each with the question, the failure reason, the
   submitted SQL and the golden SQL side by side.

Outcomes: `pass`, `wrong_result` (SQL ran, different rows), `sql_error`, `policy_reject`,
`transpile_error`, `no_submission`, `timeout`, `llm_error`.

`data/`, `eval_out/` and `logs/` are gitignored; `logs/audit.jsonl` records every query with its
outcome and row count, never the rows. Model SQL only ever runs read-only — through the policy,
with a `TOP` cap, and there is no code path around either.
