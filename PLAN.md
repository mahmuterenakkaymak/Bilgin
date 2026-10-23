# PLAN - NL2SQL Run 1 (Phase 0 proof + CLI vertical slice)

Source: `PROJECT_BRIEF.md`. Measurement tool, not the product. Stack: Python 3.11, sqlglot, openai, pyodbc, pytest,
stdlib only.

## Architecture

```
nl2sql/schema_map/generator.py  generate(seed) -> Dataset (in-memory rows)
            |                         \
nl2sql/schema_map/build.py             eval/reference.py  (pure-Python truth, tests only)
  -> data/test.db (SQLite)
  -> db/mssql/build_test_db.sql (T-SQL)
schema/schema.json -> nl2sql/schema_map/doc.py (compact text, table detail, allowlist)

nl2sql/cli -> nl2sql/agent/loop.run_agent -> LLMClient (OpenAIClient | FakeLLM)
                    | tools: get_schema | run_sql | submit_sql
                    v
             nl2sql/engine/LocalExecutor.execute(sql, budget)
                 policy.check  ->  transpile (sqlite only)  ->  backend (SQLite ro | MSSQL ro)  ->  audit log
nl2sql/eval/runner -> agent per golden question -> executor -> compare vs golden result -> report.json/.md
```

## File layout

```
pyproject.toml                 pinned deps + pytest config (pythonpath = ".")
nl2sql/
  __main__.py                  -> cli.main()
  config.py                    all tunables at top; env readers
  schema_map/ generator.py build.py doc.py
  policy/     policy.py        check(sql, allowlist, top_n) -> PolicyResult
  engine/     result.py executor.py _sqlite.py _mssql.py audit.py
  agent/      llm.py fake.py tools.py prompt.py loop.py
  eval/       compare.py runner.py report.py
  cli/        main.py table.py
schema/schema.json             hand-written canonical schema doc
eval/ golden.jsonl traps.jsonl reference.py __init__.py
tests/ test_*.py  tests/data/malicious.jsonl
data/ (db, ignored)  db/mssql/  eval_out/ (ignored)  logs/ (ignored)
```

## Decisions

1. **Dataset = plain dicts.** `generate(seed)` returns `dict[table, list[dict]]`; no ORM. Both writers and the Python
   reference consume the same object, so DB and truth cannot drift.
2. **schema.json is the single source of column names and types.** Writers build DDL from it (SQLite type and T-SQL
   type per column); a test asserts generator row keys == schema columns, in order.
3. **Dates are ISO strings** (`'YYYY-MM-DD'`) in SQLite and `DATE` in T-SQL. Golden SQL uses half-open literal ranges
   (`TARIH >= '2026-09-01' AND TARIH < '2026-10-01'`) - portable through the transpile. Money is `REAL` / `DECIMAL(18,2)`.
4. **Coded values (fixed here so generator, schema doc and golden SQL agree):**
   - `TBLCASABIT.CARI_TIP`: `A` alıcı, `S` satıcı, `H` hem alıcı hem satıcı.
   - `TBLFATUIRS.FTIRSIP`: `1` satış faturası, `2` alış faturası, `3` satış iade faturası. `IPTAL`: `E`/`H`.
   - `TBLSTHAR.STHAR_GCKOD`: `G` giriş, `C` çıkış. `STHAR_HTUR`: `S` satış (C), `A` alış (G), `I` satış iadesi (G),
     `T` depo transferi (C+G pair, no invoice), `D` sayım/devir (G, no invoice). `FISNO` NULL when no invoice.
   - `TBLCAHAR.BA`: `B` borç, `A` alacak.
5. **Trap -> golden question map** (each trap changes the answer of its question; naive SQL in `eval/traps.jsonl`):

   | Q | Shape | Trap (naive SQL) |
   |---|---|---|
   | Q01 | simple filter: Ankara'daki alıcı cariler | - |
   | Q02 | top-5 products by Sep qty sold (ordered) | multi-warehouse (naive groups by depot) |
   | Q03 | "geçen ay" (Aug) net revenue, SUM(qty*STHAR_NF) | several price lines (naive qty*card price) |
   | Q04 | 3-table join: Sep invoice total per plasiyer | cancelled (naive ignores IPTAL) |
   | Q05 | Aug net qty per product, returns subtracted | returns (naive ignores HTUR I) |
   | Q06 | Jul total of invoices that have lines | fan-out (naive SUM(GENELTOPLAM) after line join) |
   | Q07 | total G qty per depot | movements without invoice (naive INNER JOIN invoices) |
   | Q08 | purchase total per supplier cari | buyer+seller (naive `CARI_TIP='S'` misses `H`) |
   | Q09 | order lines with no delivery date, per cari | NULL dates (naive COUNT(col)) |
   | Q10 | HAVING: products with return ratio > 10% | coded G/C + returns |
6. **Policy is parse-tree based** (sqlglot `read="tsql"`). Allowlist = upper-cased table names from schema.json.
   CTE names are collected per scope; a reference is a "real table" unless it resolves to a CTE in scope; real table
   names are always checked, so a CTE named `TBLSTHAR` wrapping `sys.objects` still fails on `sys.objects`.
   `TOP n` injected on the outermost SELECT; a top-level UNION is wrapped as `SELECT TOP n * FROM (...) AS _q`.
7. **Executor owns the policy.** `LocalExecutor.execute` is the only public entry; backends are private modules
   (`_sqlite`, `_mssql`) with no policy-free public method. SQLite: `file:...?mode=ro` URI, timeout via
   `set_progress_handler`. MSSQL: pyodbc imported lazily, conn string only from `NL2SQL_MSSQL_CONN`.
8. **Two budgets.** Model sees `Budget(max_rows=50)`; eval comparison uses `Budget(max_rows=100000)` for both golden and
   predicted SQL.
9. **Paths are parameters.** Every function that touches disk takes the path as an argument defaulting to config, so
   tests use `tmp_path`, never monkeypatched globals.
10. **LLM abstraction:** `LLMClient.chat(messages, tools) -> ChatResponse`; `OpenAIClient` and `FakeLLM` implement it.
    Unreachable / HTTP errors raise `LLMError`; the loop turns it into outcome `llm_error`.
11. **Fake LLM for `eval --llm fake`** replays get_schema -> run_sql(golden) -> submit_sql(golden) => 10/10. For `ask`
    it replays golden if the question text matches a golden question, else a fixed `TBLSTSABIT` query.
12. **CLI output is UTF-8** (`sys.stdout.reconfigure(encoding="utf-8")`) - Turkish labels and ✓/✗ on Windows consoles.
13. **Eval exit code** = 0 when the run completed (score is data, not failure); non-zero only on crash / missing DB.
14. No `visual.json`: the product has no screens in Run 1.

## Contracts

| Shape | Producer -> Consumer | Fields (optional = default) |
|---|---|---|
| `Dataset` | generator -> build, reference, traps tests | `dict[str, list[dict]]`; keys = schema.json table names; row keys = schema columns in order; values `int/float/str/None`; dates ISO str |
| schema doc | `schema/schema.json` -> doc.py, build.py, policy allowlist | `{"tables":[{"name","description","module","columns":[{"name","type"(T-SQL),"description","fk"=null ("TABLE.COL"),"values"={} (code->meaning),"nullable"=true}]}]}` |
| golden line | `eval/golden.jsonl` -> reference tests, runner, FakeLLM | `{"id":"Q01","question","sql","ordered"=false,"trap"="","notes"="","review"="pending"}` |
| trap line | `eval/traps.jsonl` -> trap tests | `{"trap","qid","naive_sql"}` |
| reference | `eval/reference.py` -> tests | `REFERENCES: dict[qid, Callable[[Dataset], list[tuple]]]`; column order = golden SQL select order |
| `PolicyResult` | policy -> executor | `ok: bool`, `sql: str|None` (rewritten T-SQL, TOP injected), `reason: str|None` (short, model-readable), `tables: set[str]`=empty |
| `Budget` | caller -> executor | `max_rows: int = 50`, `timeout_s: float = config.QUERY_TIMEOUT_S` |
| `Result` | executor -> tools, runner, CLI | `columns: list[str]`, `rows: list[tuple]` (≤ max_rows), `row_count: int` (before truncation), `truncated: bool=False`, `elapsed_ms: float`, `error: ExecError|None=None` |
| `ExecError` | executor -> tools, runner | `kind: "policy"|"transpile"|"sql"|"timeout"`, `message: str` |
| audit entry | executor -> `logs/audit.jsonl` | `{"ts","source" ("ask"|qid),"sql","elapsed_ms","row_count","outcome" ("ok"|error kind)}` - never rows |
| `ToolCall` | LLMClient -> loop | `id: str`, `name: str`, `arguments: dict` (invalid JSON -> `{}` + `parse_error`) |
| `ChatResponse` | LLMClient -> loop | `content: str=""` (think stripped), `tool_calls: list[ToolCall]=[]`, `prompt_tokens: int=0`, `completion_tokens: int=0`, `latency_ms: float=0` |
| `Step` | loop -> CLI, report | `n, tool, args, summary, ok: bool, prompt_tokens, completion_tokens, latency_ms` |
| `AgentRun` | loop -> runner, CLI | `question, steps: list[Step], submitted_sql: str|None, status: "submitted"|"no_submission"|"timeout"|"llm_error", stop_reason: str="", max_prompt_tokens, total_prompt_tokens, total_completion_tokens, elapsed_s` |
| `CompareResult` | compare -> runner | `match: bool`, `reason: str=""`, `column_map: dict[int,int]`, `extra_columns: list[str]=[]` |
| `QuestionResult` | runner -> report, CLI | `id, question, outcome` (pass/wrong_result/sql_error/policy_reject/transpile_error/no_submission/timeout/llm_error), `sql, golden_sql, reason, tool_calls, steps, max_prompt_tokens, total_tokens, seconds` |
| report.json | report -> report.md, next run delta | `{"timestamp","model","config":{...},"score":{"passed","total"},"decision","context":{"max_prompt_tokens","median_prompt_tokens"},"questions":[QuestionResult...],"previous"=null}` |

## Milestones

- **M1 - Data + truth:** config, schema doc, generator with all traps, SQLite + T-SQL writers, golden + reference,
  trap tests. Integration: generator -> build -> SQLite -> golden SQL == Python reference.
- **M2 - Safe execution:** policy + malicious set, result types + SQLite backend, LocalExecutor + MSSQL backend +
  audit. Integration: built DB -> executor (policy inside) -> golden == reference; malicious rejected and audited.
- **M3 - Agent + eval + CLI:** LLM client, fake LLM, tools/prompt, loop, compare, runner + report, table, CLI, README +
  smoke. Integration: runner with real FakeLLM + real executor; CLI subprocess end to end.

## Delight

1. **Turkish number formatting in tables** - `1.234,56`, numeric columns right-aligned (display only; values come
   from SQL untouched).
2. **Friendly empty/truncated notices** - "Sonuç boş (0 satır)" and "İlk 50 satır gösteriliyor (toplam 312)".
3. **Helpful startup errors** - missing `data/test.db` says "Önce `python -m nl2sql build-db` çalıştırın"; unreachable
   endpoint says which URL failed and suggests checking Strata / `NL2SQL_LLM_BASE_URL`; no traceback.
4. **Live eval progress** - one line per question as it finishes: `Q03 ✓ pass  4 araç  12.3 sn  8.1K token`.
5. **Run-to-run delta** - report.md shows score change vs the previous `latest` and which questions flipped
   (`Q04 wrong_result -> pass`).
6. **Step markers in `ask`** - each step prefixed ✓/✗ with its latency; a policy reject shows the reason inline so
   the viewer sees the guardrail work.
