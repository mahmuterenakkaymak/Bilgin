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

---

# Run 2 — Retrieval, join graph, and the A/B that decides whether RAG stays

Run 2 grows the world to 83 tables (the Run 1 stream, six new data tables, 67 distractors), 40 golden
questions and 15 business rules, and adds a retrieval path: an index over the schema and the rules,
plus a join graph built from foreign keys and an ERP column profile. The phase rule is **no measured
gain → no RAG**, so the deliverable is not the retriever — it is `eval --compare`.

## Commands

```bash
python -m nl2sql build-db [--seed 42]                       # data/test.db + db/mssql/build_test_db.sql
python -m nl2sql build-index [--embed openai|fake]          # index/docs.json + vectors.json + meta.json
python -m nl2sql eval-retrieval [--embed openai|fake] [--k 5]
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
Apache — so read them before putting it in anything commercial. `bge-m3` (BAAI) is **MIT**, 1024-dim,
8K context and served exactly the same way, so the swap is two lines:

```bash
set NL2SQL_EMBED_MODEL=bge-m3
python -m nl2sql build-index && python -m nl2sql eval-retrieval
```

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
