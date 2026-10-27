Türkçe: [README.tr.md](README.tr.md)

# Bilgin — Run 1

Product name **Bilgin**; the package and the CLI stay `nl2sql`.

A measurement tool for one question: **can a local LLM write correct T-SQL over an ERP-like
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

1. **Score** (`Skor`) `7/10` and the decision that score implies (continue / rebuild / rethink).
2. **Context** (`Bağlam`) — peak and median prompt tokens per question: how much of the window the
   schema and the tool results eat, which is the number that decides whether a bigger model fits at
   all.
3. **Versus the previous run** (`Önceki koşuya göre`) — score delta versus the previous run and which
   questions flipped (`Q04 ✗ wrong_result → ✓ pass`). Absent on the first run.
4. One table row per question, then a section each with the question, the failure reason, the
   submitted SQL and the golden SQL side by side.

Outcomes: `pass`, `wrong_result` (SQL ran, different rows), `sql_error`, `policy_reject`,
`transpile_error`, `no_submission`, `timeout`, `llm_error`.

`data/`, `eval_out/` and `logs/` are gitignored; `logs/audit.jsonl` records every query with its
outcome and row count, never the rows. Model SQL only ever runs read-only — through the policy,
with a `TOP` cap, and there is no code path around either.

---

# Run 2 — Retrieval, join graph, and the A/B that decides whether RAG stays

Run 2 grows the world to 83 tables (the Run 1 stream, six new data tables, 67 distractors), 40 golden
questions and 15 business rules, and adds a retrieval path: an index over the schema and the rules,
plus a join graph built from foreign keys and an ERP column profile. The phase rule is **no measured
gain → no RAG**, so the deliverable is not the retriever — it is `eval --compare`.

## Commands

```bash
python -m nl2sql build-db [--seed 42]                       # data/test.db + db/mssql/build_test_db.sql
python -m nl2sql build-index [--embed openai|fake[:dim]] [--embed-model bge-m3]   # index/ + meta.json
python -m nl2sql eval-retrieval [--embed openai|fake[:dim]] [--embed-model bge-m3] [--k 5]
python -m nl2sql ask "..." [--llm openai|fake] [--mode full|full_rules|rag]
python -m nl2sql eval [--llm openai|fake] [--mode full|full_rules|rag] [--tag archive needs_rule]
                      [--only Q03 Q04] [--compare] [--fresh]
```

`build-index` folds `schema/schema.json` and `schema/rules.json` into one document per table and one
per rule, embeds them and writes `index/` (gitignored) together with the content hash of the schema
and rules it was built from. `ask` and `eval` **refuse** a stale index — exit 2, `İndeks eski` —
instead of rebuilding it silently: searching with old vectors turns a table the index never had into
what looks like a model error. `--embed fake` builds the vectors from a deterministic hashed
bag-of-words (dim 256), so retrieval is measurable with no server and no model at all.

`eval-retrieval` touches neither the database nor the index on disk: it builds the index in memory and
prints recall@k per golden question for the three methods (`hybrid`, `bm25`, `dense`), then the means
per method and per tag. The criterion is the golden line's `requires_tables` — did the tool *see* the
table inside the first `k`, order irrelevant. `--k` sets that window (default 5). Report:
`eval_out/retrieval/latest/report.md`.

## The embedding server

The default is an OpenAI-compatible `/v1/embeddings` endpoint on **`http://127.0.0.1:8891/v1`** — a
second llama.cpp instance, so the chat model on 8080 and the embedder on 8891 never share a server:

```bash
llama-server -m embeddinggemma-300m-q4_k_m.gguf --host 127.0.0.1 --port 8891 --embedding
```

| Env var | Default | Notes |
| --- | --- | --- |
| `NL2SQL_EMBED_BASE_URL` | `http://127.0.0.1:8891/v1` | OpenAI-compatible base URL, `/v1` included |
| `NL2SQL_EMBED_MODEL` | `embeddinggemma` | sent as the model id |
| `NL2SQL_EMBED_API_KEY` | `local` | local servers ignore it; never commit a real key |

`meta.json` records the embedder id (`openai:embeddinggemma`, `fake:256`) and the query side builds
its embedder from that record, which is why `ask` and `eval` take no `--embed`: an index and a query
cannot end up in different vector spaces by accident. **Changing the model means re-running
`build-index`.** A server that is not listening exits 3 and names the URL it tried.

### EmbeddingGemma vs bge-m3 (license)

The default `embeddinggemma` is ~300M, multilingual (Turkish included) and light enough to sit next to
a 27B chat model, but it ships under the **Gemma Terms of Use** — Google's own terms, not MIT or
Apache — so read them before putting it in anything commercial. `bge-m3` (BAAI) is **MIT**, 1024-dim
and 8K context, and it is what you ship if the Gemma terms are a problem.

### Measuring bge-m3 against the default

bge-m3 is bigger than a 300M embedder and the GPU is already carrying the chat model, so run it **on
CPU on its own port** — retrieval is measured, not served, and a few seconds per document is fine
when the whole index is built once:

```bash
llama-server -m bge-m3-Q8_0.gguf --host 127.0.0.1 --port 8892 --embedding --cpu
set NL2SQL_EMBED_BASE_URL=http://127.0.0.1:8892/v1
python -m nl2sql build-index --embed-model bge-m3
python -m nl2sql eval-retrieval --embed-model bge-m3
```

`--embed-model` is the model id sent to the endpoint, so the two models can be compared without
touching `NL2SQL_EMBED_MODEL`; `meta.json` records the id it was built with (`openai:bge-m3`), which
is how `ask`/`eval` know they are not querying a different vector space than they indexed. The
numbers themselves are read by hand after the run: `eval-retrieval` prints recall@k per golden
question and the means per method and per tag, and its report lands in `eval_out/retrieval/latest`.
Compare the recall before committing to either: the license decides what you may ship, the recall
decides whether retrieval earns its place at all.

## Three modes, three context budgets

| Mode | What the system prompt carries | Tools |
| --- | --- | --- |
| `full` | every table in full detail — `doc.full_text`, the ~30K-token schema | `get_schema`, `run_sql`, `submit_sql` |
| `full_rules` | `full` plus all 15 business rules written out | same |
| `rag` | table **names** grouped by module, plus a search-first rule | `search_schema`, `get_table_details`, `find_join_path`, `search_rules`, `sample_values`, `run_sql`, `submit_sql` |

`rag` buys the small prompt with tool calls — 12 per question against 8 — and with latency, which is
why the comparison reports context *and* score per mode rather than one number. `--mode` picks which
of the three a run uses; `ask` defaults to `rag` when a fresh index exists and to `full` (with a note
line) when it does not, `eval` defaults to `full`. `--llm` picks the client — `fake` replays the
golden SQL instead of calling a model — and `--seed` still pins the synthetic world `build-db` writes.
`--only` narrows a run
to specific ids, and the run's fingerprint records exactly which questions ran, so a shortened run is
never mistaken for a full one later.

## Running the A/B

```bash
python -m nl2sql eval --mode rag
python -m nl2sql eval --mode full_rules --tag archive needs_rule
python -m nl2sql eval --compare            # all three modes, one report
python -m nl2sql eval --compare --fresh    # rerun the modes a reuse would have kept
```

Each mode writes to its own `eval_out/<mode>/`, so the run-to-run delta only ever compares like with
like. `--compare` runs the three modes over the same questions and writes one report under
`eval_out/compare/`; a mode whose `latest` carries the fingerprint of the run about to happen is
reused instead of re-run and prints `(önceki koşu)`. `--fresh` ignores that shortcut. A `--tag` no
question carries is an error, not an empty run: `Bu etiketle soru yok: <tag>`, exit 2.

### Reading the compare report

`eval_out/compare/latest/report.md` opens with the model, the question count and the schema token
estimate (what `full` pays per question before it does anything), then one row per mode — score,
peak/median prompt tokens, mean/max tool calls, mean/total seconds, reused or not — then a tag × mode
score table, then the questions whose outcome differs between modes, then the verdict in bold.

The verdict is arithmetic, not judgment: RAG stays iff `rag.passed >= full_rules.passed` **and**
`rag.max_prompt_tokens < full_rules.max_prompt_tokens`. Whichever condition fails is the one the line
names, with both numbers:

```
Karar: RAG kalır — rag 31/40 ≥ full_rules 30/40 ve tepe bağlam 6.2K < 28.4K token.
Karar: RAG yok — rag 27/40 < full_rules 30/40.
```

`full` is the reference row, never a condition — it is what Run 1 measured. Questions and tool limits
are never tuned to flip this line.

## Reviewing what the questions actually ask

```bash
python -m eval.review [--out eval/REVIEW.md]
```

A score says the SQL matched the golden SQL; only a person can say the golden SQL matches the
business *intent*. `eval/REVIEW.md` prints every golden question with its tags, rules, tables, golden
SQL and the first five rows of the pure-Python reference answer — computed from
`eval.reference.REFERENCES`, never from the database — each under an unchecked `- [ ] niyet doğru`
box. Regenerate it whenever `eval/golden.jsonl` changes.

---

# Run 3 — A schema from the outside, and personal data that never leaves the executor

Run 3 does two things. It gets a customer's schema into the system without anyone hand-writing
`schema/schema.json` — an Excel map, a live database, or both — and it makes the tool safe to point at a
real ERP database: every value that traces back to a column marked as personal data is masked inside the
executor, before the model, the screen or the eval ever sees a row.

## Commands

```bash
python -m nl2sql import-map HARITA.xlsx [--llm openai|fake] [--accept] [--mapping m.json]
                      [--out schema/imported.json]
python -m nl2sql introspect [--out schema/skeleton.json] [--sample]
python -m nl2sql diff-map --excel schema/imported.json (--db | --db-schema schema/skeleton.json)
python -m nl2sql merge-map --excel schema/imported.json (--db | --db-schema schema/skeleton.json)
                      [--out schema/merged.json]
python -m nl2sql make-login-script [--login nl2sql_ro]
python -m nl2sql eval   [--llm openai|fake] [--schema DOSYA|full|skeleton] [--mode ...]
                      [--compare [--repeat N]]
python -m nl2sql ask "..." [--mode auto|full|full_rules|rag]      # auto is the default now
```

`build-db`, `build-index` and `eval-retrieval` are unchanged from Run 2. The generated files
(`schema/mapping.<name>.json`, `schema/imported.json`, `schema/skeleton.json`, `schema/diff.json|md`,
`db/mssql/readonly_login.sql`) are gitignored or carry a password placeholder, so none of them leaks
anything by being on disk.

## Getting a customer's schema in

One rule runs through all four commands: **the LLM proposes, code converts.** The model sees sheet names,
headers and twenty preview rows — never the rows themselves — and the conversion of every row after that is
plain Python over the whole workbook.

`import-map` is two phases on purpose. Without `--accept` it prints the mapping proposal (sheet, header row,
which field each column was read as), writes `schema/mapping.<name>.json` and stops, so you can edit it;
where the model and the deterministic header dictionary (`profiles/excel_headers.json`) disagree, the line
is printed as `⚠ uyuşmuyor:` rather than resolved silently. With `--accept` the mapping — the one just
written, or a corrected one via `--mapping` — is applied to every row and the canonical schema lands in
`--out`. An unreachable model is not an error here: the dictionary maps the workbook alone and says so.

`introspect` reads the database itself (SQLite `PRAGMA`, SQL Server `INFORMATION_SCHEMA` + `sys.foreign_keys`)
and writes a skeleton: names, types, nullability, foreign keys. Empty descriptions are not a gap — the
skeleton carries structure, the Excel map carries meaning. `--sample` adds up to five distinct values per
short text column, and those queries go through the same executor as model SQL, so they are policy-checked
and audited too.

`diff-map` answers "does the map describe this database?" — Excel-only and DB-only tables and columns, type
mismatches, foreign keys the map claims that the DB does not have — as `schema/diff.json` plus a readable
`schema/diff.md`. `merge-map` produces the schema both sides agree on: the database decides existence,
types, nullability and keys; the Excel decides description, coded values and module.

`eval --schema <path|full|skeleton>` measures the schema it names — allowlist, prompt text, join graph and
index signature all come from that file — prints `Şema: <path> (<hash8>)` before the live lines and records
path and hash in `report.json`. That is what makes "hand-written schema vs skeleton-only" a measurement
rather than two incomparable runs, and it keeps the Run 2 refusal: an index built from a different schema is
rejected, not silently rebuilt.

## PII: eight classes, one choke point

A schema column may carry `pii`: `tckn`, `vkn`, `iban`, `phone`, `email`, `address`, `salary`,
`person_name`. Nothing else in the system decides what happens to it — masking lives **inside the
executor, after the backend and before the Result is returned**, so the agent's tools, `ask`'s table and
the eval all read the same masked rows. There is no second place to forget.

Each class keeps the smallest part that still lets a reader recognise the row, and none of it is
reversible:

| Class | What you see |
| --- | --- |
| `tckn`, `vkn` | `*******1234` |
| `iban` | `TR** **** **** **** 1234` |
| `phone` | `*** ** 456` |
| `email` | `e***@ornek.com` |
| `address` | the city — the first segment only |
| `person_name` | initials, `E. K.` |
| `salary` | `***` |

Which output columns to mask is decided by tracing each one back to its source columns with sqlglot
lineage, so an alias, a CTE rename, a `CAST`/`CONVERT`, a `SUBSTRING`, a `CASE`, a `UNION` into a
non-personal column position, a scalar subquery or a derived table does not lose the mark. `COUNT` and
`COUNT(DISTINCT ...)` are whitelisted — a count leaks no value — while `MAX` and `AVG` over a salary are
masked, because the aggregate *is* the value. A column whose lineage cannot be resolved is masked in full:
fail closed, and the CLI prints how many columns were hidden that way.

The other half is the filter. `WHERE TCKN LIKE '1%'` returns no personal value and still answers a personal
question, so a marked column in `WHERE`, `JOIN ON`, `GROUP BY` or `ORDER BY` is rejected outright, with the
column named in the reason. `config.PII_FILTER` holds the classes that are filtered this way; drop a class
from the set and only the masking still applies to it.

`Result.masked_columns` carries the masked names, `ask` prints `Maskelendi: TCKN, TELEFON` under the table,
and `logs/audit.jsonl` records the names — never the values. `sample_values` and `introspect --sample`
inherit all of it because they go through the same door.

## Two layers, and the database is the first one

The Python policy is **not** the boundary. It reads the table names a query mentions, and a VIEW, a SYNONYM
or a table-valued function can wrap a table that is not on the allowlist — the query only ever names the
wrapper, so the parser cannot see through it. The durable control is a database permission, and
`make-login-script` generates it: `db/mssql/readonly_login.sql` creates the login with the password
placeholder `__DEGISTIR__` (never a real secret, which is why the file can live in the repo), adds
`db_datareader`, then takes it back — `DENY SELECT` for every table outside the schema allowlist,
column-level `DENY SELECT` for every personal column, `DENY VIEW DEFINITION` and `DENY EXECUTE`. DENY beats
GRANT, so the login can read the allowed tables and cannot see a personal column at all.

The sqlglot policy is the second layer: it catches a mistake before a query is sent, caps rows with `TOP`,
refuses multi-statement batches and `sys`/`INFORMATION_SCHEMA` reads, and rejects the filter side channels
above. Two layers because they fail differently — the login script is what limits damage if the parser is
fooled, and the parser is what tells the model *why* its query was wrong.

## Real-data checklist

Against a **copy** of the customer's ERP database. Never the live one, and never with the account you use
to administer it.

1. Restore the copy, and create the read-only login **first**: `python -m nl2sql make-login-script`,
   replace `__DEGISTIR__` with a real password, run the script in the copy's database context. Windows auth
   on this machine is sysadmin — it is never used, because a login that can do anything makes every guardrail
   above decorative.
2. Point the tool at it: `NL2SQL_BACKEND=mssql` and `NL2SQL_MSSQL_CONN` with that login and
   `ApplicationIntent=ReadOnly`.
3. `introspect --sample` → `schema/skeleton.json`. This is the first step precisely because it needs no
   schema: the skeleton is introspected from tables the hand-written `schema.json` has never heard of.
4. `import-map customer.xlsx` → edit `schema/mapping.customer.json` if a header was read wrong →
   `import-map customer.xlsx --accept --mapping ...` → `schema/imported.json`.
5. `diff-map --excel schema/imported.json --db` → read `schema/diff.md`; then
   `merge-map --excel schema/imported.json --db --out schema/merged.json`.
6. `build-index` from the merged schema, then `eval --schema schema/merged.json --llm fake` (scores the
   pipeline with no model), then the same without `--llm fake`, then `ask`.

Nothing in the test suite touches a real server. The SQL Server query texts are parse-tested and the
rows-to-skeleton conversion is a pure function over hand-built rows, so `pyodbc` is never connected; every
test that executes SQL runs it against a SQLite file that `build-db` wrote in a temp directory.

<!-- ASSUMPTION: --mode auto (R3-10) and --repeat (R3-11) are Run 3 surface documented here at the M9
close; they ship in M10 (T107, T108), which is why the Run 3 command list already names them. -->

## `--mode auto` and `--repeat`

`ask` now defaults to `--mode auto`: the full_rules prompt is measured, and a schema small enough to fit
`config.AUTO_FULL_MAX_TOKENS` (12000 by default — a 16–24K context box) runs with every rule written out,
while a bigger one falls back to `rag`, or to `full` with the Run 2 note when no fresh index exists. The
resolved mode and the estimate are printed and land in the audit line, so a run says which budget it paid.
`eval` refuses `auto`: a measurement has to name its mode.

`eval --compare --repeat N` runs each mode N times and reports mean, min and max per mode and per tag, plus
how many questions flipped between repeats of the *same* mode. The verdict compares means and adds
`fark gürültü içinde` when two mode means differ by less than the spread of either — a one-run difference on
a local model is not a result, and Run 2's rag-vs-full_rules tie is exactly the kind of number this
measures.

---

# Run 4 — A public dataset, and what a 27B in a 16K window can still answer

Run 4 makes the thing being measured swappable. Until now one dataset — the synthetic ERP-like
world — and one endpoint were wired through every command, so "does a 27B dense model in a 16–24K
context still answer?" could not be asked cleanly, and no number could be reproduced off this machine.
Two things change: a **dataset** is now a folder selected by `--dataset`, and a **model** is a profile
selected by `--model`, carrying its own context budget the agent never exceeds. The deliverable is
`eval --compare --models` — one table, model × mode, on a public database anyone can restore and on the
private set.

## Datasets: `--dataset` on every command

```bash
python -m nl2sql build-db          --dataset synthetic_erp|wwi [--seed 42]
python -m nl2sql build-index       --dataset ... [--embed openai|fake[:dim]]
python -m nl2sql eval-retrieval    --dataset ... [--embed ...] [--k 5]
python -m nl2sql ask "..."         --dataset ... [--model PROFILE] [--mode ...]
python -m nl2sql eval              --dataset ... [--model PROFILE] [--mode ...] [--compare ...]
python -m nl2sql make-login-script --dataset wwi [--login nl2sql_ro]
```

A dataset is a folder `datasets/<name>/` with a `dataset.json` (display name, dialect, connection kind,
default schema, the file names, the builder and reference entry points, and where its outputs land)
beside `schema.json`, `rules.json`, `profile.json`, `golden.jsonl`, `traps.jsonl`, `builder.py` and
`reference.py`. Two ship:

| `--dataset` | What it is | Outputs |
| --- | --- | --- |
| `synthetic_erp` (default) | the private ERP-like development set — Run 1–3 content, moved by path only | `data/test.db`, `index/`, `eval_out/` |
| `wwi` | WideWorldImporters, Microsoft's public sample (sales, purchasing, stock, invoices) | `data/wwi.db`, `index/wwi/`, `eval_out/wwi/` |

`--dataset` is optional everywhere and defaults to `synthetic_erp`, so every Run 1–3 command runs
unchanged. When it *is* given, nothing about that run comes from a config constant: the database, the
index, the eval output folder and the schema all come from the dataset's own `dataset.json`, and the
index refuses to serve a schema it was not built from.

## WideWorldImporters, the public set

The point of a public dataset is a number someone else can reproduce. The tests never touch a real
server — `--dataset wwi` runs end to end against a small seeded SQLite fixture that copies WWI's table
and column **names** (`Sales.Orders`, `Warehouse.StockItems`, `Application.People`) and its traps
(orders that were never invoiced, credit notes, back-orders, NULL delivery dates), never its rows. To
measure against the real database, restore it by hand:

1. Download `WideWorldImporters-Full.bak` from Microsoft's **`sql-server-samples`** GitHub release and
   restore it on the local SQL Server Express. The sample is published under the **MIT** licence — but
   re-check the licence on the release page before publishing anything derived from it.
2. Create the read-only login **first**, from the WWI schema's allowlist:
   `python -m nl2sql make-login-script --dataset wwi` → `db/mssql/readonly_login.sql`, with the
   `__DEGISTIR__` password placeholder replaced and run in the WWI database context. Windows auth on
   this machine is sysadmin and is **never** used — a login that can do anything makes every guardrail
   decorative.
3. Point the tool at it: `NL2SQL_BACKEND=mssql` and `NL2SQL_MSSQL_CONN` carrying that login and
   `ApplicationIntent=ReadOnly`.
4. The schema here is written from Microsoft's public documentation, so the real restore may differ.
   `introspect --sample` then `diff-map` against the live database is the check, run by hand; fix the
   names there before trusting a score.

## Model profiles: `--model` and `config/models.json`

`config/models.json` maps a profile name to an endpoint, a model id, the **environment variable** that
holds its API key (never the key itself), a context budget in tokens and a max-output cap. Three ship:

| Profile | Endpoint | Key env | Budget |
| --- | --- | --- | --- |
| `strata` | `http://127.0.0.1:8080/v1` | — | 262144 (the whole 256K window) |
| `qwen27b-24k` | `http://127.0.0.1:8888/v1` | `UNSLOTH_API_KEY` | 24576 |
| `qwen27b-16k` | `http://127.0.0.1:8888/v1` | `UNSLOTH_API_KEY` | 16384 |

`--model PROFILE` on `ask` and `eval` picks one: the client comes from the profile's endpoint, the key
is read from its named variable, and its budget becomes the per-turn prompt cap. With no `--model` the
Run 3 endpoint and constants are used, unchanged. An unknown profile, or a profile whose key variable
is unset, is one clear line and exit 2 — never a silent fallback.

## The context budget: trim, then stop

Before **every** LLM call the agent estimates the prompt with the same token counter `--mode auto`
uses. Over budget it first trims old tool results — the latest stays, older long answers are cut and
marked — and only if that is still not enough does it stop with `context_overflow` instead of sending.
It never relies on the server to truncate silently. `context_overflow` is a **result**, not a crash: it
appears in the per-question outcome, in `report.json` and in the compare table, alongside the peak
prompt tokens actually sent and how many answers were trimmed. `--mode auto` reads the threshold from
the profile's budget, so the same schema is "small enough" for Strata and "too big" for a 16K 27B —
which is exactly the thing being measured.

## Comparing models: `eval --compare --models`

```bash
python -m nl2sql eval --compare --models strata,qwen27b-16k --modes full_rules,rag --dataset wwi --repeat 3
python -m nl2sql eval --compare --models fakeA,fakeB --modes full_rules,rag --dataset wwi --llm fake
```

Every model × mode (× repeat) combination runs over the same questions and lands in one report —
accuracy (mean/min/max over repeats), answered %, peak tokens against that model's budget, overflow
count, seconds per question, and per-tag scores. `--modes` defaults to `full_rules,rag`; `--repeat N`
turns each cell into a spread so a one-run difference on a local model is not mistaken for a result.
`--models` without `--compare` is the Run 2/3 mode comparison, untouched.

The GPU holds one heavy model at a time, so before each model's block the endpoint is pinged: a model
that is not up is **skipped** with a `⚠` line naming the URL, not failed — run Strata and the 27B one
after another and each fills its own row. `--llm fake` skips the ping and replays the golden SQL under
each profile's budget, so even a fake comparison shows which mode fits which window before any GPU is
touched. If every model is skipped, no report is written and the exit code is 3.

The report is `compare_<dataset>_<timestamp>.md` (and the matching `.json`) in the dataset's own eval
folder — `eval_out/wwi/compare_wwi_20261024-153000.md` for `--dataset wwi` — and its path is printed at
the end of the run.

---

# The 27B test (running it)

The question this whole run exists to answer: **does Qwen3.8-27B, in a 16K or 24K window, still write
correct T-SQL — and does `rag` save it where `full_rules` overflows?** One heavy model on the 32 GB
card at a time, so the two halves are run one after another by hand.

**Half 1 — the 27B (creative GPU mode).** Switch the GPU to **creative** mode (the AI Modes panel, or
`scripts\switch-mode.ps1` in `local-agent-stack`), which frees the card from Strata and starts Unsloth
Studio. Serve Qwen3.8-27B on `127.0.0.1:8888` with the context that matches the profile you are
measuring — `--context-length 16384` for `qwen27b-16k`, `--context-length 24576` for `qwen27b-24k` —
and `-np 1` (one slot: the budget is per sequence, and a second slot halves the window each request
gets). Then run the comparisons:

```bash
set UNSLOTH_API_KEY=...            # the key config/models.json names for the qwen27b profiles
python -m nl2sql eval --compare --models qwen27b-16k --modes full_rules,rag --dataset wwi --repeat 3
python -m nl2sql eval --compare --models qwen27b-16k --modes full_rules,rag --dataset synthetic_erp --repeat 3
```

**Half 2 — Strata (agent GPU mode).** Switch back to **agent** mode so Strata has the card again, then
run its block on the same two datasets:

```bash
python -m nl2sql eval --compare --models strata --modes full_rules,rag --dataset wwi --repeat 3
python -m nl2sql eval --compare --models strata --modes full_rules,rag --dataset synthetic_erp --repeat 3
```

Read the `compare_wwi_*.md` and `compare_synthetic_erp_*.md` reports side by side. A 27B that only
survives in `rag` — `full_rules` overflowing at 16K while `rag` answers — is a **result to report, not
a failure to hide**: it is the number that says what the customer-box model can carry.

---

# Run 5 — A Turkish web UI, and an answer that asks instead of guessing

Run 5 puts a screen on the measurement. A user types a question and gets a short written answer, a
chart when the data suits one, the result table, and the evidence behind it — or a clarification
question when the question is genuinely ambiguous. The core rule from Run 1 holds: **the LLM writes
SQL, words and clarification options — never a number that is not in the result.** Chart type and
chart data are chosen by code; every execution still goes through the executor (policy, read-only,
PII masking); nothing leaves the machine.

## `serve` — the UI on your own machine

```bash
python -m nl2sql serve [--host 127.0.0.1] [--port 8777] [--llm openai|fake] [--dataset ...] [--model ...]
```

`serve` binds **`127.0.0.1` only** — single user, **no auth**. That is deliberate: this is a
measurement tool run by one person on their own box, not a hosted service, so there is no login to
build and nothing to leak to the network. The address is not a free choice either — a `--host`
outside `127.0.0.1`/`localhost` is refused before anything starts listening, because a session that
can already see a dataset must never be reachable from outside the machine. The startup line names
which dataset, model and source are being served.

`serve --llm fake` runs the whole UI on the golden SQL with **no model at all** — the demo and review
path, so the screen can be opened and clicked through without Strata up.

## Building the UI

The frontend is React + Vite + ECharts in `web/`, built into `nl2sql/web/static` and served by
FastAPI at `/`. There is no separate web server in production — `serve` serves the built files:

```bash
npm --prefix web install
npm --prefix web run build          # -> nl2sql/web/static, served by `serve`
npm --prefix web run dev            # dev server with hot reload, talks to a running `serve`
```

For the dev loop, run `python -m nl2sql serve --llm fake` and `npm --prefix web run dev` side by side:
the Vite dev server proxies `/api` to the API, so you edit components without rebuilding.

## What an answer shows

Every part of the answer card is the **same payload** the API returns, so the screen and `ask --json`
never disagree:

- **Written answer** (`report/narrate.py`): the LLM gets the question, the column names, a few result
  rows and a list of **facts computed by code** (totals, top item, share %, change vs the previous
  period), and writes 1–3 sentences. A **number guard** then extracts every number in that text
  (Turkish formats: `1.234,56`, `%12`, `12,5 bin`) and accepts it only if it equals a result cell or a
  computed fact. A number that fails is retried once with the offenders named; if it still fails, a
  **deterministic template sentence** is shown instead. A confident wrong number is never shown.
- **Chart** (`report/chart.py`), chosen by code from the result shape — date + numeric → line, one
  category + numeric and ≤ 20 rows → bar, a share question with ≤ 6 positive parts → pie, two numerics
  → scatter only when asked, otherwise no chart. The LLM never picks the chart or its data.
- **Warnings** (`engine/checks.py`), by code: empty result, an all-NULL column, a join whose row count
  is far above its driving table (fan-out suspicion), a result truncated by `TOP`, masked columns.
  Shown in amber; nothing is silently "fixed".
- **"nasıl hesapladım"** (collapsible evidence): the SQL, `tables_used`, `rules_used`, the mode, the
  masked columns and the timings — the same evidence the audit line carries.

## Clarification instead of guessing

When a business term is undefined, or two readings change the number ("satış" gross vs net of
returns; cancelled invoices in or out), the agent may call `ask_clarification` instead of
`submit_sql`. Both the CLI and the API return `needs_clarification` with the question and its
options; the user's choice is sent back as a follow-up with the chosen reading, which is answered
normally:

```bash
python -m nl2sql ask "Geçen ay satış ne kadar?" --choice "İadeler düşülmüş net"
```

The prompt only asks when the readings give **different numbers** — a term a business rule already
defines is answered, not questioned.

## `ask --json`

```bash
python -m nl2sql ask "..." --json
```

prints the **same payload as `POST /api/ask`** — status, answer text, chart, columns, rows, SQL,
tables, rules, masked columns, warnings, timings — and nothing else on stdout, so the CLI and the web
API are one code path, not two. The exit code is the status: `answered` and `needs_clarification` are
success; anything else is non-zero.

## Export: CSV and Excel

The export buttons re-run the stored SQL through the executor (result rows are never stored) and
stream the file. CSV is written **UTF-8 with a BOM and a `;` separator** so Turkish Excel opens it
with the decimal comma intact; XLSX keeps numbers as number cells so a total can be re-summed. PII
stays masked in both, because the mask is computed inside the executor before the file is built.

## Saved questions and history

Saved questions live in a **local SQLite file, `data/bilgin.db`** — never in the analysed database —
while the sidebar history is read from **`logs/asks.jsonl`**, the file every ask is appended to. Both
hold the **question text and the SQL only, never result rows**: history is a list of what was asked,
not a copy of the data. The sidebar re-asks a saved question or a history entry with one click.

## Rules screen

The rules screen lists, adds, edits and deletes the business rules, and a valid edit writes straight
to the dataset's own **`datasets/<name>/rules.json`** (validated: id, term, synonyms, definition,
`sql_hint`, tables; an invalid rule is rejected with a per-field message). Because these are demo
files under git, **restore them with `git checkout -- datasets/<name>/rules.json`** after editing.

Any rule change makes the retrieval index **stale** — its content hash no longer matches — and the UI
shows an "İndeks eski" banner with an **"indeksi yeniden kur"** button (`POST /api/index/rebuild`),
which rebuilds it and clears the banner. A stale index is never searched silently: like the CLI, the
API refuses it rather than risk a table the index never had looking like a model error.

## Eval additions

```bash
python -m nl2sql eval --ambiguous [--llm fake]     # adds the ambiguous set, prints the metrics block
python -m nl2sql eval --narrate  [--llm fake]      # narrates each golden answer, counts the sources
python -m nl2sql eval-retrieval --summaries on|off # recall@k with and without table summaries
```

`eval --ambiguous` runs the golden questions plus the dataset's ambiguous set and, besides accuracy,
prints the metrics that describe *asking instead of guessing*: `Doğruluk` (accuracy),
`Cevaplanan %` (answered %), `Cevaplananlarda doğruluk` (accuracy among the answered), `Yanlış cevap
oranı` (wrong-answer rate), `Netleştirme kesinliği` (clarification precision) and `Netleştirme
duyarlılığı` (clarification recall). The scoring rule keeps the model honest: a clarification on a
golden question counts as **not answered**, so asking too often lowers the score.

`eval --narrate` runs each submitted golden answer back through the narrator and reports who wrote
each sentence — `llm`, `llm_retry`, `şablon` — and the **template rate** (`şablon oranı`): how often the
number guard rejected the LLM's text and fell back to the deterministic sentence. A high template
rate is a signal the guard is doing real work, not a failure.

`eval-retrieval --summaries on` adds one deterministic **table summary** document per table (its
description, key columns, the rules that use it, its join neighbours) alongside the column documents,
and reports recall@k with and without them. Whatever wins is kept; the eval is never tuned to
manufacture a gain. The measured result on both datasets is recorded in **`eval/SUMMARIES.md`**.

---

# Run 6 — A login, a role, and a database you introduce yourself

Run 6 puts the measurement box in front of a team: every page sits behind a login, an analyst sees the
data but not the levers, and a customer's database is introduced to Bilgin **from the screen** instead of
by hand. Nothing below changes the core rule — the LLM writes SQL and words, the executor runs it
read-only with the PII mask on, and no data leaves the machine. What changes is *who* may ask and *which*
database the answer runs against.

## Users and roles

Accounts live in the app's own SQLite file, **`data/bilgin.db`** — never in the analysed database — and
the only way to make one is the CLI, which is also the recovery path when a password is lost:

```bash
python -m nl2sql user add eren --role admin    # ilk hesap yönetici olmak zorunda
python -m nl2sql user list                     # Kullanıcı · Rol · Durum · Son giriş
python -m nl2sql user passwd eren              # parolayı değiştirir, eski oturumlar düşer
python -m nl2sql user set analist --role user  # rolü değiştirir
python -m nl2sql user set analist --deactivate # hesabı kapatır, silmez
```

The password is asked with **`getpass`** — twice, never echoed, never passed on a command line, so it
appears in no shell history and in no `ps` output. Two entries that disagree write nothing; a password
shorter than 10 characters is refused with the reason. A username is `a-z 0-9 _ . -`, 3–32 characters.
`user list` prints roles and last logins and **never a hash**. No CLI command asks you to log in first:
whoever holds the keyboard already owns the machine, and the CLI is what you have when the UI is locked.

`serve` refuses to listen while the user table is empty — it prints
`python -m nl2sql user add <ad> --role admin` and exits before any address is bound, so a box can never
be served open by accident.

**What each role may do** (enforced on the server, per route — hiding a menu item is not a permission):

| | `Kullanıcı` (user) | `Yönetici` (admin) |
|---|---|---|
| Ask, replay, export, tables, examples | ✓ | ✓ |
| Saved questions and history | own only | the whole dataset |
| Rules screen | read-only ("İş kurallarını yalnız yönetici değiştirebilir.") | add / edit / delete, rebuild index |
| Database map, dataset switch | no | ✓ |
| Users screen | no | ✓ |

History and saved questions are filtered by the logged-in name, so an analyst's sidebar is their own
questions; an admin sees everything the active dataset holds. The filter is on the read *and* the
download: an export of someone else's audit id simply does not exist for the searcher.

## Login and sessions

`POST /api/auth/login` answers with the user's name and role and sets the session in the
**`bilgin_oturum` cookie** — `HttpOnly`, `SameSite=Strict`, path `/`, **12 hours**
(`SESSION_HOURS`). The session key itself goes nowhere else: not in a response body, not in a log line,
not in the ask log.

- An unknown username and a wrong password give **the same sentence** — the login form is not a way to
  find out which accounts exist.
- **5 failures inside 15 minutes lock the account for 15 minutes** (HTTP 429); the lock is a count of
  recent attempts, so it expires on its own and no one has to reset it.
- An expired cookie makes any call answer 401; the UI drops back to the login card with
  "Oturumunuz sona erdi, lütfen yeniden giriş yapın." and returns to the page you were on after login.

The address rule from Run 5 stands: **`127.0.0.1` only, no TLS.** The login protects against the other
people who sit at this machine, not against the network — a `--host` outside loopback is still refused
before anything listens. Bilgin is not a hosted service and does not pretend to be one.

## The development bootstrap

For a demo or a test run with no user table yet, one environment variable opens the first admin:

```bash
NL2SQL_DEV_ADMIN_PASSWORD=<parola> python -m nl2sql serve --llm fake
```

It is read **only when the users table is empty**: it then creates `admin` with that password and prints
a warning that it happened. If any user exists it does nothing at all — it cannot overwrite a real
admin's password, and it never runs twice. **Never set it on a real install**: it skips the password
length check that `user add` applies, and a bootstrap admin with a variable-length password is not an
account you want to keep. Open the real first account with `user add <ad> --role admin` and leave the
variable unset.

## Introducing a new database to Bilgin

**The database map** (`#/harita`, admin only) is the screen where a new database becomes a dataset
Bilgin can ask questions about. It is three cards: download, fill in, upload.

**1 — Get the template.** *Download the blank template* gives `bilgin-veritabani-sablonu.xlsx`: the
`Nasıl doldurulur`, `Veri kümesi`, `Tablolar`, `Kolonlar` and `İş kuralları` sheets and a filled
`Örnek` page; Run 8 writes the same workbook in English when the language is `en`. Two shortcuts:

- **Fill it from the live database** (shown only when the served box has an SQL Server connection) reads the
  live catalogue and pre-fills *Tablolar* and *Kolonlar* with names, types, NULL-ability and references —
  you then add the descriptions, which is the part a catalogue cannot tell anyone. If the read fails
  (missing `VIEW DEFINITION` permission) you get the **blank** template and a one-line note, never a
  second login attempt and never a half-filled file.
- **Try the filled example** downloads a complete example (`ornek_fatura`) so the whole flow can be
  walked before a customer's data exists.

**2 — Fill it in.** Four columns decide what the model can do with a table; in the English template
they read `DESCRIPTION`, `VALUES`, `PERSONAL DATA`, `CLOSED` and `REFERENCE`:

- **`AÇIKLAMA` (description) matters most.** The model knows a table or a column *only* from the text
  you write there; an empty description means the retrieval finds it by name alone and the agent
  guesses at its meaning.
- **`DEĞERLER` (values)** carries coded values ("`G` giriş, `C` çıkış; `1` satış faturası …") — the
  difference between a correct `WHERE` and a plausible wrong one.
- **`KİŞİSEL VERİ` (personal data)** picks one of the personal-data classes; a marked column's value
  is masked in every answer, chart and export, because the mask is applied inside the executor.
- **`KAPALI = E` (closed)** keeps the column in the schema but out of every query (passwords, internal
  notes), and **`REFERANS` (reference)** is `Tablo.Kolon` or `Şema.Tablo.Kolon` — the join graph is
  built from it.

**3 — Check** (`Kontrol et`) uploads the file and shows a report without writing anything else: counts
of `Tablo`, `Kolon`, `Kişisel veri`, `Kapalı`, `Referans` and `Kural`, then **errors** with `Sayfa` /
`Satır` / `Kolon` / `Sorun`, then warnings (the first 20, "ve N tane daha"). An error blocks
**Create** and says `Önce hataları düzeltin.`; a warning never does — a table with no description is
worth asking about, not refusing the file.

**4 — Create** (`Oluştur`) creates `real_datasets/<name>/` — `dataset.json`, `schema.json`,
`rules.json`, `profile.json`, an empty `golden.jsonl`, a `real.py` stub and a generated
`readonly_login.sql` — and indexes it; the progress line runs `Yazılıyor → İndeks kuruluyor → Hazır`.
Then **`Bu veri kümesine geç`** switches the served session, and every screen that names a dataset
follows it: the header chip, the examples, the tables, the rules, the saved list and the history.

**5 — The SQL Server side.** A new SQL Server dataset needs a read-only login before it can answer. The
generated script is downloadable per dataset (`GET /api/datasets/<name>/login-script.sql`); it contains
**`__DEGISTIR__`** where the password goes — the file never carries a password, and the allowlist and the
denied PII columns are already in it. Run it on the server, then start Bilgin with that connection
string in **`NL2SQL_MSSQL_CONN`**. Switching to the dataset works without it and says so
("Bu küme SQL Server'a bağlı: salt okunur girişi kurun ve sunucuyu `NL2SQL_MSSQL_CONN` ile başlatın.")
rather than failing a question with a connection error.

## An upload never touches an existing dataset

Preview writes only under `data/map_previews/` and expires after 30 minutes; **apply creates a folder
that does not exist yet** — a name already used by a dataset is refused with `Bu ad zaten bir veri
kümesi` and no file anywhere is modified. The datasets under `datasets/` (the synthetic and WWI demo
sets) are never written by an upload, so a bad map cannot break the eval you are measuring with.

`real_datasets/*` is **git-ignored except `real_datasets/wwi_real/`**: a customer's schema, rules and
generated login script stay on the machine that produced them, and the one real dataset used for public
measurements stays in the repo.

---

# Run 7 — A question that leans on the answer before it

Run 7 turns a session into a conversation: a follow-up is understood against what was just answered,
the sidebar keeps the threads you had, and the same chains are measured — did the second question use
the right turn, and did it get the right number? The core rule is untouched: the LLM writes SQL and
words, the executor runs it read-only with the mask on, and every number in an answer still comes from
**this turn's** rows.

## Conversation: one question after another

A turn is one question and its answer; a conversation is the turns under one id. `Bunlardan kaç
taneydi?` after a list of customers works because the earlier turn is in front of the model again —
not because anything was guessed at.

**Bir takip sorusu neye yaslanabilir.** The model is offered the last `CONV_TURNS` (3) **answered**
turns of the conversation as a `## Önceki turlar` block appended to the single system message: per
turn its question, its SQL, its column names and its kept rows. A keyword hint under it names what
kind of refinement this is — a `sadece / yalnız` filter, a `karşılaştır / önceki yıl` comparison, an
`aylık / yıllık` period change, an `ilk N` top-N — and the model resolves `bu / bunlar / o müşteri /
aynı dönem / bunu / peki` from those turns. Two follow-ups never reach the model at all:

- **A chart-only turn** ("bunun grafiğini çizgi yap") reruns the previous turn's SQL through the
  executor and redraws it in the requested kind: zero model calls, one new audit line. A kind the
  result shape refuses says so (`Bu sonuç çizgi grafiğe uygun değil: …`) and shows the automatic
  chart instead.
- **An ambiguous entity** ("Bu müşteri kim?") while the kept rows hold several customers comes back as
  a clarification built from those rows — Run 5's clarification, one turn down the line. The chosen
  option runs the agent with that value fixed.

**The evidence line.** When an answer stands on an earlier turn, the card says which one, above
*"Nasıl hesapladım"* (`#context-line`): `Önceki cevaptan: <etiket> <değer> (<ad>)`, where the label is
the column's schema description and never its technical name, and the parenthesis is the other text
cell of the row carrying the value. A turn that only reused an earlier query says
`Önceki cevaptan: 2. turun sorgusu temel alındı.` That line is the model's own claim about which turn
and which value it used, and **code checks it**: every turn number must exist, the value must appear
in that turn's kept rows or SQL, and the column must be one of that turn's columns. A claim that fails
is dropped, the answer stands on its own with no evidence line, and the ask record carries
`context_dropped: <reason>`. Nothing in the claim can move a number — the narrator's allowed set is
still this turn's rows and facts, so an earlier turn's total is never repeated as if it were
recomputed.

**Ekranda.** The address becomes `#/c/<id>` the moment the first answer arrives, so a thread is a link
you can return to. Reloading it reads the stored turns and **runs no SQL**: an older turn shows its
sentence and its kept rows with "Tam tablo ve grafik için yeniden çalıştırın." and the replay button.
**New conversation** empties the thread and goes back to `#/` — the turns stay on the server, and the
sidebar (`#conversation-list`, above history) lists them by title, relative time and turn count, with
a delete that asks first. A conversation belongs to the user who started it and to the dataset it was
started on: an id that is someone else's, or from another dataset, answers `Konuşma bulunamadı.` —
the same sentence as an id that does not exist, so the screen is not a way to discover either. The id
is a random uuid hex precisely so that a `#/c/<id>` in a link is not guessable.

**CLI.**

```bash
python -m nl2sql ask "Eylül 2026 fatura sayısı?" --new                   # yeni konuşma açar
python -m nl2sql ask "Bunlardan kaç müşteri?" --conversation <id>        # devamını sorar
```

Both end with one line, `Konuşma: <id> · tur <n>`, which is what you paste into the next call, and
`--json` adds `conversation_id`, `turn` and `context` to the payload it already printed. The two flags
are mutually exclusive; a plain `ask` is still Run 6 — no conversation is opened and nothing is
written — and an unknown id is `Konuşma bulunamadı.` with exit code 2.

**Measurement: `eval --followups`.** A dataset may carry `followups.jsonl`: chains of 2–3 turns, each turn
with its golden SQL and the turns it is allowed to lean on (`uses_turns`). `--followups` runs them
after the golden questions, turn by turn through the same door the screen uses, with a throwaway
conversation store under `eval_out/<dataset>/followups/` — the real producer, not a copy of the loop:

| | |
|---|---|
| **Turn accuracy** (`turn_accuracy`) | the turn's result set equals its own golden SQL |
| **Chain accuracy** (`chain_accuracy`) | every turn of the chain is right |
| **Context accuracy** (`context_accuracy`) | the note's `uses_turns` equals the golden set — an empty set is correct for a turn that stood alone |

report.md gets an `Ardışık sorular` section with those three numbers and a table per chain, and the
console prints one line per chain plus a total. `--llm fake` replays the chains and must come out
100 % — it proves the wiring, not the model. The number worth watching is a real model's
**`tur doğruluğu`** in `full_rules` (target ≥ 80 %).

**Manual run on the real database.** `wwi_real`'s chains are written for the public sample database
and are measured on the real server **by hand** — never as an automated test, because the numbers they
check against live on a machine this repo does not own:

```bash
NL2SQL_BACKEND=mssql NL2SQL_MSSQL_CONN="<salt okunur giriş>" \
  python -m nl2sql eval --followups --dataset wwi_real --mode full_rules --model <model>
```

What a test *does* guarantee is that every turn's golden SQL passes the policy against that dataset's
allowlist, so the manual run measures the model rather than a broken chain.

**What a turn keeps.** Per turn the store keeps the question, the status, the answer sentence, the
column names, the row count, the computed facts, the chart kind, the context note and **at most
`CONV_KEEP_ROWS` (5) result rows** — the rows exactly as the executor returned them, i.e. already
masked, so a masked cell stays masked in the next turn's context too. No chart option, no export, no
row 6 and beyond: a full table is re-run from its SQL, never read back out of a conversation. A failed
turn stays in the thread but never enters a context block. Conversations live in the app's own SQLite
file, `data/bilgin.db`, never in the analysed database.

## The start screen and ready questions

`#/` is no longer an empty box: the screen is a board of cards, and a card is an **approved question
with its saved SQL** showing its last result — a number, a chart, a short table. The model never writes
a card: its SQL goes through the same policy and the same read-only executor as a typed question, the
sentence over it is the narrator speaking *this* run's rows, and no answer on the board shows the SQL
itself. Clicking a card opens that question as **turn 1 of a new conversation**, so the follow-up that
leans on it is the same Run 7 door.

**Business role.** A card belongs to one of the `BUSINESS_ROLES` (5) — `Satış`, `Satın alma`,
`Muhasebe`, `Yönetim`, `Genel` — or to `*`, which every role sees. The role is a field on the account, set where accounts are
made (`POST /api/users`, the users screen), and the board is the filter: an approved card of someone
else's role is not greyed out on your screen, it is not in your list at all, and opening or refreshing
it answers 404 — the same sentence as a card that does not exist, so the board is not a way to discover
other roles' questions. A user with no role gets `*` and their own cards.

**Approval from an answer.** A card is born from an answer, never from typed SQL: **`Hazır soru yap`** on an
answered card takes that question's own record and runs its SQL once more through the executor — if it
does not run, nothing is saved and the reason stays on the form. The ready-questions screen
(`#/hazir-sorular`, admin) is the same approval from the other side, on a row that is already waiting
there. Approval is the only thing that makes a row visible: an **`Onay bekliyor`** row exists in the
store and on that screen and is invisible on the board; an admin opening one there is a preview, and
says so.

**A personal card.** **`Panoma ekle`** on any answer pins it to your own board: no business role, no
approval, at most `PERSONAL_CARDS` (6) per dataset, and only you see or remove it. The filter is your
own name, so a pin built on someone else's answer record is a 404 rather than their card.

**Suggestions are born unapproved.** `Öneri iste` starts a background job that asks the model — through the same
agent, with the schema and the business rules in front of it — for questions this dataset answers well,
`SUGGEST_PER_ROLE` (2–4) per role, and the screen shows the job's progress line. Every suggestion is
stored **unapproved**: only the ones that actually answered got their SQL written, and none of them
reaches a board before an admin has looked at it and approved it.

**A settled screen.** A card's load is cached for `START_CACHE_S` (300) per dataset + card + SQL, so
ten people opening the board run one query, and re-approving a card's SQL retires its old load.
**`Yenile`** steps over the cache but not over the calendar: one card refreshes at most once per
`CARD_REFRESH_MIN_S` (30), and the 429 names the seconds left. A card whose query fails is one error
card in warning colours, and the other cards on the board are unaffected; on an admin's board that card
carries `SQL'i yeniden onayla`, which puts the question in the ask box.

**The seed: `ready_questions.json`.** A dataset may ship its board. The file in the dataset folder is
written to the store once, on the first `serve` that opens that dataset — the `ready_seeded` setting is
why a second start, or a card an admin deleted, does not bring them back. Seeds are born approved (their
SQL is a golden line or a hand-checked constant) but they are only *checked* against the policy at that
moment, never run: a seed the guard refuses prints one line and drops, instead of becoming an error
card. `wwi_real` ships 14 seeds across the five roles, so a fresh server pointed at the real database
has something to show.

## Database connections

**Every dataset has its own connection.** A SQL Server dataset's connection is a row in the app's
own SQLite file (`data/bilgin.db`), filled in on a screen — `#/baglantilar`, admin — and the table
lists one row per SQL Server dataset with its own dot, **`Son başarılı`** and **`Son hata`**. Switching the
active dataset switches the database with it: the session's executor is rebuilt on the spot, no
restart, and a dataset with no row keeps answering from whatever it was built on.

**The password never comes back to the screen.** The password box says `değiştirmek için yazın` — an empty box **keeps**
the stored password, it never clears it. What is stored is a **DPAPI** blob (Windows, local-machine
scope, the dataset's own name as extra entropy), never the text. What that protects against is the file
leaving the machine: a copied or backed-up app database, a commit and a log line all carry bytes that
do not open on another computer, and one stolen blob cannot be replayed as another dataset's
connection. No answer ever carries a password or a connection string — a row speaks of the secret only
as `has_secret` — and a driver's own sentence, which quotes the connection string back, goes through
`connections.scrub` before anyone reads it.

**The environment variable wins.** `NL2SQL_MSSQL_CONN_<DATASET>` (the dataset name upper-cased) beats the
stored row, and the generic `NL2SQL_MSSQL_CONN` beats it while it names the database the whole process
is asking — the active dataset, on the mssql backend. Such a row carries an `Ortam değişkeninden`
badge and its form opens read-only:
`Bu bağlantı ortam değişkeninden geliyor; ekrandan değiştirilemez.`

**The server is asked before anything is saved.** Neither `Bağlantıyı test et` nor `Kaydet` trusts the form: the
login's own powers are read from the server — `sysadmin` and `db_owner` membership, the five
database-level powers (`INSERT`, `UPDATE`, `DELETE`, `ALTER`, `EXECUTE`) and whether a sample of the
map's own tables is readable. A login that writes or manages answers 409 with the report line by line
and **no row is written**; a table the login cannot read is reported, not refused, because a map may
name a table this database does not have. Every report ends with `Salt okunur giriş betiğini indir` —
the dataset's own generated `login-script.sql`, the same script the map screen offers, so the fix is
one download away.

**The status dot never holds a request waiting.** A background thread runs `SELECT 1` every `DB_CHECK_S` (60)
over the datasets somebody actually reads, and again right after a saved connection or a connection
error; what a screen shows is the last answer, never a new question. `#db-dot` (labelled `Veritabanı`)
is that answer for every logged-in user — `Bağlı` / `Erişilemiyor` / `Denenmedi` / `Kurulu değil` — and while
it is down a red `#db-banner` sits above the start, ask and thread screens. A user reads one generic
sentence and nothing else:

> `Veritabanına bağlanılamıyor, yöneticinize haber verin.`

**An admin additionally gets** the driver's own text (`message_admin`, scrubbed) and the address of the
screen that fixes it. A question asked while the state is down is refused before the model runs —
`db_down` — because an answer built on rows that never arrived is worse than no answer.

---

# Run 8 — The program speaks English too

Run 8 moves every sentence a person reads into a message catalog and resolves the language in one
place. The core rule does not change: the model writes SQL and words, every number in an answer comes
from **this turn's** rows, and neither the mask nor the policy has a language. What changes is that the
same measurement box answers an English question in English, writes its report in English and hands out
an English template.

## Choosing the language

| Where | Order |
| --- | --- |
| CLI | `--lang` (on every command; it also builds the parser in that language) → `NL2SQL_LANG` → `tr` |
| Web and API | the logged-in user's `lang` preference (`PUT /api/auth/me`) → `Accept-Language` → `NL2SQL_LANG` |
| The answer | the question's language: the payload's `answer_lang`; when the question says nothing, the screen language |

`config.LANGUAGES` (`tr`, `en`) and `config.DEFAULT_LANG` (`tr`) are the one list, and every sentence
lives in `nl2sql/i18n/tr.json` and `nl2sql/i18n/en.json` (`t(key, lang)`); the two files carry the same
key set, so a missing English sentence is a test failure, not an English screen with Turkish in it. The
shell picks it too:

```bash
NL2SQL_LANG=en python -m nl2sql eval --dataset wwi --llm fake
python -m nl2sql --lang en ask "How many invoices were issued in September 2026?" --dataset wwi
python -m nl2sql eval --help --lang en      # the help text is English as well
```

**The answer's language is the question's language**, separate from the screen's: a Turkish question
asked under `--lang en` is answered in Turkish, an English one in English. `--lang` names the frame —
headings, warnings, the report — and `answer_lang` names the sentence. Number formats follow the
language: `tr` writes `1.234,56` and `%12,3`, `en` writes `1,234.56` and `12.3%`, and the number guard
rejects the other language's format — an English answer never shows `1.234,56`, and its retry is
written in that language too.

## The English template

The template comes in the program's language: `python -m nl2sql template --lang en --out
bilgin-database-template.xlsx` writes the English sheets (`How to fill in`, `Dataset`, `Tables`,
`Columns`, `Business rules`, `Example`), English headers, `Y/N` validation lists and one filled English
example row; `--lang tr` writes today's Turkish workbook. The download follows the same rule —
`GET /api/schema-map/template.xlsx?lang=en` uses the requesting user's language.

**Either template imports in either language:** `profiles/excel_headers.json` knows the English headers
and sheet names too, `E/H` and `Y/N` both read as booleans, and the workbook carries its own language
in the hidden `_bilgin` sheet. On the rules sheet, `SYNONYMS (EN)` / `EŞ ANLAMLILAR (EN)` is the rule's
`synonyms_en` field.

## `synonyms_en`: an English question finds the same rule

A business rule's `synonyms_en` is optional (a list of non-empty strings, default `[]`). A term whose
Turkish synonyms are already written goes here when it has an English name as well. The index folds
both lists into the rule document's text, the BM25 query rewrite uses both, and the `full_rules` prompt
writes both — so an English question reaches the rule and the table it needs even on a dataset whose
descriptions were written in Turkish.

## `eval --lang en`

`--lang en` translates the golden set too: the dataset's `dataset.json` names it in `files.golden_en`
— `golden_en.jsonl` — and a dataset without one runs the Turkish questions. `wwi` and `wwi_real` each
carry two English sets: `golden_en.jsonl` (`E01..E26`, `source_id` pointing at the Turkish question,
while `sql`, `requires_tables`, `rules` and `tags` are copied as they are) and `followups_en.jsonl`
(chains translated turn by turn, SQL copied). The same order holds for `eval --followups --lang en`.

The report is written in English and `report.json` records `lang`. With `--llm fake`, `eval --lang en`
on `wwi` and on `wwi_real` has to come out 26/26 — what that measures is the wiring, not the model.

**The manual English run on the real database.** `wwi_real`'s English set is measured on the real
server by hand as well: the same two variables and the same read-only login as Run 7's manual step,
only the questions are English:

```bash
NL2SQL_BACKEND=mssql NL2SQL_MSSQL_CONN="<salt okunur giriş>" \
  python -m nl2sql eval --lang en --dataset wwi_real --llm openai --model <model>
```

What a test does guarantee stays the same: every question's golden SQL passes the policy against that
dataset's own allowlist, so the run measures the model rather than a broken chain.
