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

Run 2 shapes and extensions: see "Contracts (Run 2 additions)" at the end of this file.

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

---

# PLAN - NL2SQL Run 2 (Phase 2: retrieval + join graph, proven by an A/B eval)

Source: `PROJECT_BRIEF_RUN2.md`. Rule of the phase: **no measured gain -> no RAG**. Everything above stays valid
unless a numbered "Run 2 decision" below says it changes. Stack unchanged: **no new dependencies** (embeddings via the
`openai` SDK; vectors, BM25 and the join graph in the standard library). The product still has no screens (CLI only,
web UI is out of scope), so there is still no `.hybrid/visual.json` (Decision 14 stands); "what users see" is the CLI
output and the markdown reports, planned in R2-14.

## Run 2 architecture

```
schema/schema.json (~81 tables) + schema/rules.json --build-index--> index/ docs.json vectors.json meta.json(hash)
        |                                                                   |
        |              nl2sql/index: text(fold) embed(Fake|OpenAI) docs bm25 store search(hybrid, RRF)
        |                                                                   |
generator.generate(seed) = Run 1 stream (unchanged) + extra.extend(own stream)          profiles/netsis.json
        -> build_db (every schema table)                                    |                 |
                                                                            v                 v
ask/eval --mode full|full_rules|rag -> agent/modes.py (ToolContext; tools + prompt per mode) <- nl2sql/graph
        -> loop.run_agent -> tools.dispatch: get_schema | search_schema | get_table_details | find_join_path
                                             | search_rules | sample_values | run_sql | submit_sql
                                  sample_values / run_sql / submit_sql -> LocalExecutor (policy inside)
eval --compare -> run_eval x3 modes (or reuse same-fingerprint latest) -> eval/compare_modes -> eval_out/compare/<ts>/
eval-retrieval -> in-memory index -> eval/retrieval (recall@k hybrid|bm25|dense, no LLM) -> eval_out/retrieval/<ts>/
python -m eval.review -> eval/REVIEW.md (golden + Python reference rows, for Eren's intent review)
```

## Run 2 file layout additions

```
schema/schema.json             grows to ~81 tables (10 Run 1 + 6 data + ~65 distractors)
schema/rules.json              12-15 business rules (Turkish)
profiles/netsis.json           ERP column-pair profile for inferred join edges
nl2sql/schema_map/extra.py     extend(dataset, seed): new data tables + distractor rows, own random stream
nl2sql/schema_map/rules.py     load_rules(), rules_text(), rule_text()
nl2sql/index/  text.py embed.py docs.py bm25.py store.py search.py
nl2sql/graph/  profile.py graph.py
nl2sql/agent/modes.py          Mode, ToolContext, tools/prompt per mode
nl2sql/eval/   retrieval.py compare_modes.py
eval/reference_run2.py         Q11-Q40 references (merged into eval.reference.REFERENCES)
eval/review.py                 `python -m eval.review` -> eval/REVIEW.md
index/ (ignored)   eval_out/<mode>/   eval_out/compare/   eval_out/retrieval/
```

## Run 2 decisions

R2-1. **Run 1 world frozen by a fingerprint.** `generate(seed)` keeps the Run 1 code and its single `rng` exactly;
      new rows come from `extra.extend(dataset, seed)`, called last, with `random.Random(f"{seed}:run2")` (str seeds are
      deterministic in CPython). Pin for seed 42, computed before Run 2:
      `sha256(json.dumps({t: d[t] for t in sorted(RUN1_TABLES)}, ensure_ascii=False, sort_keys=True).encode("utf-8"))`
      `== 30e9e06c656d60503e6fb520bd116e1a5d86af606c2e4ecd5d20ff98ad598ec9`. `generate()` returns a key for **every**
      schema table (empty list allowed).
R2-2. **schema.json stays one file** (Decision 2 stands). Two optional table fields: `kind` ("data"|"distractor",
      default "data") and `keywords` (list, default []). `kind` is bookkeeping for tests only: never shown to the model,
      never indexed, never read by the graph (a real ERP has no such flag).
R2-3. **New data tables and coded values** (fictional; generator, schema doc, rules and golden SQL agree on these):
      - `TBLSTOKFIAT(FIAT_ID, STOK_KODU->TBLSTSABIT, FIYAT_TIPI S=satış/A=alış, FIYAT, GECERLILIK_TARIHI)`: 2-4 rows per
        product over 2025-2026; "liste fiyatı" = the row with the latest GECERLILIK_TARIHI <= the date asked.
      - `TBLSTHAR_ARSIV`: same columns and codes as TBLSTHAR, **only 2025** (Jan-Dec), FISNO NULL or `ARS...` (no fk);
        right only for 2025 questions. TBLSTHAR keeps only Jun-Sep 2026 (unchanged).
      - `TBLDOVKUR(KUR_TARIH, DOVIZ_KODU USD|EUR, ALIS, SATIS)`: one row per day and currency, 2026-06-01..2026-09-30.
      - `TBLCARISUBE(SUBE_KODU, CARI_KOD->TBLCASABIT, SUBE_ADI, IL, ILCE, AKTIF E/H)`: 0-3 branches per cari; city
        spelling as in TBLCASABIT (upper case with Turkish letters: 'İSTANBUL').
      - `TBLKAMPANYA(KAMPANYA_KODU, KAMPANYA_ADI, STOK_KODU->TBLSTSABIT, BASLANGIC, BITIS, INDIRIM_ORANI)`: Jun-Sep 2026.
      - `TBLMUHFIS(MUHFIS_ID, FIS_NO, TARIH, HESAP_KODU '600' yurtiçi satış|'610' satış iadesi|'153' ticari mal|
        '391' KDV, BA B/A, TUTAR, FATIRS_NO->TBLFATUIRS)`: GL lines mirroring the 2026 invoices **including cancelled
        ones** (a plausible wrong source for "ciro").
R2-4. **Distractors (~65, `kind: distractor`)**: modules Muhasebe, Banka, Çek/Senet, Personel, Üretim, Servis, İthalat,
      Sabit Kıymet, Kalite, Lojistik; Netsis-style coded names; the frequent columns (CARI_KOD/CARI_KODU, STOK_KODU,
      TARIH, TUTAR, ACIKLAMA, FISNO) everywhere; some fk into real tables. Near-duplicates: `TBLSTHAR_LOG`,
      `TBLFATUIRS_TASLAK`, `TBLCASABIT_YEDEK`, `TBLSTSABIT_ESKI`, `TBLSIPATRA_TMP` (+ a few more). Rows: near-duplicates
      get plausible rows built from real codes whose answers **differ** from the real table's (log = edited/duplicated
      movements, taslak = unposted invoices); other distractors 0-5 typed filler rows (`extra.DISTRACTOR_ROWS`, default
      0). Every distractor is created in SQLite and in the T-SQL script.
R2-5. **`full` mode changes (supersedes "compact schema in the prompt" for this mode):** the system prompt carries the
      **whole schema detail** (`doc.full_text` = `table_detail` of every table): that is the context cost the A/B must
      measure (~20-35K tokens expected, estimated as chars / `config.CHARS_PER_TOKEN`); `build-db` and the compare
      report print the estimate. Tools in `full`: get_schema, run_sql, submit_sql (as Run 1). `full_rules` = `full` +
      `rules.rules_text(rules)` appended. `rag` = rules 1-5 + a search-first rule + only `doc.name_list(schema)` (table
      names grouped by module, no descriptions); tools: search_schema, get_table_details, find_join_path, search_rules,
      sample_values, run_sql, submit_sql. `prompt.system_prompt(as_of, compact_schema)` stays for Run 1 callers.
R2-6. **Tool limits per mode**: `config.MAX_TOOL_CALLS_BY_MODE = {"full": 8, "full_rules": 8, "rag": 12}` (rag needs
      lookup calls; recorded in each report's fingerprint so it is visible, not hidden tuning). Every tool answer in
      every mode is capped at `config.TOOL_RESULT_MAX_CHARS` (4000) with the suffix `… (kırpıldı: N karakter)`.
R2-7. **sample_values(table, column)** checks identifier syntax (`^[A-Za-z0-9_]+$`) and, when the table is in the
      schema, that the column belongs to it; the table itself is **not** pre-checked: the SQL
      `SELECT DISTINCT TOP 20 [col] FROM [table] WHERE [col] IS NOT NULL ORDER BY [col]` goes through
      `executor.execute`, so the policy rejects forbidden tables and the audit records it. Budget max_rows = 20.
R2-8. **Index**: one doc per table (name, module, description, columns with descriptions + code values, keywords) and
      per rule (term, synonyms, definition, sql_hint, tables); the `examples` collection exists and stays empty.
      Folding: `İ->i`, `I->ı`, then `str.lower()`; tokens = `\w+` after folding plus the parts of `_`-joined names
      (`cari_kod` -> cari_kod, cari, kod). FakeEmbedder = hashed bag-of-words (md5 of token mod dim, L2-normalized,
      dim 256; never Python `hash()`). Dense = brute-force cosine. BM25 (k1 1.5, b 0.75) is recomputed from the docs
      at load, not persisted (one artefact less to go stale). Fusion = RRF `sum 1/(RRF_K + rank)`, RRF_K 60, ties by
      doc id.
R2-9. **Index freshness**: `meta.json` stores `content_hash` (sha256 of canonical JSON of schema + rules) and the
      embedder id (`fake:256` / `openai:<model>`). Loading with another hash raises `StaleIndexError`; the CLI says
      "İndeks eski: `python -m nl2sql build-index` çalıştırın" (exit 2) - refused, never silently rebuilt. The query
      embedder is built from `meta.embedder`, so `ask`/`eval` take no `--embed`. `eval-retrieval --embed` builds its
      index **in memory** (no dependency on the on-disk index; works on a clean checkout).
R2-10. **Join graph**: edges from schema `fk` (confidence 1.0, source "fk") + profile pairs (every table having the left
      column x every other table having the right column, confidence from the profile, source "profile"; an fk edge
      wins over a profile edge on the same columns); edge cost `1 / confidence`; `find_join_path(tables)` = union of
      Dijkstra shortest paths from the first table to each other one, deduplicated, deterministic tie-break by table
      name; edges below `config.LOW_CONFIDENCE` (0.7) listed in `low_confidence`. No ERP rule in Python.
R2-11. **Rules agree with golden SQL**: each golden line lists its `rules` ids; each rule has `markers` (regexes) that
      must match every golden SQL citing it (whitespace-collapsed, case-insensitive), and every rule is cited by at
      least one question. Q03 -> `ciro` (KDV hariç, STHAR_NF x miktar, iade düşülmez), Q04 -> `plasiyersiz_haric` +
      `iptal_haric`, Q10 -> `iade_orani` (miktar bazlı). Q01-Q10 question texts unchanged. Rule set (12-15): ciro,
      net_satis (iade düşülür, miktar), brut_satis, iade_orani, iptal_haric, plasiyersiz_haric, gecen_ay, bu_yil,
      alici (CARI_TIP A/H), satici (S/H), arsiv_2025, liste_fiyati, doviz_tl, kampanyali_satis, teslim_bekleyen.
R2-12. **Eval outputs per mode** (supersedes Run 1's `eval_out/<ts>` + `eval_out/latest`): `eval_out/<mode>/<ts>/` and
      `eval_out/<mode>/latest/`, so the run-to-run delta compares like with like. `eval` default mode = `full`; `ask`
      default = `rag` when a fresh index exists, else `full` with a note line. Report `config` gains the fingerprint.
      `--compare` reuses a mode's latest when its fingerprint equals the one about to run; `--fresh` forces reruns.
R2-13. **Verdict** (deterministic, in Python): RAG kept iff `rag.passed >= full_rules.passed` **and**
      `rag.max_prompt_tokens < full_rules.max_prompt_tokens`. Lines: `Karar: RAG kalır — rag 31/40 ≥ full_rules 30/40
      ve tepe bağlam 6.2K < 28.4K token.` / `Karar: RAG yok — <the failed condition with both numbers>.` Never tune
      questions or limits to flip it (brief §9).
R2-14. **What the user sees (CLI states)**: build-db prints table counts (data/distractor) + the schema token
      estimate; build-index prints doc counts per collection, embedder, dim, hash prefix, seconds; embed server down
      -> URL + hint `NL2SQL_EMBED_BASE_URL` (exit 3, no traceback). `ask` header `Mod: rag` (+ fallback note when no
      fresh index); step notes per tool: search_schema `→ TBLSTHAR, TBLSTSABIT, …`, get_table_details `→ 2 tablo`,
      find_join_path `→ 2 join` (+ `⚠ düşük güven: …` line), search_rules `→ ciro, iade_orani`, sample_values
      `→ 8 değer`. `eval` prints `Mod: <mode>` before the live lines. `eval --compare` prints one summary line per mode
      (score, peak/median context, mean tool calls, seconds, `(önceki koşu)` when reused), then the verdict line and the
      report path. `eval-retrieval` prints a per-question table (`Soru | hybrid | bm25 | dense | eksik`), means per
      method and per tag. Empty states: search with no hit -> "Eşleşen tablo yok."; disconnected tables ->
      "Bağlantı yolu yok: A - B."; `--tag` matching nothing -> "Bu etiketle soru yok: <tag>" exit 2.
R2-15. **Golden Q11-Q40** are agent-written; Python references in `eval/reference_run2.py` stay independent of SQL
      (Decision 1); `eval.reference.REFERENCES` merges them. Tag rules: `trap:<name>` iff `trap` non-empty;
      `needs_rule` iff `rules` non-empty; `multi_join` = 3+ real tables; `archive` = uses TBLSTHAR_ARSIV. Targets:
      >= 8 questions each for needs_rule, multi_join, distractor, needs_values; >= 5 for archive. `requires_tables` =
      exactly the real tables of the golden SQL. Multi-join golden SQL uses the join conditions the graph finds (fk or
      profile pairs on the shortest path). Dates relative to AS_OF 2026-09-30 as before.
R2-16. **No leakage**: no index doc contains a golden question or any 6-token shingle of one (after folding).

## Contracts (Run 2 additions)

| Shape | Producer -> Consumer | Fields (optional = default) |
|---|---|---|
| schema doc (ext.) | schema.json -> doc, build, extra, index.docs, graph | table + `kind`="data" ("data"\|"distractor"), `keywords`=[] |
| rules doc | `schema/rules.json` -> rules.py, index.docs, prompt (full_rules), tests | `{"rules":[{"id","term","synonyms"=[],"definition","sql_hint"="","tables"=[],"markers"=[]}]}` |
| golden line (ext.) | golden.jsonl -> runner, FakeLLM, retrieval, graph test, review | + `tags`=[], `requires_tables`=[], `rules`=[] (runner.load_golden fills defaults) |
| profile | `profiles/netsis.json` -> graph | `{"name","pairs":[{"left","right","confidence"}]}`; pair symmetric, confidence in (0,1) |
| `Doc` | index.docs -> store, bm25, search | `id` ("table:X"\|"rule:<id>"), `collection` ("tables"\|"rules"\|"examples"), `title`, `text`, `meta`={} (`table`,`module` \| `term`,`tables`) |
| Embedder | embed -> build-index, search, retrieval | `id: str`, `dim: int`, `embed(texts: list[str]) -> list[list[float]]` (L2-normalized); failures -> `EmbedError` (message names the URL) |
| index files | store.FileStore -> search.load_search | `docs.json` [Doc], `vectors.json` [[float]] in doc order, `meta.json` {`content_hash`,`embedder`,`dim`,`built_at`,`counts`:{collection:int}} |
| `Hit` | search -> tools, retrieval | `doc_id`, `title`, `score: float`, `rank: int` (1-based), `text`="" |
| `Edge` | graph -> find_join_path, tools | `left_table`, `left_column`, `right_table`, `right_column`, `confidence: float`, `source` ("fk"\|"profile") |
| `JoinPath` | graph.find_join_path -> tools, tests | `tables: list[str]` (requested + intermediates), `joins: list[Edge]`, `low_confidence: list[Edge]`=[]; unknown table / no path -> `GraphError(message)` |
| `ToolContext` | caller -> loop -> dispatch | `executor`, `schema`, `rules`=[], `search`=None (HybridSearch), `graph`=None (JoinGraph), `mode`="full" |
| `Mode` | modes -> loop | `name`, `tools: list[dict]`, `system_prompt(ctx) -> str`, `max_tool_calls: int` |
| `AgentRun` (ext.) | loop -> runner, CLI | + `mode: str`="full" |
| `QuestionResult` (ext.) | runner -> report, compare_modes | + `mode`="full", `tags`=[] |
| report.json (ext.) | report -> compare_modes, next run | + `mode`, `tags`: {tag: {passed,total}}, `config.fingerprint`: {`mode`,`llm`,`model`,`question_ids`,`golden_hash`,`schema_hash`,`rules_hash`,`index_hash`="" (rag only),`max_tool_calls`} |
| compare report.json | compare_modes -> report.md, CLI, tests | `{"timestamp","model","questions":int,"schema_tokens":int,"modes":{mode:{"score","tags","context":{"max_prompt_tokens","median_prompt_tokens"},"tool_calls":{"mean","max"},"seconds":{"mean","total"},"report":path,"reused":bool}},"flips":[{"id","outcomes":{mode:outcome}}],"verdict":{"keep_rag":bool,"line":str}}` |
| retrieval report | eval.retrieval -> CLI, report.json/md | `{"k","embedder","questions":[{"id","tags","requires","hybrid","bm25","dense" (recall 0-1),"missing":{method:[tables]}}],"mean":{method:float},"by_tag":{tag:{method:float}}}` |

## Run 2 milestones

- **M4 - Bigger world + rules + questions** (T31-T46): config, schema contract + Run 1 pin, 6 data tables + rows,
  ~65 distractors + rows, build-db counts/token estimate, golden contract, rules, Q11-Q40 + references, REVIEW.md.
  Integration: real generator -> build_db -> LocalExecutor -> 40 golden == references; tag/rule coverage; pin.
- **M5 - Retrieval + graph** (T47-T57): folding, embedders, docs, BM25, store, hybrid search, build-index, profile +
  graph + find_join_path, eval-retrieval. Integration: real schema/rules -> docs -> FakeEmbedder -> FileStore ->
  HybridSearch over 40 questions; graph over every multi_join golden; leakage on the real index.
- **M6 - RAG agent + A/B eval** (T58-T66): modes/prompts, rag tools + cap, sample_values, mode-aware loop + FakeLLM rag
  replay, runner/report per mode, CLI eval --mode/--tag, compare report, CLI --compare + ask --mode, README + smoke.
  Integration: real FakeLLM + real executor + real index + real graph through `eval --compare`.

---

# PLAN - NL2SQL Run 3 (schema map import: Excel + live DB, and PII protection)

Source: `PROJECT_BRIEF_RUN3.md`. Product name **Bilgin** (README title; package and CLI stay `nl2sql`). Everything
above stays valid unless a numbered "Run 3 decision" says it changes. Stack: Run 2 + **openpyxl 3.1.5** (MIT, pure
Python; installed and pinned in pyproject before the run). No pandas, no other new dependency. Still CLI-only ->
Decision 14 stands, no `.hybrid/visual.json`; "what users see" is CLI output and markdown reports (R3-13).

## Run 3 architecture

```
Excel map --(LLM proposes mapping JSON, user edits/accepts)--> excel.convert (code, all rows) --> schema/imported.json
live DB  --introspect (SQLite PRAGMA | MSSQL INFORMATION_SCHEMA)--------------> schema/skeleton.json
                          merge.merge_map (DB truth: existence+types; Excel truth: meaning) --> merged schema
                          diff.diff_map  --> schema/diff.json + schema/diff.md          |
                                                                                  build-index (hash check stays)
ask/eval --mode full|full_rules|rag|auto--> agent --> LocalExecutor.execute:
    policy.check (tables + PII filter rules) -> transpile -> backend -> pii.mask (sqlglot lineage, fail closed)
    -> Result (+ masked_columns) -> audit (+ masked column names, never values)
make-login-script --> db/mssql/readonly_login.sql (the primary control; policy is the second layer)
```

## Run 3 file layout additions

```
profiles/excel_headers.json      header synonyms for the deterministic mapping fallback
nl2sql/schema_map/excel.py       read (sheets, header detect, preview), propose (LLM+fallback), convert (rows)
nl2sql/schema_map/introspect.py  sqlite skeleton, MSSQL query texts + rows -> skeleton, --sample hints
nl2sql/schema_map/merge.py       merge_map(excel, db), diff_map(excel, db) -> DiffReport, render md
nl2sql/policy/pii.py             classes + mask fns, trace(sql, schema) lineage, filter check for predicates
nl2sql/engine/login_script.py    readonly_login_sql(schema, login) -> T-SQL text
tests/fixtures/make_maps.py      generates map_netsis_style.xlsx + map_customer_map.xlsx from schema.json
tests/fixtures/*.xlsx            the two committed fixtures
tests/data/pii_bypass.jsonl      >= 20 bypass cases
schema/mapping.<name>.json  schema/imported.json  schema/skeleton.json  schema/diff.json|md  (generated, ignored)
db/mssql/readonly_login.sql      (generated)
```

## Run 3 decisions

R3-1. **Golden test consolidation (first task of the run).** One parametrized file `tests/test_golden_all.py` over
      every golden line with the union of per-question checks (policy pass, transpile, run on build_db(tmp), equals
      eval.reference.REFERENCES rounded 2 dp, >=1 row, order-aware only when `ordered`). Delete
      `tests/test_golden_q11_q20.py`, `test_golden_q21_q30.py`, `test_golden_q31_q40.py`; strip the duplicated
      golden-vs-reference parts from `tests/test_golden_reference.py`, `tests/test_integration_m2.py`,
      `tests/test_integration_m4.py`, keeping every other distinct assertion there. Report test count before/after;
      behaviour coverage must not shrink.
R3-2. **Excel pipeline is two-phase, LLM never touches rows.** Phase 1 `propose`: the LLM sees only sheet names,
      headers and the first `config.EXCEL_PREVIEW_ROWS` (20) rows and returns the mapping JSON; it is written to
      `schema/mapping.<name>.json` for the user to edit. Phase 2 `convert` (on `--accept`) turns **all** rows into a
      canonical schema with code only: group by table, normalise types, parse `values` cells (`G=Giriş; C=Çıkış`),
      keep row order, report skipped/invalid rows with sheet+row number. Header row = first row with >= 3 text cells.
R3-3. **Deterministic fallback** (`profiles/excel_headers.json`: canonical field -> Turkish-folded header synonyms;
      TABLO/TABLE/TABLO ADI, KOLON/ALAN/FIELD, TİP/TYPE, AÇIKLAMA/ACIKLAMA/DESCRIPTION, MODÜL/MODUL/MODULE,
      TÜR/TUR/DEĞER/DEGER/VALUES, NULLABLE/BOŞ, REFERANS/FK...). Used when the LLM is unreachable (with a printed
      note) and always to sanity-check the LLM proposal; per-field disagreements are listed in the proposal output
      and in the mapping file (`disagreements`), never silently resolved.
R3-4. **Introspection.** SQLite: `sqlite_master` + `PRAGMA table_info` / `foreign_key_list`. SQL Server: query texts
      (`INFORMATION_SCHEMA.TABLES/COLUMNS`, `sys.foreign_keys` joins) live in ONE module constant, are parse-tested
      with sqlglot tsql, and the rows -> skeleton conversion is a pure function unit-tested with hand-built rows;
      the pyodbc connection (lazy, `NL2SQL_MSSQL_CONN`, ApplicationIntent=ReadOnly) is never exercised by tests.
      Skeleton schema: names, types (normalised to the T-SQL type names schema.json uses), nullability, fks;
      descriptions empty; `kind` = "unknown"; join edges stay inferred from the profile (nothing stored).
      `--sample` adds up to 5 distinct values per short text column (declared length <= 100), fetched through
      LocalExecutor (policy + audit inside), columns whose `pii` is set excluded.
R3-5. **Merge + diff.** `merge_map`: live DB wins on existence and types, Excel wins on meaning (description, values,
      module, keywords); an Excel fk missing in the DB is kept only in the diff, not in the merge. `diff_map` ->
      `DiffReport` rendered as diff.json + diff.md. Index freshness (R2-9) keeps working: content_hash is computed
      from the schema actually loaded, so `build-index`/`eval --schema <path>` refuse an index built from another one.
R3-6. **PII.** Schema columns gain optional `pii` in tckn, vkn, iban, phone, email, address, salary, person_name.
      Masking runs **inside the executor, after the backend, before the Result is returned** (model, CLI and eval
      all see masked rows): output columns are traced to source columns with sqlglot lineage; any output depending
      on a PII column is masked per class (`tckn` -> `*******1234`, `iban` -> `TR** **** **** **** 1234`, `salary`
      -> `***`, `address` -> city only, `phone` -> last 4, `email` -> first char + domain, `person_name` -> initials
      only, `vkn` -> `*******1234`), except whitelisted aggregates `COUNT` / `COUNT(DISTINCT ...)` which stay;
      `MAX/AVG` over a salary stay masked. Lineage unresolvable for an output column -> the whole column is masked
      (fail closed) and the count of fail-closed columns is printed. Policy rejects PII columns appearing in
      WHERE/JOIN/GROUP BY/ORDER BY (filter side channels), configurable per class via `config.PII_FILTER`. Audit
      gains `masked`: column names only. sample_values and introspect --sample inherit the protection through the
      executor.
R3-7. **Synthetic PII data** (`extra.extend_run3(dataset, seed)`, own stream `random.Random(f"{seed}:run3")`, called
      last): TBLPERSONEL gains columns TCKN/VKN/IBAN/E_POSTA/ADRES (appended), TBLCARISUBE gains ADRES/TELEFON/
      E_POSTA; TBLPERSONEL, TBLMAAS, TBLMAASDETAY get rows (fictional people, checksum-valid TCKN (11-digit rule)
      and IBAN (mod-97)); existing Run 1/Run 2 column values and all 40 golden answers unchanged (Run 1 pin holds;
      golden SQL selects explicit columns). schema.json annotates the PII columns (R3-6 classes); no golden question
      touches them.
R3-8. **Login script** (`make-login-script [--login nl2sql_ro]` -> `db/mssql/readonly_login.sql`): CREATE LOGIN with
      password placeholder `__DEGISTIR__` (never a real one), CREATE USER, `db_datareader`, `DENY SELECT` on every
      table not in the schema allowlist, column-level `DENY SELECT` on every `pii` column, `DENY VIEW DEFINITION`,
      `DENY EXECUTE`; header comments state that views/synonyms/TVFs bypass a parser allowlist so THIS script is the
      primary control. Tests parse the whole script with sqlglot tsql and check the DENY set equals the schema.
R3-9. **Retrieval improvements, measured, never tuned to flip the verdict.** Neighbour expansion: `search_schema`
      adds 1-hop join-graph neighbours of the top-k that are data tables (config `NEIGHBOUR_EXPANSION` on/off,
      `NEIGHBOUR_MAX`), hits marked "komşu" in the tool answer; synonym rewriting: synonyms of the rules matched by
      the query are appended to the BM25 query (config `SYNONYM_REWRITE`). `eval-retrieval` reports recall@k per
      variant (base / +komşu / +eşanlam); with FakeEmbedder neither may lower recall@5 on the golden set. Embed
      model is configuration: `build-index --embed-model` / `eval-retrieval --embed-model`, meta stores the id
      (already true); README documents bge-m3 (MIT) via llama-server `--embedding` on CPU at another port. `rag`
      prompt gains: call `find_join_path` before writing a 3+ table join.
R3-10. **`--mode auto`** (new default for `ask`; eval keeps explicit modes): estimate = `doc.estimate_tokens` of the
      full_rules system prompt (schema full text + rules + system); <= `config.AUTO_FULL_MAX_TOKENS` (12000) ->
      `full_rules`, else `rag` (rag without a fresh index -> `full` with the Run 2 note). The chosen mode and the
      estimate are printed and land in the audit/`AgentRun.mode`.
R3-11. **Noise measurement**: `eval --compare --repeat N` runs each mode N times; the compare report gains per-mode
      and per-tag mean/min/max scores, `flips_within_mode` (questions whose outcome changes between repeats of the
      same mode), and the verdict uses the means, saying "fark gürültü içinde" when two mode means differ by less
      than the max-min spread of either.
R3-12. **Test rule for this run (from brief §0):** tests over a growing or configurable set assert structure (ids
      sequential/unique, every item checked), never a fixed count; a test that depends on data volume reads it from
      the dataset/config. New tests must not hardcode "40 questions" or "83 tables".
R3-13. **What the user sees (CLI states):** `import-map` prints the proposal as a table (sheet, header row, mapped
      fields per column), the disagreement lines ("⚠ uyuşmuyor: <sheet>.<column> <field>: llm=... fallback=..."),
      and after --accept "Şema yazıldı: schema/imported.json (N tablo, M kolon, K atlanan satır)" with each skipped
      row listed; `introspect` prints "İskelet: N tablo, M kolon -> schema/skeleton.json"; `diff-map` prints the
      counts and the two output paths, empty diff -> "Fark yok."; `eval --schema X` prints "Şema: <path> (<hash8>)";
      after a masked result the CLI prints "Maskelendi: TCKN, TELEFON" and the audit line carries the names; `ask`
      prints "Mod: auto -> full_rules (bağlam tahmini 9.8K token)"; `--repeat` prints per-mode mean/min/max and the
      noise verdict line.
R3-14. **Real-data checklist** in README: introspect -> import-map -> diff-map -> merge-map -> build-index ->
      make-login-script (create the login first!) -> ask/eval against a Netsis **copy**; states that nothing in the
      tests touches a real server and that Windows auth (sysadmin) is never used.

## Contracts (Run 3 additions)

| Shape | Producer -> Consumer | Fields (optional = default) |
|---|---|---|
| sheet preview | excel.read -> propose, CLI | `{"file", "sheets":[{"name", "header_row"(1-based), "headers":[str], "rows":[first EXCEL_PREVIEW_ROWS rows as [cell]]}]}` |
| mapping | excel.propose -> `schema/mapping.<name>.json`, excel.convert, CLI | `{"file", "generated_by"("llm"\|"fallback"), "sheets":[{"sheet","header_row","columns":[{"column"(letter or header text),"table_name"=null,"column_name"=null,"data_type"=null,"description"=null,"fk_target"=null("TABLE.COL"),"values"=null,"nullable"=null,"module"=null}]}], "disagreements"=[{"sheet","column","field","llm","fallback"}]}` |
| convert report | excel.convert -> CLI | `{"schema": <canonical schema doc>, "tables": int, "columns": int, "skipped":[{"sheet","row"(1-based),"reason"}]}` |
| skeleton schema | introspect -> merge, diff, eval --schema | canonical schema doc shape; `kind`="unknown", descriptions "", `pii` from DB = none |
| `DiffReport` | merge.diff_map -> diff.json/md, CLI | `{"excel_only_tables":[str], "db_only_tables":[str], "excel_only_columns":[{"table","column"}], "db_only_columns":[{"table","column"}], "type_mismatches":[{"table","column","excel","db"}], "fk_missing_in_db":[{"table","column","fk"}]}` |
| pii class | schema.json column + `pii`=null -> policy, pii.mask, login_script, introspect --sample | one of tckn, vkn, iban, phone, email, address, salary, person_name |
| lineage | pii.trace(sql, schema) -> pii.mask | per output column: `list[(table, column)]` or `None` (unresolvable -> mask whole column) |
| `Result` (ext.) | executor -> tools, runner, CLI | + `masked_columns: list[str]`=[] |
| audit entry (ext.) | executor -> logs/audit.jsonl | + `"masked"`:[column names]=[] — never values |
| bypass case | `tests/data/pii_bypass.jsonl` -> parametrized test | `{"id","sql","expect"("masked"\|"rejected"),"masked_columns"=[],"note"=""}` |
| retrieval report (ext.) | eval.retrieval -> CLI, report | + `variants`: "base"\|"neighbours"\|"synonyms" -> `{"mean":{method:float},"by_tag":{...}}` |
| report.json (ext.) | runner -> report.md | + `"schema"`: {"path","hash"} |
| compare report (ext.) | compare_modes -> report.json/md | + `"repeat"`:int=1, per mode `"scores"`:{"mean","min","max"}, per tag mean/min/max, `"flips_within_mode"`:int; verdict line may end "fark gürültü içinde" |

## Run 3 milestones

- **M7 - Clean-up + Excel import** (T77-T85): golden test merge, config, reader + header detection, fallback
  mapping, LLM proposal + disagreements, row conversion, fixtures, CLI import-map. Integration: real fixture files
  -> real reader -> real fallback -> real convert == schema.json (tidy exact; messy same tables/columns).
- **M8 - Live schema** (T86-T92): SQLite + MSSQL introspect, --sample, merge, diff, merge-map/diff-map CLI,
  eval --schema <path|full|skeleton> with schema path+hash in the report. Integration: build_db -> real introspect
  -> real diff vs real imported schema -> eval --schema skeleton with fake LLM.
- **M9 - PII + DB script** (T93-T101): classes + masks, schema annotations, synthetic PII rows, lineage, executor
  masking + audit, filter rules, bypass set, login script, README checklist. Integration: real executor on real
  built DB masks every bypass case; golden 40 unchanged; login script DENY set == schema.
- **M10 - Retrieval + modes** (T102-T109): neighbour expansion, synonym rewriting, eval-retrieval variants,
  embed-model config, rag join hint, --mode auto, --repeat noise, README + smoke. Integration: real index + graph +
  FakeEmbedder through eval-retrieval; real CLI auto + compare --repeat.

---

# PLAN - NL2SQL Run 4 (datasets + WideWorldImporters, model profiles + context budget)

Source: `PROJECT_BRIEF_RUN4.md`. Everything above stays valid unless a numbered "Run 4 decision" says it changes.
Stack unchanged, **no new dependency** (WWI fixture in SQLite via the stdlib, endpoint check via the `openai` SDK
already pinned). Still CLI-only: the web UI is Run 5, so Decision 14 stands and there is still no
`.hybrid/visual.json`; "what users see" is CLI output and the markdown reports (R4-14). The brief names `serve`
for `--model`; there is no `serve` command yet (Run 5), so `--model` lands on `ask` and `eval` only.

Open before this run (not blocking it): T101 (README Run 3 section), T109 (Run 3 smoke file) and T120 (`_t101check/`
cleanup) are still `[ ]`; T120's deletion is staged in the working tree. Run 4 tasks do not depend on them.

## Run 4 architecture

```
datasets/<name>/dataset.json + schema.json rules.json profile.json golden.jsonl [traps.jsonl] [builder.py reference.py]
        |  nl2sql/datasets.load_dataset(name) -> Dataset (paths, as_of, seed, builder, generator, references)
        v
--dataset X --> build-db | build-index | eval-retrieval | ask | eval | eval --compare | make-login-script
        schema "Sales.Orders" --policy (qualified allowlist, unqualified -> resolved) --> executor
        --sqlite: rewrite Sales.Orders -> "Sales.Orders" (one quoted identifier) | mssql: as written
config/models.json --nl2sql/agent/llm.load_profiles--> ModelProfile --> client_for(profile), budget
loop: before every chat: estimate(messages+tools) > budget? trim old tool answers -> still over? context_overflow
eval --compare --models a,b --modes m1,m2 --dataset d [--repeat N]
        -> per model: ping endpoint (skip block + message if down) -> per mode x repeat: run_eval(budget)
        -> nl2sql/eval/compare_models -> eval_out/compare_<dataset>_<ts>.json|md (model x mode table)
```

## Run 4 file layout additions

```
datasets/synthetic_erp/        dataset.json + MOVED (paths only, content byte-identical):
                               schema/schema.json -> schema.json, schema/rules.json -> rules.json,
                               profiles/netsis.json -> profile.json, eval/golden.jsonl -> golden.jsonl,
                               eval/traps.jsonl -> traps.jsonl
                               (Python stays where it is: nl2sql/schema_map/{generator,extra,build}.py,
                               eval/reference.py + eval/reference_run2.py; dataset.json points at them)
datasets/wwi/                  dataset.json schema.json rules.json profile.json golden.jsonl traps.jsonl
                               builder.py (generate + build_db) reference.py (REFERENCES)
nl2sql/datasets.py             Dataset, load_dataset(name, root), list_datasets(root), DatasetError
nl2sql/agent/budget.py         estimate_prompt(messages, tools), trim_tool_answers(messages, limit)
nl2sql/eval/compare_models.py  build_model_compare(cells, ...), render md, write_model_compare
config/models.json             model profiles (no secrets: only the NAME of the key's env variable)
tests/fixtures/datasets/mini/  3-table qualified-name dataset (Sales/Warehouse), for M11 tests before WWI exists
tests/data/pii_bypass_wwi.jsonl  >= 20 bypass cases on WWI names
data/wwi.db  db/mssql/build_wwi.sql  index/wwi/  eval_out/wwi/   (generated, ignored like their synthetic twins)
```

## Run 4 decisions

R4-1. **Dataset = folder + `dataset.json`** (Contracts). `nl2sql/datasets.load_dataset(name, root=None)`; `root`
      default = `config.datasets_dir()` (env `NL2SQL_DATASETS_DIR`, read at call time, default `<ROOT>/datasets`) so
      tests point at `tests/fixtures/datasets` without monkeypatching globals (Decision 9). Code references in
      dataset.json are `"module.path:attr"` (imported) or `"file.py:attr"` (loaded by path from the dataset folder
      with `importlib.util.spec_from_file_location`, module name `nl2sql_dataset_<name>_<stem>`; the repo-root
      `datasets/` folder is never imported as a package - it would shadow HuggingFace `datasets`). Unknown name ->
      `DatasetError("Bilinmeyen veri kümesi: x (bilinenler: synthetic_erp, wwi)")`, CLI exit 2.
R4-2. **The synthetic move is paths only** (brief §9). The five data files move with their bytes unchanged
      (sha256 before == after, asserted in the task's test); `config.SCHEMA_PATH/RULES_PATH/PROFILE_PATH/
      GOLDEN_PATH/TRAPS_PATH` point at the new places, so every module that defaults to config follows with no
      code change. **Changes an old decision:** the path literals pinned in `tests/test_config.py` (SCHEMA_PATH,
      GOLDEN_PATH, TRAPS_PATH) and `tests/test_config_run2.py` (RULES_PATH, PROFILE_PATH) change to the new
      locations - these two tests pin a location the brief deliberately moves; no other existing test changes.
      `profiles/excel_headers.json` is not dataset data and stays. `tests/fixtures/make_maps.py` reads
      `config.SCHEMA_PATH` instead of its own literal. Generated Run 3 outputs (`schema/imported.json`,
      `skeleton.json`, `diff.*`, `mapping.*`, `merged.json`) stay under `schema/` (config.SCHEMA_DIR unchanged).
R4-3. **Outputs per dataset.** dataset.json `outputs` (all optional): `db` (default `data/<name>.db`),
      `mssql_script` (`db/mssql/build_<name>.sql`), `index_dir` (`index/<name>`), `eval_out` (`eval_out/<name>`).
      synthetic_erp spells today's paths (`data/test.db`, `db/mssql/build_test_db.sql`, `index`, `eval_out`), so a
      run without `--dataset` reads and writes exactly what it did in Run 3.
R4-4. **`--dataset <name>` (default `config.DEFAULT_DATASET` = "synthetic_erp")** on build-db, build-index,
      eval-retrieval, ask, eval (incl. `--compare`) and make-login-script. Whole: the Dataset supplies EVERY one of
      schema, rules, profile (join graph), golden (eval, eval-retrieval, fake replay), seed, builder, db path, T-SQL
      script path, index dir, eval_out, `as_of` and the fake fallback SQL - no command may keep a `config.*` default
      for any of them once `--dataset` exists. `as_of` reaches the model through `ToolContext.as_of`
      (default `config.AS_OF`; modes.py's three prompts read it instead of `config.AS_OF`) and the auto estimate.
      `--schema` (R3-5) still overrides the dataset's schema for eval.
R4-5. **Qualified table names.** A schema table `name` is `"Schema.Table"` when it lives outside the dataset's
      `default_schema`; synthetic tables stay bare (default_schema `dbo`). Helpers in doc.py: `split_name(name) ->
      (schema|None, table)`, `split_fk("Sales.Orders.CustomerID") -> ("Sales.Orders", "CustomerID")` (rsplit once),
      `allowlist()` = upper-cased full names (unchanged for synthetic). Policy (`_check_table`):
      - `schema.table` whose upper full name is in the allowlist -> allowed; `tables` records the full name.
      - a 3- or 4-part name (catalog/server) -> rejected as today; `sys.*`/`INFORMATION_SCHEMA.*` -> as today.
      - a 2-part name not in the allowlist (`Website.Customers`, `[dbo].[TBLSTHAR]`) -> "İzin verilmeyen tablo:
        WEBSITE.CUSTOMERS — başka şema, veritabanı ya da sunucu okunamaz." (keeps the "veritabanı" every existing
        malicious case expects).
      - a bare name: in the allowlist -> as today; else exactly one allowlisted `X.<name>` -> the node is
        rewritten to `X.<name>` (so SQL Server sees the qualified name too); several -> "Belirsiz tablo adı:
        ORDERS (PURCHASING.PURCHASEORDERS, ...); şemasıyla yazın."; none -> as today.
      `check()` gains no parameter: resolution reads the allowlist only.
R4-6. **SQLite storage of qualified names**: the SQLite table is created as the single quoted identifier
      `"Sales.Orders"` (build.write_sqlite already quotes); `executor` rewrites every `exp.Table` with a `db` part to
      `Identifier("Sales.Orders", quoted=True)` (and a column's 3-part `Sales.Orders.Col` prefix likewise) in the
      transpile step only - PolicyResult.sql stays T-SQL. T-SQL script: `CREATE SCHEMA [Sales];` once per schema
      before the tables, names bracketed `[Sales].[Orders]`. Type map gains `BIT`->`BOOLEAN`, `DATETIME2`->
      `DATETIME`, `VARBINARY`->`BLOB` (declared SQLite type names; affinity keeps text dates text) and
      introspect.normalize_type stays the exact inverse (synthetic round trip unchanged). Introspection: SQLite
      names come back dotted as stored; MSSQL `rows_to_skeleton` names `f"{schema}.{table}"` unless schema == "dbo"
      (supersedes Run 3's "bare names" ASSUMPTION; Netsis in dbo is unchanged), fks the same way.
R4-7. **PII on qualified names + denied columns.** `pii.column_map` keys are `(FULL_TABLE_NAME_UPPER, COLUMN)`;
      `pii.trace` builds the sqlglot lineage schema nested `{schema: {table: {col: type}}}` for qualified tables;
      `_filter_target`/`_aliases` in policy use full names. New optional column field `deny` (default false): the
      column is left out of every model-facing text (`table_detail`, `full_text`, index docs), the policy rejects
      any reference to it anywhere ("Erişimi kapalı kolon: APPLICATION.PEOPLE.HASHEDPASSWORD.") and rejects
      `SELECT *` / `t.*` over a table that has one ("Bu tabloda kapalı kolon var; kolonları adıyla yazın."); the
      login script DENYs it like a pii column. WWI: `Application.People.HashedPassword` and `.Photo` are `deny`
      (the brief says "PhotoPath"; WWI's real column is `Photo` varbinary - the real name wins), `FullName`/
      `PreferredName` person_name, `EmailAddress`/`LogonName` email, `PhoneNumber`/`FaxNumber` phone; Customers and
      Suppliers `PhoneNumber`/`FaxNumber` phone, `DeliveryAddressLine1/2`/`PostalAddressLine1/2` address.
      Login script: `OWNER = "dbo"` is replaced by each table's own schema (bracketed), dbo for bare names.
R4-8. **Index belongs to a dataset.** build-index writes `meta.dataset`; `FileStore.load_checked(expected_hash,
      dataset=None)` raises `ForeignIndexError` (subclass of `StaleIndexError`, so every existing `except` keeps
      catching it) with "İndeks başka veri kümesine ait: <stored> (istenen <wanted>); `python -m nl2sql build-index
      --dataset <wanted>` çalıştırın." when they differ; meta without `dataset` counts as "synthetic_erp".
      Search answers, ask's step notes and the eval-retrieval table print qualified names: the CLI regexes
      `SCHEMA_HIT`/`DETAIL_HEAD` in nl2sql/cli/main.py accept `Schema.Table` (mixed case, one dot).
R4-9. **WWI dataset (fictional rows, Microsoft's public names).** 20 tables: Application.{Countries,
      StateProvinces, Cities, DeliveryMethods, People}, Sales.{BuyingGroups, Customers, Orders, OrderLines, Invoices,
      InvoiceLines, CustomerTransactions}, Warehouse.{StockGroups, StockItems, StockItemStockGroups,
      StockItemTransactions, StockItemHoldings}, Purchasing.{Suppliers, PurchaseOrders, PurchaseOrderLines}
      (BuyingGroups and StockItemStockGroups added to the brief's list: the buying-group trap and stock groups need
      them). Columns: the reporting subset of the real ones with the real names and T-SQL types (e.g. Sales.Invoices:
      InvoiceID, CustomerID, BillToCustomerID, OrderID, DeliveryMethodID, SalespersonPersonID, InvoiceDate,
      IsCreditNote BIT, ConfirmedDeliveryTime DATETIME2 NULL; InvoiceLines: InvoiceLineID, InvoiceID, StockItemID,
      Description, Quantity, UnitPrice, TaxRate, TaxAmount, LineProfit, ExtendedPrice). English descriptions,
      Turkish `keywords` per table, `module` = the schema name, fks as `"Sales.Customers.CustomerID"`,
      `default_schema` null, `as_of` "2016-05-31" (the real sample ends there), seed 42. Fixture = small
      deterministic rows (`random.Random(f"{seed}:wwi")`), Jan-May 2016, with traps: orders never invoiced; credit
      notes (`IsCreditNote = 1`, negative line quantities/amounts); back-orders (`Orders.BackorderOrderID`);
      several StockItemTransactions per item (signed quantities); NULL `ConfirmedDeliveryTime` /
      `PickingCompletedWhen`; one customer name on two CustomerIDs in two buying groups; purchase orders received
      after `ExpectedDeliveryDate`. Business terms (rules.json, Turkish): ciro = SUM(Quantity*UnitPrice) of
      non-credit-note invoice lines (KDV/vergi hariç), net_satis = ciro with credit notes subtracted, brut_kar =
      SUM(LineProfit), eldeki_stok = StockItemHoldings.QuantityOnHand, geciken_teslimat, faturalanmamis_siparis,
      geri_siparis, gecen_ay/bu_yil relative to 2016-05-31, plus what the golden needs. Golden >= 25 Turkish
      questions, same line contract, Python references in `datasets/wwi/reference.py` never reading SQL. Tag
      vocabulary as R2-15 (trap tags from `datasets/wwi/traps.jsonl`); targets for WWI: >= 6 needs_rule, >= 6
      multi_join, >= 4 needs_values, every trap >= 1. Licence: Microsoft publishes the sample under MIT in
      `sql-server-samples`; README repeats "re-check before publishing" (brief §9).
R4-10. **Model profiles** (`config/models.json`, read by `llm.load_profiles(path=config.MODELS_PATH)`): name ->
      `ModelProfile` (Contracts). Shipped: `strata` (http://127.0.0.1:8080/v1, model "strata", no key variable,
      budget 262144, max output 8192), `qwen27b-24k` / `qwen27b-16k` (http://127.0.0.1:8888/v1, model
      "unsloth/Qwen3.8-27B-GGUF", key variable `UNSLOTH_API_KEY`, budgets 24576 / 16384, max output 4096).
      `llm.client_for(profile)` reads the key from the named variable at call time (none named -> "local"; named
      but unset -> `LLMError("API anahtarı yok: UNSLOTH_API_KEY ortam değişkenini tanımlayın.")`, CLI exit 2) and
      passes `max_tokens`, sampling and `enable_thinking` to the request. `--model` absent = Run 3 behaviour
      (`config.llm_settings()`, no budget). `--models-file <path>` on ask/eval overrides the file (tests).
      A test scans models.json: no field other than `api_key_env` mentions a key, no value looks like a secret.
R4-11. **Context budget, enforced by code.** `prompt_limit = context_budget - max_output_tokens`. Before EVERY
      `llm.chat` the loop computes `budget.estimate_prompt(messages, tools)` = ceil(chars of every message content
      + JSON of every tool_calls entry + JSON of the tool schemas, / CHARS_PER_TOKEN) + `MESSAGE_OVERHEAD_TOKENS`
      per message (the `doc.estimate_tokens` rule `--mode auto` uses). Over the limit -> `trim_tool_answers`: tool
      messages oldest first, the latest tool message never, each cut to `config.TRIM_TOOL_CHARS` chars + "…
      (bağlam bütçesi için kısaltıldı: N karakter)", re-estimating after each; the message stays (every
      tool_call_id must keep its answer), the cut is permanent in the transcript. Still over -> the run stops with
      status `context_overflow`, stop reason "Bağlam bütçesi aşıldı: tahmin E > sınır L token." - nothing is sent.
      A system prompt that alone does not fit overflows on turn 1 (a 27B in 16K with full_rules on the synthetic
      set): that is a result, not a failure to hide (brief §9). AgentRun records `peak_estimate`, `trimmed`,
      `overflows` (0/1); `max_prompt_tokens` stays the server-reported peak. QuestionResult gains outcome
      `context_overflow` (runner.OUTCOMES grows to 9; **changes** the count pinned in
      `tests/test_eval_runner.py`, which that task edits) and the three numbers. `budget=None` = no enforcement,
      so every pre-Run 4 caller is unchanged.
R4-12. **`--mode auto` per profile**: `resolve_auto(schema, rules, index_dir, max_tokens=None)`; None -> reads
      `config.AUTO_FULL_MAX_TOKENS` at call time (tests/test_cli_auto_mode.py monkeypatches it); with `--model` the
      threshold is the profile's `auto_full_max_tokens` or `floor(context_budget * config.AUTO_FULL_SHARE)`
      (0.5: half the window for tool rounds; 24K -> 12288, 16K -> 8192). The AUTO_LINE gains "· bütçe 16.384".
R4-13. **Model comparison eval** (`eval --compare --models a,b [--modes full_rules,rag] [--repeat N] --dataset d
      [--llm fake|openai] [--models-file p]`; without `--models` the Run 2/3 mode compare is unchanged; `--modes`
      without `--models` -> "--modes yalnız --models ile kullanılır." exit 2). Per model, in the order given:
      `--llm openai` -> `llm.ping(profile)` (`models.list()` with `config.PING_TIMEOUT_S`); down -> print "⚠ <model>:
      uç nokta yanıt vermiyor (<url>) — bu blok atlandı; GPU'da bu modeli açıp yeniden koşun." and record it in
      `skipped`; up -> each mode x repeat through `runner.run_eval(..., budget=prompt_limit)`. `--llm fake` skips the
      ping and replays the golden through the same budget, so a fake compare already shows which mode fits which
      window (deterministic dry run). Output `eval_out/compare_<dataset>_<YYYYmmdd-HHMMSS>.json|md` (directly under
      eval_out, as the brief names it): model x mode cells with accuracy mean/min/max over repeats, answered %
      (status submitted), peak estimate vs budget, peak server tokens, overflows, trimmed, seconds per question,
      per-tag mean/min/max, and per-question outcomes. All blocks skipped -> no report, exit 3; else exit 0.
      The GPU holds one heavy model at a time: README tells to run Strata and the 27B one after the other.
R4-14. **What the user sees (CLI states)**: every command with `--dataset` prints "Veri kümesi: <display_name>
      (<name>)" as its first line; build-db on wwi prints the same table/token lines as synthetic; `ask --model`
      prints "Model: qwen27b-16k (unsloth/Qwen3.8-27B-GGUF, bütçe 16.384 token)"; a trimmed run adds a step-less
      note "✂ bağlam: N araç cevabı kısaltıldı"; an overflow prints "Cevap gönderilmedi: Bağlam bütçesi aşıldı:
      ..." (exit 1, like no_submission); the eval progress line shows `context_overflow` like the other
      outcomes; report.md gains "Model profili: <name> · bütçe B · tepe tahmin P · taşma O". The model compare
      prints one line per cell "<model> | <mode> | 18/26 (ort.) | cevap %92 | tepe 14.2K/16.4K | taşma 2 | 9.1
      sn/soru", the skipped lines, then the report path. Unknown profile -> "Bilinmeyen model profili: x
      (bilinenler: qwen27b-16k, qwen27b-24k, strata)" exit 2. A foreign index -> R4-8 message, exit 2.
R4-15. **Test rule kept** (brief §0, R3-12): tests over golden sets, datasets or profiles assert structure, never a
      count; tests never call a real model or a real SQL Server; the ping is tested on a closed localhost port.

## Contracts (Run 4 additions)

| Shape | Producer -> Consumer | Fields (optional = default) |
|---|---|---|
| dataset.json | `datasets/<name>/` -> nl2sql/datasets.py | `{"name", "display_name"=name, "dialect"="tsql", "connection"="sqlite" ("sqlite"\|"mssql"), "default_schema"=null, "as_of", "seed"=42, "files":{"schema"="schema.json","rules"="rules.json","profile"="profile.json","golden"="golden.jsonl","traps"=null}, "builder" ("mod:attr"\|"file.py:attr", `build_db(seed, db_path, sql_path) -> checksum`), "generator" (`generate(seed) -> Dataset rows`), "references" (`REFERENCES` dict), "fake_fallback_sql"=first golden SQL, "outputs":{"db","mssql_script","index_dir","eval_out"} (R4-3 defaults)}` |
| `Dataset` | datasets.load_dataset -> CLI, runner, tests | frozen: `name, display_name, dialect, connection, default_schema, as_of, seed, root: Path, schema_path, rules_path, profile_path, golden_path, traps_path: Path\|None, db_path, mssql_script, index_dir, eval_out, fake_fallback_sql`; methods `build_db(seed=None, db_path=None, sql_path=None)`, `generate(seed=None)`, `references() -> dict`, `schema()`, `rules()`, `golden()` (runner.load_golden defaults) |
| table name | schema.json -> doc, policy, executor, graph, index, pii, login script | `"Schema.Table"` outside `default_schema`, bare inside; fk `"Schema.Table.Column"` (split with `doc.split_fk`) |
| column (ext.) | schema.json -> doc, index.docs, policy, login_script | + `deny`=false |
| `PolicyResult.tables` (ext.) | policy -> executor, tests | upper-cased FULL names (`SALES.ORDERS`) |
| index meta (ext.) | build-index -> FileStore.load_checked | + `dataset`="synthetic_erp" when absent |
| models.json | `config/models.json` -> llm.load_profiles | `{"profiles":{name:{"base_url","model","api_key_env"=null,"context_budget":int,"max_output_tokens"=4096,"sampling"={} (temperature, top_p, ...),"enable_thinking"=config.ENABLE_THINKING,"auto_full_max_tokens"=null,"description"=""}}}` |
| `ModelProfile` | llm -> CLI, loop (via budget), compare_models | frozen: `name, base_url, model, api_key_env, context_budget, max_output_tokens, sampling, enable_thinking, auto_full_max_tokens, description`; property `prompt_limit = context_budget - max_output_tokens` |
| `ToolContext` (ext.) | caller -> loop -> modes | + `as_of`=config.AS_OF |
| `run_agent` kwarg | caller -> loop | + `budget: int\|None`=None (prompt limit in tokens) |
| `AgentRun` (ext.) | loop -> runner, CLI | status + "context_overflow"; + `peak_estimate`=0, `trimmed`=0, `overflows`=0 |
| `QuestionResult` (ext.) | runner -> report, compare_models | outcome + "context_overflow"; + `peak_estimate`=0, `trimmed`=0, `overflows`=0, `submitted`=False |
| report.json (ext.) | report -> report.md, compare | + `"dataset"`="synthetic_erp", `"profile"`: {"name","model","context_budget","max_output_tokens"} \| null; `context` + `peak_estimate`, `overflows`; `config.fingerprint` gains `"budget"` and `"dataset"` ONLY when not default/None, so Run 3 fingerprints stay byte-equal and `latest` reuse keeps working |
| model compare report | compare_models -> json/md, CLI | `{"timestamp","dataset","questions":int,"repeat":int,"models":[name],"modes":[name],"cells":{model:{mode:{"profile":{"model","context_budget","prompt_limit"},"scores":{"mean","min","max"},"answered_pct","peak_estimate","peak_reported","overflows","trimmed","seconds_per_question","tags":{tag:{"mean","min","max"}},"outcomes":{qid:[outcome per repeat]}}}},"skipped":{model: reason}}` |
| bypass case (WWI) | `tests/data/pii_bypass_wwi.jsonl` -> test | Run 3 bypass shape; `expect` + "denied" (policy rejects a `deny` column) |

## Run 4 milestones

- **M11 - Datasets** (T121-T135): config, the paths-only move, dataset loader, a qualified mini fixture dataset,
  qualified names through doc/policy/executor/build/introspect/pii/login/index/graph/tools/CLI, index meta
  dataset, `--dataset` on every command. Integration: real loader -> real builder -> real executor -> golden ==
  references for synthetic_erp and the mini dataset; build-index on one dataset refused by the other.
- **M12 - WWI** (T136-T145): schema + deny columns, fixture builder with traps, profile + rules, traps + golden +
  references, PII bypass on WWI names. Integration: real WWI builder -> executor -> every golden == reference;
  build-index + eval-retrieval + eval (fake) on wwi end to end.
- **M13 - Models + budget** (T146-T155): profiles, budget estimate/trim, loop enforcement, outcome wiring, `--model`
  and auto per profile, ping + compare report, CLI compare, README Run 4 + "27B test", smoke. Integration: real
  profiles file + real loop + FakeLLM + real executor through the model compare on wwi and synthetic_erp, a tiny
  budget profile shows overflows in the table.

---

# PLAN - NL2SQL Run 5 (Bilgin web UI: evidence, charts, written answer, clarification)

Source: `PROJECT_BRIEF_RUN5.md`. Everything above stays valid unless a numbered "Run 5 decision" says it changes.
Stack: Run 4 + **fastapi 0.162.0, uvicorn 0.54.0** (dependencies) and **httpx 0.28.1** (dev, TestClient) in `.venv`;
`web/` with **react 19.3.1, react-dom 19.3.1, echarts 6.1.0** and dev **vite 8.3.5, vitest 5.0.5** (all pinned exact,
installed before the run). Nothing else: no TypeScript, no @vitejs/plugin-react, no jsdom/testing-library, no router,
no CSS framework, no CDN (the built UI loads only its own files - nothing leaves the machine).
**Changes Decision 14:** the product now has screens, so `.hybrid/visual.json` exists (R5-17).

## Run 5 architecture

```
Browser (web/ React, built into nl2sql/web/static) --fetch /api/*--> nl2sql/web/app.py (FastAPI, 127.0.0.1 only)
                                                                          |
CLI `ask --json` -------------------------------------------------------> nl2sql/app/ask.py ask_payload(session, ...)
                                                                          |  (ONE code path for CLI and API)
nl2sql/app/session.py open_session(dataset, model, llm, paths) -> Session |
   reuses cli.main: resolve_auto, _context, make_client, build_index      v
                         agent loop (run_agent, + ask_clarification tool when ctx.clarify)
                           |                                   |
                needs_clarification                     submitted SQL
                           |                                   v
                           |        LocalExecutor.execute(Budget(UI_MAX_ROWS)) -> Result (+ tables, masked)
                           |                                   v
                           |        engine/checks.post_checks -> warnings (code only, nothing "fixed")
                           |        report/chart.chart_spec  -> ECharts option (code only) | None
                           |        report/facts.compute_facts -> facts (code only)
                           |        report/narrate.narrate(LLM) -> report/guard.check_text -> retry 1x -> template
                           v                                   v
                      AskPayload  --> app/asklog.record_ask -> logs/asks.jsonl (no rows)
export: asks.jsonl[audit_id].sql -> executor again (Budget(EXPORT_MAX_ROWS)) -> report/export csv|xlsx
rules:  /api/rules -> schema_map/rules_edit (validate, atomic save) -> content_hash changes -> index stale (R2-9)
eval --ambiguous: golden + ambiguous.jsonl through run_eval(clarify=True) -> eval/metrics -> report.json "metrics"
index: index/summaries.table_summaries -> collection "summaries"; search_tables(summaries=on|off); eval-retrieval
```

## Run 5 file layout additions

```
nl2sql/app/      __init__.py session.py (Session, open_session, SessionError) ask.py (ask_payload)
                 asklog.py (new_audit_id, record_ask, history, find_ask)
nl2sql/web/      __init__.py app.py (create_app, routes) saved.py (SavedStore, SQLite) static/ (built, ignored)
nl2sql/report/   __init__.py fmt.py shape.py chart.py facts.py guard.py narrate.py export.py
nl2sql/engine/checks.py          post-execution warnings
nl2sql/schema_map/rules_edit.py  validate_rule, save_rules
nl2sql/eval/metrics.py           answered/wrong/clarification metrics
nl2sql/index/summaries.py        deterministic table summary documents
datasets/synthetic_erp/ambiguous.jsonl   >= 6 ambiguous questions (dataset.json files.ambiguous)
scripts/smoke_serve.py           starts `serve --llm fake`, calls the API, stops it (smoke)
web/  package.json (pinned) vite.config.js index.html src/{main.jsx App.jsx styles.css}
      src/lib/{route,format,api,steps,askState,chartFormat,rulesForm}.js  src/components/*.jsx  src/**/*.test.js(x)
data/bilgin.db (saved questions, ignored by data/*.db)   logs/asks.jsonl (ignored by logs/)
```

## Run 5 decisions

R5-1. **One code path.** `nl2sql/app/session.py` builds what a run needs once: `open_session(dataset=None, model=None,
      llm="openai", models_file=None, db_path=None, index_dir=None, audit_path=config.AUDIT_LOG,
      ask_log=config.ASK_LOG)` -> `Session` (dataset, schema, rules, executor with `pii_schema`, profile, budget,
      llm kind, index dir, `agent_llm(mode)`, `narrator()`, `context(mode)`, `reload_rules()`, `ping()`). It reuses
      `cli.main.resolve_auto`, `_context`, `make_client`, `build_index` (no copies). Import rule: `cli/main.py` imports
      `nl2sql.app` / `nl2sql.web` only inside the functions that need them, so there is no import cycle. Setup
      failures (unknown dataset/profile, missing key, missing DB) raise `SessionError(message, exit_code)` carrying
      the existing CLI sentences (NO_DB with `--dataset`, R4-10/R4-14 texts). `ask_payload(session, question,
      mode=None, choice=None)` is the only function that turns a question into an AskPayload; `ask --json` and
      `POST /api/ask` call it and nothing else. The human `ask` output (Run 1-4) stays as it is, plus the lines in
      R5-14. `resolve_auto` gains `notify=print`; the app passes a collector so its NO_INDEX_NOTE lands in
      `payload.notes` instead of stdout (`--json` prints JSON only).
R5-2. **Status mapping.** AgentRun `submitted` + final execution ok -> `answered`; `needs_clarification` ->
      `needs_clarification`; everything else (llm_error, no_submission, timeout, context_overflow, final SQL error,
      stale/missing index for rag) -> `failed` with `error {kind, message}` (kind = AgentRun status, `exec:<kind>`,
      or `index`) and `answer_text` = the Turkish message. The final SQL runs once more under
      `Budget(max_rows=config.UI_MAX_ROWS)` (200) with source `web:<audit_id>` / `cli:<audit_id>`.
      `tables_used` = `Result.tables` (new, R5-3); `rules_used` = ids of rules with >= 1 marker whose markers all
      match the SQL whitespace-collapsed and case-insensitive (`rules.matching_rules`, the R2-11 test rule, now in
      code) - a rule without markers is never claimed.
R5-3. **`Result.tables`** (sorted upper full names, from `PolicyResult.tables`) is filled by the executor on every
      backend for every successful run; error results keep `[]`. Display only - nothing decides on it.
R5-4. **Ask log, not rows.** Every `ask_payload` call appends one line to `logs/asks.jsonl` (config.ASK_LOG, same
      ignore and no-rows rule as the audit log): audit_id (`uuid4().hex[:12]`), ts, source `web|cli`, dataset,
      mode, question, choice, status, sql, row_count, error kind. `/api/history` = last `config.HISTORY_N` (50)
      lines newest first (malformed lines skipped); export finds its SQL here. The executor audit lines of that
      ask carry `source = "<web|cli>:<audit_id>"`, so both logs join on the id. Brief "from the audit log" =
      this ask log next to audit.jsonl; the audit.jsonl entry shape (Run 1/3 contract) is unchanged.
R5-5. **Post-execution warnings** (`engine/checks.post_checks(sql, result, executor)` -> list[Warning], each
      `{code, message, column}`; a check that itself fails adds nothing and never fails the answer):
      `empty` (row_count 0), `all_null` (per column, over the returned rows, only when rows > 0), `top_limited`
      (row_count == config.TOP_N: the policy cap cut it; a user's own `TOP 5` never warns), `masked` (one warning
      listing masked columns), `fan_out`: outermost SELECT (no UNION/CTE) with >= 1 JOIN and an aggregate ->
      `SELECT COUNT(*) FROM <from+joins> <where>` vs `SELECT COUNT(*) FROM <driving table> <alias> <where-conjuncts
      that reference only the driving alias>`, both through the executor (policy + audit, source `checks`);
      joined/driving > `config.FANOUT_FACTOR` (3.0) -> warning. Messages Turkish (Contracts). Never rewrite SQL.
R5-6. **Chart chosen by code** (`report/shape.py` + `report/chart.py`). Column kinds: `date` (all non-null values
      ISO `YYYY-MM-DD`/`YYYY-MM` strings, or folded name in AY/YIL/DONEM/TARIH/MONTH/YEAR/DATE with int values),
      `number` (int/float, not bool, name not code-like), `code` (code-like name: ends with KOD/KODU/ID/NO,
      `_ID`, `ID`), `category` (other text). Category pick: text columns minus code-like ones, then the first; if
      only code columns, the first code column. Rules in order: <= 1 row -> none; exactly one date + 1-3 numbers
      -> `line` (x ascending); one category + exactly one number + rows <= `CHART_BAR_MAX_ROWS` (20): share
      question (folded question contains pay, oran, yüzde, dağılım, share, pasta) + rows <= `CHART_PIE_MAX_PARTS`
      (6) + all values > 0 -> `pie`, else `bar` sorted descending; exactly two numbers, no date, scatter asked
      (ilişki, korelasyon, saçılım, scatter) -> `scatter`; else none. Output `{"type", "option"}` where option is
      plain ECharts JSON (tooltip, grid, xAxis/yAxis or none for pie, series with data from the result) plus
      `"bilgin": {"value_format": "number"|"percent", "value_column", "label_column"}`; the frontend only attaches
      tr-TR formatter functions named by `value_format` (JSON cannot carry functions). `validate_option(option)`
      -> list of problems (the "schema check" of brief test 2; tests require []).
R5-7. **Facts by code** (`report/facts.compute_facts(columns, rows)` -> list[Fact]): `row_count`; per number column
      `total`, `max` + its row label, `min`, `mean` (2 dp); with a category column: `top_item` and `top_share`
      (% of the column total, only when all values >= 0 and total > 0); with a date column and >= 2 periods:
      `last_period`, `previous_period`, `change` and `change_pct` (last vs previous, sorted by the date value).
      Each Fact has `display` in Turkish format (`report/fmt`). Masked or non-numeric cells are skipped.
R5-8. **Number guard** (`report/guard.py`): `extract_numbers(text)` finds `1.234,56`, `1234`, `12,5`, `-3`, `%12`,
      `%12,5`, `12,5 bin|milyon|milyar` (scale 1e3/1e6/1e9), ignores digits glued to letters (`STK001`, `Q3`) and
      flags English forms (`1,234.56`, `12.5`, dot + 1-2 digits) as `format`. Allowed values = numeric result cells
      (all returned rows), integers inside text cells and ISO dates (year, month, day), `row_count`, every Fact
      value, numbers in the question. A number with d shown decimals at scale s matches v iff
      `|n - v| <= config.NUMBER_TOLERANCE_UNITS * 10^-d * s` (0.5 = honest rounding of the last shown digit), a
      percent matches percent facts. `check_text(text, allowed)` -> `GuardResult(ok, offending: [raw])`.
R5-9. **Narration** (`report/narrate.narrate(question, columns, rows, facts, llm)` -> `Narration(text, source,
      rejected)`): the LLM (same client kind as the agent, no tools) gets the question, column names, up to
      `config.NARRATE_MAX_ROWS` (20) masked rows and the facts with their `display`, and must write 1-3 Turkish
      sentences using only those numbers. Guard fails -> one retry naming the offending numbers ("Şu sayılar
      sonuçta yok: ..."); fails again, or LLMError -> `template_sentence(question, facts)` (deterministic, always
      passes the guard; tested). `source` = `llm` | `llm_retry` | `template`. Empty result -> template without an
      LLM call. A failing text is never returned. Fake: `fake.narration_client()` writes a sentence from the first
      facts' `display` (deterministic, passes); `fake.inventing_narrator()` / `rounding_narrator()` for tests.
R5-10. **Clarification tool** `ask_clarification(question, options[])`: offered only when `ToolContext.clarify` is
      True (default False, so every Run 1-4 caller, prompt and fingerprint is unchanged); the loop sends
      `mode.tools + [ASK_CLARIFICATION]` and `dispatch` accepts it; the system prompt appends
      `prompt.CLARIFY_RULES` (ask only when a business term is undefined by the rules AND two readings give
      different numbers - "satış" brüt vs net, iptaller dahil mi; never when a rule defines the term; in rag call
      search_rules first; 2-4 short mutually exclusive options; never guess). Valid args (non-empty question,
      2..`config.CLARIFY_MAX_OPTIONS` (4) distinct non-empty options) -> run ends `needs_clarification` with
      `AgentRun.clarification = {question, options}`; invalid -> ERROR_PREFIX answer, the run goes on. `ask`, `ask
      --json` and the API set clarify=True; a follow-up never does (no clarification loop).
R5-11. **Follow-up.** `clarify.follow_up_text(question, choice)` = `"{question}\n\nKullanıcının seçtiği anlam:
      {choice}"`; `ask_payload(..., choice=...)` runs it as a normal question (clarify off) and the ask record keeps
      `question` and `choice` separately. API body `{"question", "mode"?, "choice"?}`; CLI `ask "<q>" --choice
      "<option>"`. Fake: `for_golden(..., ambiguous=lines)` answers an ambiguous question with ask_clarification
      (options = reading labels) and its follow-up with that reading's SQL; golden questions replay as before.
R5-12. **Ambiguous set + metrics.** `datasets/synthetic_erp/ambiguous.jsonl` (dataset.json `files.ambiguous`,
      optional, default null): >= 6 lines `{"id":"A01","question","expect":"clarify","term","readings":[{"label",
      "sql"}] (>= 2),"notes"}`; every pair of readings returns different results on the built DB (test); A01 is
      exactly "Eylül 2026'da satışlarımız ne kadar?" (visual flow). No reading SQL text in the index (leak test).
      `eval --ambiguous` = golden + ambiguous through `run_eval(..., clarify=True)`; runner outcomes gain
      `needs_clarification` (OUTCOMES 9 -> 10, **changes** the pinned count in tests/test_eval_runner.py again);
      ambiguous lines get `clarified` | `guessed` | a failure outcome (`AMBIGUOUS_OUTCOMES`). `eval/metrics.py`
      per run (= per mode): accuracy = pass/golden; answered_pct = submitted/golden; accuracy_when_answered =
      pass/answered (null when 0); wrong_answer_rate = (answered - pass)/golden; clarify_precision = clarified
      ambiguous / all clarifications (null when none); clarify_recall = clarified/ambiguous. A clarification on a
      golden question = not answered (brief rule). `eval --ambiguous` on a dataset without the file -> "Bu veri
      kümesinin belirsiz soru seti yok." exit 2; with `--compare` -> "--ambiguous tek mod eval'i içindir." exit 2.
      Fingerprint gains `"clarify": true` only when on (R4 rule: old fingerprints stay byte-equal).
R5-13. **Narration measured** (brief §9): `eval --narrate` narrates every submitted golden answer and the report gains
      `narration: {"llm", "llm_retry", "template", "template_pct"}`; README states the number from a real run is
      measured by hand (tests use the fake narrator).
R5-14. **CLI states.** `ask` (human) adds `Cevap: <answer_text>` after the table when narration ran, the warnings
      as `⚠ ...` lines, and for a clarification prints `Netleştirme: <question>` + numbered options + `Seçmek için:
      ask "<q>" --choice "<seçenek>"` (exit 0). `ask --json` prints only the payload (ensure_ascii False, indent
      2); exit 0 answered/needs_clarification, 1 failed, setup errors keep their one line and exit 2. `serve`
      prints `Bilgin: http://127.0.0.1:8777  (veri kümesi ..., model ..., llm fake|openai)`; a non-loopback
      `--host` -> "Bilgin yalnız 127.0.0.1 üzerinde çalışır (tek kullanıcı, kimlik doğrulama yok)." exit 2.
      `eval --ambiguous` prints the metrics block (Doğruluk, Cevaplanan %, Cevaplananlarda doğruluk, Yanlış cevap
      oranı, Netleştirme kesinliği / duyarlılığı); report.md gets the same table.
R5-15. **Web API** (FastAPI, `create_app(session, saved_path, static_dir)`; single user, no auth, CORS off, binds
      127.0.0.1 - README says so). Routes: `POST /api/ask`, `GET /api/health`, `GET /api/examples` (first
      `config.EXAMPLES_N` (4) golden questions + the first ambiguous one), `GET /api/tables`, `GET/POST
      /api/saved`, `DELETE /api/saved/{id}`, `GET /api/history`, `GET /api/export/{audit_id}.csv|.xlsx`, `GET/POST
      /api/rules`, `PUT/DELETE /api/rules/{id}`, `POST /api/index/rebuild`, `/` + `/assets/*` static. Errors:
      empty question 400 `{"detail": "Soru boş."}`; unknown audit_id/saved/rule 404; export of a non-answered ask or
      another dataset's ask 409; rule validation 422 `{"errors":[{"field","message"}]}`; duplicate rule id 409.
      Agent outcomes are 200 with `status` in the body. Static missing -> `/` returns a small Turkish HTML page
      "Arayüz derlenmemiş: `npm --prefix web run build` çalıştırın." (API works without node).
R5-16. **Saved, export, rules.** Saved questions: SQLite `config.APP_DB_PATH` (`data/bilgin.db`, never the analysed
      DB), table `saved(id, question, mode, sql, dataset, created_at)` - question text and SQL only. Export re-runs
      the ask log SQL through the session executor (`Budget(config.EXPORT_MAX_ROWS)`, source `export:<id>`, PII
      masked) and streams CSV (UTF-8 BOM, `;`, `\r\n`, decimal comma, no thousands separator, NULL empty) or XLSX
      (openpyxl, numeric cells numeric, bold header, `bilgin_<audit_id>.<ext>`). Rules edits write the served
      dataset's `rules.json` (atomic temp+replace, `{"rules": [...]}`, indent 2, UTF-8, order kept) after
      `rules_edit.validate_rule` (id `^[a-z0-9_]+$` unique, term + definition non-empty, synonyms/tables/markers
      lists of strings, tables exist in the schema, markers compile); the brief's `name` field is the existing
      `term`. The changed content hash makes the index stale by R2-9 (no flag file); `GET /api/rules` and health
      report `index.fresh`; `POST /api/index/rebuild` calls `build_index` with the embedder of the current meta
      (none -> `fake` under `--llm fake`, else `openai`) and reloads the session's search. README: on the demo
      datasets the rules screen edits committed files - restore with git.
R5-17. **Frontend** (`web/`, plain JS + JSX, React 19, ECharts 6 imported from node_modules; Vite builds to
      `../nl2sql/web/static` with `emptyOutDir`, dev proxy `/api` -> 127.0.0.1:8777; JSX automatic runtime via
      Vite's built-in transform). Tests: vitest in node environment - pure modules in `src/lib` and components
      rendered with `react-dom/server` `renderToStaticMarkup`. Hash routes: `#/` (Sor), `#/kurallar` (Kurallar).
      Design, states, ids and the phone fallback: R5-18. `.hybrid/visual.json` flows: R5-19.
R5-18. **What the user sees (web).** Tokens on `:root` (light) + `prefers-color-scheme: dark`: `--bg #F6F5F1`,
      `--surface #FFFFFF`, `--text #1D1D1B`, `--muted #6A6963`, `--line #E3E1DA`, `--accent #1F5FAD`, `--warn-bg
      #FEF3C7`, `--warn-line #F59E0B`, `--warn-text #8A3B05`, `--err-bg #FDECEC`, `--err-text #9B1C1C`, `--ok
      #2F7D32`; system-ui font stack, numbers `tabular-nums`, answer text 20px/1.5, 8px spacing grid, radius 10px.
      - Header: "Bilgin" wordmark, dataset + model chip (from health), nav `#nav-ask` / `#nav-rules`, health dot
        (green ok, amber index stale, red model down) with a tooltip sentence.
      - Layout >= 960px: sidebar 280px (`#saved-list`, `#history-list`) + main column max 880px. < 720px: one
        column, sidebar collapses behind `#sidebar-toggle` ("Kayıtlılar ve geçmiş") above the question box, tables
        scroll inside `.table-wrap` (no page-level horizontal scroll), chart height 260px. (Brief: a mobile app is
        out; the layout must just not break at 375px.)
      - Ask: `#question` textarea (Enter sends, Shift+Enter newline), `#ask-button`, `.example-chip` buttons.
      - Empty state (no ask yet): "Verinize Türkçe soru sorun" + "Bilgin SQL'i yazar, sonucu ve nasıl hesapladığını
        gösterir." + example chips.
      - Loading: `#loading` skeleton card + step text from `lib/steps.js` ("Soru okunuyor", "Şema aranıyor", "SQL
        çalıştırılıyor", "Cevap yazılıyor"), advancing every 1.2 s and stopping on the last (labelled progress,
        not server events); the ask button disabled.
      - Answer card `#answer-card`: status line (✓ Cevaplandı · mod · süre), `#answer-text`, `#warnings` (amber
        band, ⚠ per warning), `#chart` (only when `chart`), `#result-table` (sticky header, numbers right-aligned in
        tr-TR, NULL "–", first 200 rows, footer "İlk 200 satır gösteriliyor (toplam 1.234)"), `#export-csv`,
        `#export-xlsx` ("Tamamını indir"), `#save-question`, `#evidence-toggle` -> `#evidence` "Nasıl hesapladım"
        (SQL block + copy, tables, rules, mode, masked columns, facts, steps, audit id, timings, notes).
        Empty result: the `empty` warning + "Bu soruya uyan kayıt yok." in place of the table.
      - Clarification `#clarification-card`: "Netleştirelim", the question, options as `button[data-option-index]`,
        secondary "Soruyu değiştir" (focuses `#question`).
      - Error `#error-card` per kind: llm_error "Model yanıt vermiyor" + Strata hint; index "İndeks eski" + rebuild
        button; failed run "Cevap üretilemedi" + the reason; network "Sunucuya ulaşılamadı".
      - Sidebar: saved items (click = ask again, × delete), empty "Henüz kayıtlı soru yok."; history newest first
        with ✓ / ? / ✗, empty "Geçmiş boş.".
      - Rules screen `#rules-screen`: "İş kuralları", `#rule-add`, stale banner `#index-stale` "Kurallar değişti,
        indeks eski." + `#index-rebuild` ("kuruluyor…", then "İndeks güncel."), table (Terim, Eş anlamlılar,
        Tablolar, Düzenle / Sil with inline "Silinsin mi? Evet / Vazgeç"), form `#rule-form` (id - locked when
        editing, term, synonyms comma-separated, definition, sql_hint, tables with a datalist from /api/tables),
        `#rule-save`, field errors under each field and the summary `#rule-errors` from the 422 body; client-side
        required-field checks in `lib/rulesForm.js` mirror the server messages.
R5-19. **Visual flows** (`.hybrid/visual.json`, start builds the DB, the fake index and the UI, then `serve --llm
      fake --port 8777`): landing (empty state), golden ask (Q02 -> answer + bar chart, then evidence open),
      ambiguous ask (A01 -> clarification -> option 0 -> answer), export (answer then the CSV/Excel buttons),
      history/saved (save, then sidebar), rules screen (list, add form, submit empty -> validation messages).
R5-20. **Table summaries** (`index/summaries.table_summaries(schema, rules, graph)` -> one Doc per table, id
      `summary:<TABLE>`, collection `summaries`, meta.table): description, key columns (fk columns + code-like
      columns, max `config.SUMMARY_KEY_COLUMNS` (8), with descriptions, never deny columns), rule terms whose
      `tables` include it, 1-hop join neighbours (data tables via the graph). Built deterministically, always
      written by build-index (COLLECTIONS gains "summaries"; content_hash unchanged - same schema + rules);
      leakage rule R2-16 applies. `HybridSearch.search_tables(query, k, summaries)` = `search(..., "tables")`
      when off; on = RRF of the table ranking and the summary ranking mapped to `table:<name>`. `eval-retrieval
      --summaries on|off` (default off) adds variant `summaries` to the report (recall@k with and without).
      **Decision rule, fixed now:** `config.TABLE_SUMMARIES` = True iff hybrid recall@5 with summaries >= without
      on BOTH datasets with FakeEmbedder (T192 measures, sets the constant, writes the numbers into
      README); `search_schema` follows the constant. Never tune the eval or the summaries to flip it.
R5-21. **PII group bypass:** `SELECT p.DEPARTMAN_KODU, AVG(m.NET_TUTAR) FROM TBLMAAS m JOIN TBLPERSONEL p ON
      m.PERSONEL_KODU = p.PERSONEL_KODU GROUP BY p.DEPARTMAN_KODU` over a department with exactly one person stays
      masked (AVG over salary is not whitelisted, R3-6); a test proves it on the built DB, fix if red.
R5-22. **Test rules kept** (R3-12/R4-15): structure over counts, no real model, no real SQL Server, no network but
      127.0.0.1 in the smoke script; API tests use TestClient with tmp DB/index/logs/saved paths and tmp copies of
      the dataset folder whenever rules are edited (never the committed rules.json).

## Contracts (Run 5 additions)

| Shape | Producer -> Consumer | Fields (optional = default) |
|---|---|---|
| `Result` (ext.) | executor -> app.ask, checks, export | + `tables: list[str]`=[] (upper full names, sorted) |
| `Warning` | checks.post_checks -> AskPayload, CLI, UI | `{"code": "empty"\|"all_null"\|"top_limited"\|"masked"\|"fan_out", "message": str (Turkish), "column": str\|null=null}`; messages: "Sonuç boş: bu koşullara uyan kayıt yok." / "'{col}' kolonunun tüm değerleri boş (NULL)." / "Sonuç {n} satırlık üst sınırda kesildi; tamamı daha fazla olabilir." / "Maskelendi: {cols} — kişisel veri gösterilmez." / "Join sonrası {joined} satır, sürücü tablo {table} {driving} satır ({ratio}x): toplamlar çoğalmış olabilir." |
| `ChartSpec` | chart.chart_spec -> AskPayload, UI ChartView | `null` or `{"type": "line"\|"bar"\|"pie"\|"scatter", "option": ECharts option JSON + "bilgin": {"value_format": "number"\|"percent", "value_column": str, "label_column": str\|null}}` |
| `Fact` | facts.compute_facts -> narrate, guard, AskPayload | `{"name": "row_count"\|"total"\|"max"\|"min"\|"mean"\|"top_item"\|"top_share"\|"last_period"\|"previous_period"\|"change"\|"change_pct", "label": str (Turkish), "column": str\|null=null, "value": number\|str, "display": str (tr format), "percent": bool=false}` |
| `GuardResult` | guard.check_text -> narrate | `ok: bool`, `offending: list[str]` (raw tokens, text order), `numbers: list[NumberToken(raw, value, decimals, scale, percent, format_error)]` |
| `Narration` | narrate -> AskPayload, eval | `text: str`, `source: "llm"\|"llm_retry"\|"template"`, `rejected: list[str]`=[] (offending tokens of failed attempts) |
| `AgentRun` (ext.) | loop -> app.ask, runner | status + "needs_clarification"; + `clarification: {"question","options":[str]}\|None`=None |
| `ToolContext` (ext.) | caller -> loop, dispatch | + `clarify: bool`=False |
| ask_clarification args | model -> dispatch | `{"question": str, "options": [str] (2..CLARIFY_MAX_OPTIONS, distinct, non-empty)}` |
| AskPayload | app.ask.ask_payload -> `ask --json`, `/api/ask`, UI | `{"status": "answered"\|"needs_clarification"\|"failed", "question", "choice"=null, "answer_text"="", "narration_source"=null, "chart"=null, "facts"=[], "columns"=[], "rows"=[] (<= UI_MAX_ROWS, JSON scalars, masked), "row_count"=0, "truncated"=false, "sql"="", "tables_used"=[], "rules_used"=[], "masked_columns"=[], "warnings"=[Warning], "notes"=[str], "mode", "dataset", "model" (profile name or "fake"/"openai"), "timings": {"agent_s","execute_ms","narrate_s","total_s"} (0 when not run), "audit_id", "clarification"=null {"question","options"}, "error"=null {"kind","message"}, "steps"=[{"tool","ok","summary" (<= 300 chars)}]}` - same keys in every status |
| ask record | asklog.record_ask -> logs/asks.jsonl, history, export | `{"ts","audit_id","source":"web"\|"cli","dataset","mode","question","choice"=null,"status","sql"="","row_count"=0,"error"=null (kind)}` - never rows |
| history item | `/api/history` -> UI | ask record minus `source`, newest first, <= HISTORY_N |
| saved question | SavedStore -> `/api/saved`, UI | `{"id": int, "question", "mode"=null, "sql"=null, "dataset", "created_at"}`; POST body `{"question", "mode"?, "sql"?}` |
| health | `/api/health` -> UI header | `{"status":"ok","dataset":{"name","display_name"},"llm":{"kind","model","url"=null,"reachable":bool,"reason"=null},"index":{"fresh":bool,"reason"=null,"embedder"=null},"schema_hash","rules_hash","mode":{"default":"auto","auto_full_max_tokens":int,"estimate":int},"budget"=null}` |
| rules API | `/api/rules` -> UI | GET `{"rules":[rule],"index":{"fresh","reason"}}`; POST/PUT body = rule (rules doc shape); 200 -> same as GET; 422 `{"errors":[{"field","message"}]}` |
| rebuild | `/api/index/rebuild` -> UI | `{"index":{"fresh":true,"reason":null,"embedder"},"counts":{collection:int},"seconds":float}` |
| examples | `/api/examples` -> UI | `{"examples":[{"question","kind":"golden"\|"ambiguous"}]}` |
| export file | report.export -> `/api/export` | CSV: BOM + `;` + `\r\n`, header = columns, decimal comma; XLSX: one sheet "Sonuç"; both masked as the executor returned them |
| ambiguous line | `datasets/<ds>/ambiguous.jsonl` -> runner, fake, tests | `{"id":"A01","question","expect":"clarify","term","readings":[{"label","sql"}],"notes"=""}` |
| dataset.json (ext.) | datasets.load_dataset | `files` + `"ambiguous"`=null; `Dataset` + `ambiguous_path: Path\|None`, `ambiguous() -> list[dict]` ([] when none) |
| `QuestionResult` (ext.) | runner -> report, metrics | outcome + "needs_clarification" (golden), "clarified"\|"guessed" (ambiguous); + `kind: "golden"\|"ambiguous"`="golden", `clarification`=None, `narration_source`=None |
| metrics | eval.metrics -> report.json/md, CLI | `{"accuracy","answered_pct","accuracy_when_answered"\|null,"wrong_answer_rate","clarify_precision"\|null,"clarify_recall"\|null,"golden":int,"ambiguous":int}` (fractions 0-1, 4 dp) |
| report.json (ext.) | report -> report.md | + `"metrics"` (always; clarify fields null without --ambiguous), + `"narration"`=null `{"llm","llm_retry","template","template_pct"}`; fingerprint + `"clarify": true` only when on |
| summary Doc | index.summaries -> store, search | `id "summary:<TABLE>"`, collection `"summaries"`, title = table, meta `{"table"}` |
| retrieval report (ext.) | eval.retrieval -> CLI, report | + `"summaries": bool`; `variants` + `"summaries"` when `--summaries on` |

## Run 5 milestones

- **M14 - API + evidence** (T163-T174): config, Result.tables + warnings, fan-out, session, ask log, ask_payload,
  `ask --json`, FastAPI app + health/ask + serve, saved/history, export, smoke script. Integration: real session ->
  real FakeLLM -> real loop -> real executor -> real checks -> payload equal from `ask --json` and `/api/ask`;
  export of that audit id re-runs and stays masked.
- **M15 - Report** (T175-T183): fmt + shape, chart, facts, number guard, narrate + fake narrators, payload wiring,
  rules validation + save, rules API + stale/rebuild. Integration: real executor result -> real chart/facts/
  narrate/guard through `/api/ask`; a rules edit via the API makes the real index stale and rebuild clears it.
- **M16 - Clarification + eval + retrieval** (T184-T194): tool + loop, fake ambiguous replay, payload/CLI follow-up,
  ambiguous set, outcomes + metrics, eval --ambiguous/--narrate, summaries, search + eval-retrieval, the measured
  decision, PII group test. Integration: real eval --ambiguous through the real loop; real ask -> clarification ->
  follow-up answered through the API; eval-retrieval with/without summaries on both datasets.
- **M17 - Frontend** (T195-T204): scaffold + tokens + router, format/api libs, ask + states, answer card, chart,
  clarification, sidebar, rules screen, static serving + visual.json + README, smoke + integration (pytest +
  vitest + build + served UI).

## Run 6 architecture

```
Browser --cookie bilgin_oturum--> nl2sql/web/app.py create_app(session, saved_path, static_dir, users=None)
   web/src/main.jsx -> Root.jsx (auth gate: GET /api/auth/me first, LoginScreen or App)
                                   |
             nl2sql/web/authz.py   current_user(request) -> User|None ; require("public"|"user"|"admin")
                                   ROUTE_ROLES {(method, path): level}  (one table, every route)
                                   |
   nl2sql/auth/  passwords.py (scrypt)  store.py UserStore(app DB: users, sessions, login_failures, settings)
                 bootstrap.py (NL2SQL_DEV_ADMIN_PASSWORD on an empty users table)
                                   |
   per-user: ask_payload(..., username) -> ask record.username, audit source <src>:<user>:<id>
             history / replay / export / saved filtered by username (admin: all)
                                   |
   admin:   /api/users*  (UserStore)          /api/rules writes, /api/index/rebuild (Run 5 code)
            /api/schema-map/template.xlsx  <- schema_map/template.py build_template(skeleton=None)
            /api/schema-map/preview        -> template_import.read_template + validate (+ merge.diff_map)
                                              -> data/map_previews/<id>.json (nothing else written)
            /api/schema-map/apply          -> schema_map/onboard.apply_preview -> real_datasets/<name>/ (new only)
                                              -> background thread cli.build_index -> status
            /api/datasets, /api/datasets/active -> open_session(name) -> app.state.session swapped, settings row
CLI (no login): ask/eval/import-map unchanged; `user add|list|passwd|set` on the same UserStore.
```

## Run 6 file layout additions

```
nl2sql/auth/        __init__.py passwords.py store.py bootstrap.py
nl2sql/web/         authz.py (ROUTE_ROLES, current_user, require) auth_api.py (login/logout/me, users API)
                    map_api.py (template, sample, preview, apply, status) datasets_api.py (list, switch, login script)
nl2sql/schema_map/  template.py (build_template, filled_example_workbook, header constants)
                    template_import.py (read_template, validate) onboard.py (previews, apply_preview, index job)
scripts/visual_serve.py   throwaway app DB + users for the visual flows, then `serve --llm fake`
scripts/smoke_onboard.py  template -> filled -> preview -> apply -> index -> switch -> ask (smoke)
web/src/Root.jsx  web/src/lib/{auth,usersForm,mapFlow,fileB64}.js
web/src/components/{LoginScreen,UsersScreen,MapScreen,DatasetList}.jsx
data/map_previews/ (ignored)  data/visual/ (ignored)  logs/map_changes.jsonl (ignored by logs/)
real_datasets/<name>/  dataset.json schema.json rules.json profile.json golden.jsonl real.py readonly_login.sql
                       (ignored: `real_datasets/*` + `!real_datasets/wwi_real/` - a customer's map never lands in git)
```

## Run 6 decisions

R6-1. **Config** (`nl2sql/config.py`, existing names unchanged): `PASSWORD_MIN_LEN=10`, `SCRYPT_N=2**14`,
      `SCRYPT_R=8`, `SCRYPT_P=1`, `SESSION_HOURS=12`, `SESSION_COOKIE="bilgin_oturum"`, `LOGIN_MAX_FAILURES=5`,
      `LOGIN_WINDOW_MIN=15`, `LOCKOUT_MIN=15`, `DEV_ADMIN_ENV="NL2SQL_DEV_ADMIN_PASSWORD"`, `MAP_MAX_BYTES=5*1024*1024`,
      `MAP_PREVIEW_TTL_MIN=30`, `MAP_PREVIEWS_DIR=ROOT/data/map_previews`, `MAP_CHANGES_LOG=ROOT/logs/map_changes.jsonl`,
      `REAL_DATASETS_DIR=ROOT/real_datasets`, `TEMPLATE_FILENAME="bilgin-veritabani-sablonu.xlsx"`,
      `TEMPLATE_VERSION="1"`, `DATASET_NAME_RE=r"^[a-z][a-z0-9_]{2,30}$"`; call-time env readers like
      `datasets_dir()`: `app_db_path()` (`NL2SQL_APP_DB` else `APP_DB_PATH`) and `real_datasets_dir()`
      (`NL2SQL_REAL_DATASETS_DIR` else `REAL_DATASETS_DIR`). Every Run 6 caller uses the readers, so tests, the
      smoke and the visual server run on throwaway files and never touch `data/bilgin.db` or `real_datasets/`.
R6-2. **Passwords** (`auth/passwords.py`, stdlib only): `hash_password(pw)` -> `scrypt$n$r$p$salt_b64$hash_b64`
      (16-byte `secrets.token_bytes` salt, dklen 32, maxmem large enough for n=2**14); `verify_password(pw, stored)`
      recomputes with the stored n/r/p and compares with `hmac.compare_digest`; a malformed stored value -> False,
      never an exception. `check_new_password(pw)` -> Turkish message or None ("Parola en az 10 karakter olmalı.").
R6-3. **UserStore** (`auth/store.py`, same SQLite file as saved questions, short-lived connections like
      `SavedStore`, `clock=time.time` injectable): tables `users(id, username UNIQUE, password_hash, role CHECK(role IN
      ('admin','user')), active INTEGER, created_at, last_login_at)`, `sessions(token_hash PRIMARY KEY, user_id,
      created_at, expires_at)`, `login_failures(username, ts)`, `settings(key PRIMARY KEY, value)`. Username rule
      `^[a-z0-9_.-]{3,32}$` (folded to lower). Errors are `UserError(message, status)` with Turkish messages: duplicate
      409 "Bu kullanıcı adı zaten var.", unknown 404 "Kullanıcı bulunamadı.", last admin 409 "Son etkin yönetici
      pasifleştirilemez ya da rolü düşürülemez.", bad role / name / short password 422. A password change or
      deactivation deletes that user's sessions. Public dicts never carry `password_hash`.
R6-4. **Login and lockout.** `authenticate(username, password)` -> User | raises `LoginError(message, status)`:
      unknown user, wrong password and inactive user give the same 401 "Kullanıcı adı ya da parola hatalı." and all
      record a failure row (so the lockout is no user-existence oracle); `LOGIN_MAX_FAILURES` failures inside
      `LOGIN_WINDOW_MIN` -> 429 "Çok fazla hatalı deneme. {n} dakika sonra yeniden deneyin." until the last failure +
      `LOCKOUT_MIN`, even with the right password; success clears that username's failures and sets
      `last_login_at`. `create_session(user)` -> raw token (`secrets.token_urlsafe(32)`), only `sha256(token)` hex is
      stored, expiry `SESSION_HOURS`; `session_user(token)` -> active User or None (expired rows deleted on read);
      `delete_session(token)`.
R6-5. **HTTP auth** (`web/authz.py`, `web/auth_api.py`). `create_app(session, saved_path=..., static_dir=...,
      users=None)`: `users=None` is the Run 5 single-user mode (no login, every route open, username None
      everywhere) - the ~86 existing API tests keep calling it that way unchanged. With a store: `POST
      /api/auth/login {username, password}` -> 200 `{username, role}` + cookie `bilgin_oturum` (HttpOnly,
      SameSite=Strict, Path=/, Max-Age = SESSION_HOURS*3600, no Secure: loopback http; README says so); `POST
      /api/auth/logout` deletes the session and the cookie (200 even without one); `GET /api/auth/me` -> `{username,
      role}` | 401. `require(level)` is one dependency factory; every route is declared with it and `ROUTE_ROLES`
      is the single table the brief's matrix lives in (public: `/`, `/assets/*`, `/api/auth/login`, `/api/auth/logout`;
      user: ask, replay, export, saved, history, examples, health, tables, GET rules, `/api/auth/me`; admin: rule
      writes, index rebuild, `/api/users*`, `/api/schema-map/*`, `/api/datasets*`). No session -> 401 "Oturum açmanız
      gerekiyor."; wrong role -> 403 "Bu işlem yalnız yöneticiye açık.". Bodies are always `{"detail": str}`.
      Passwords, hashes and tokens never reach a log, the ask log, the audit log or a response body.
R6-6. **SPA fallback.** Every GET that is not `/api/*` and not `/assets/*` returns the built `index.html` with
      `Cache-Control: no-cache` (or the Run 5 NO_UI page); unknown `/api/*` stays a JSON 404 and, with a store and no
      session, a 401. The UI decides what to show; the server never 404s a typed deep link.
R6-7. **serve** always builds `UserStore(config.app_db_path())` and passes it. Empty users table: if
      `NL2SQL_DEV_ADMIN_PASSWORD` is set (non-blank) `auth/bootstrap.dev_admin(store, environ)` creates `admin`/admin
      with that value (no minimum length for this path only), prints the brief's warning line, and never runs when
      a user exists; otherwise serve prints "Henüz kullanıcı yok: önce `python -m nl2sql user add <ad> --role admin`
      ile bir yönetici oluşturun." and exits 2 before listening. **Changes R5-15/R5-14:** the served app is no
      longer single-user; the non-loopback sentence becomes "Bilgin yalnız 127.0.0.1 üzerinde çalışır (TLS ve ağ
      erişimi kapsam dışı)." - the two existing serve tests (`tests/test_web_api.py::test_serve_*`,
      `tests/test_serve_default_dataset.py`) are edited by the task that changes serve (named there) to seed a user
      and accept the `users` keyword.
R6-8. **CLI `user`** (`cli/main.py`, no login, `config.app_db_path()`): `user add NAME --role admin|user` (password
      through `getpass.getpass` twice: "Parola: ", "Parola (tekrar): "; mismatch "Parolalar eşleşmiyor." exit 2),
      `user list` (Kullanıcı, Rol, Durum, Son giriş; never a hash), `user passwd NAME`, `user set NAME --role R |
      --deactivate | --activate`; UserError -> its message, exit 2; success one ✓ line, exit 0. Passwords are never
      arguments.
R6-9. **Per user.** `ask_payload(..., username=None)` / `replay_payload(..., username=None)`: the ask record gains
      `username` only when not None (absent = None, so Run 5 records and `tests/test_asklog.py` stay exact); the
      executor source becomes `"<src>:<username>:<audit_id>"` with a username and stays `"<src>:<audit_id>"` without
      (Run 5 pin in `tests/test_app_ask.py` holds). CLI `ask` passes `getpass.getuser()`. `asklog.history(...,
      username=_ALL)` and `find_ask(..., username=_ALL)`: a user sees only records with their username; admin passes
      `_ALL` and sees every record (old username-less ones too). Replay/export of an id the caller cannot see -> 404
      `NO_ASK` (never 403). `saved` gains a nullable `username` column (added by `ALTER TABLE` when missing; old rows
      NULL = admin only); a user lists and deletes only their own rows (another's id -> 404); the saved item shape
      in the API is unchanged.
R6-10. **Session holder.** Routes read `request.app.state.session` on every request (no closure capture), so a dataset
      switch is one assignment under a `threading.Lock`; saved/history/export filter by the *current* session's
      dataset. Every place that shows the dataset follows a switch: header chip (health), examples, tables, rules
      screen, sidebar saved + history, export's dataset check.
R6-11. **Datasets in two roots.** `datasets.load_dataset(name, root=None)`: root None looks in `datasets_dir()` then
      `real_datasets_dir()` (explicit root unchanged); `datasets.all_datasets()` -> `[{"name", "display_name",
      "connection", "root": "datasets"|"real_datasets", "path"}]` sorted by name (first root wins a clash);
      `datasets.name_taken(name)` checks both roots (folder exists, with or without dataset.json). `list_datasets`
      unchanged. Active dataset: settings row `active_dataset`; serve order = `--dataset` > stored (when it still
      loads; else a one-line note and the default) > `config.DEFAULT_DATASET`.
R6-12. **Template writer** (`schema_map/template.py`): `build_template(skeleton=None) -> bytes` (openpyxl, sheets in
      order `Nasıl doldurulur`, `Veri kümesi`, `Tablolar`, `Kolonlar`, `İş kuralları`, `Örnek`, hidden `_bilgin`
      with A1 `bilgin-sablon`, B1 `TEMPLATE_VERSION`). Header constants `DATASET_HEADERS = (AD, GÖRÜNEN AD, BAĞLANTI,
      VARSAYILAN ŞEMA, VERİ TARİHİ)`, `TABLE_HEADERS = (TABLO, MODÜL, AÇIKLAMA, ANAHTAR KELİMELER)`, `COLUMN_HEADERS =
      (TABLO, KOLON, TİP, AÇIKLAMA, DEĞERLER, KİŞİSEL VERİ, KAPALI, REFERANS, NULL)`, `RULE_HEADERS = (KİMLİK, TERİM,
      EŞ ANLAMLILAR, TANIM, SQL İPUCU, TABLOLAR)` are used by both writer and reader. Bold header row on the token
      accent fill, frozen header, column widths, 200 styled empty rows; data validation lists: KİŞİSEL VERİ =
      `pii.CLASSES` (+ blank allowed), KAPALI/NULL = `E,H`, BAĞLANTI = `mssql,sqlite`, Kolonlar.TABLO = range of
      Tablolar!A. `Örnek` = the three blocks (one table `Satis.Fatura` with 7 columns: FaturaID key, FaturaTarihi,
      CariKod with REFERANS `Satis.Cari.CariKod`, FaturaTipi with DEĞERLER `S=Satış; I=İade`, Tutar, YetkiliAdi
      with `person_name`, IcNot KAPALI=E) + one rule (`fatura_tutari`). `filled_example_workbook(name,
      connection="sqlite", with_rule=True) -> bytes` = the template with the Örnek table + rule copied into the real
      sheets under dataset `name` (REFERANS to the absent `Satis.Cari` dropped so it validates); it feeds the tests,
      the smoke, and the UI's "Örnek dolu şablonla dene". `skeleton` (from introspect) pre-fills Tablolar/Kolonlar
      names, types, NULL and REFERANS, meanings empty. No product or company name anywhere.
R6-13. **Excel reader additions** (`schema_map/excel.py`, no second schema reader): `_FIELDS` gains `pii`, `deny`,
      `keywords`; `profiles/excel_headers.json` gains `pii: [KİŞİSEL VERİ, KISISEL VERI, PII]`, `deny: [KAPALI, DENY]`,
      `keywords: [ANAHTAR KELİMELER, ANAHTAR KELIMELER, KEYWORDS]` (`tests/test_excel_fallback.py` FIELDS is edited by
      that task, named there); `convert` writes `pii`/`deny` on a column and `keywords` (split on `,;`) on a table
      **only when the sheet maps that field**, so Run 3 workbooks convert byte-equal; `_fk` accepts `TABLE.COL` and
      `SCHEMA.TABLE.COL`; `PROPOSE_SYSTEM` is unchanged (a proposal never claims the new fields; the fallback still
      maps them); new helper `sheet_rows(path, sheet) -> (header_row, headers, [(row_number, cells)])` reusing
      `_header_row`, for cell-level validation. The `Veri kümesi` and `İş kuralları` sheets are Bilgin's own fixed
      format, read by `template_import` with the R6-12 constants (deviation from brief §2 "headers in
      excel_headers.json": that file maps a customer's synonyms to schema fields and its test pins the field set).
R6-14. **Template reader** (`schema_map/template_import.py`): `is_bilgin_template(path)` (hidden `_bilgin` A1);
      `read_template(path) -> TemplateRead` = `read_workbook` -> `fallback_mapping` restricted to `Tablolar` and
      `Kolonlar` -> `convert`, plus the dataset row and the rule rows (`rules_edit.normalize_rule`, lists split on
      `,;`); `Örnek`, `Nasıl doldurulur` and `_bilgin` are never read into the result. A non-template workbook
      (`read_template(path, llm=None)`) maps its schema sheets through the Run 3 path (`propose(preview, llm)` +
      `fallback_mapping`; llm None -> fallback only); it still needs a `Veri kümesi` sheet, else the error "Veri
      kümesi sayfası yok: Bilgin şablonunu kullanın." (an upload always creates a named dataset). Cell errors found while reading
      (convert's `skipped` notes, empty TABLO/KOLON/TİP in a filled row, unknown type, E/H other than E/H/blank,
      class not in `pii.CLASSES`) are `MapIssue {sheet, row, column, message}`; a blank template reads to 0 tables, 0
      rules and `errors == []`.
R6-15. **Validation** (`template_import.validate(read, db_skeleton=None) -> (errors, warnings, db_check)`), errors
      block apply: no table at all ("Şablonda hiç tablo yok."), dataset AD missing / not matching
      `DATASET_NAME_RE` / `datasets.name_taken`, BAĞLANTI not mssql|sqlite, VERİ TARİHİ not ISO, a Kolonlar TABLO not
      in Tablolar, duplicate table or column, REFERANS to a column not in the workbook, a rule failing
      `rules_edit.validate_rule` against the read schema (unknown table, missing term/definition, duplicate id).
      Warnings: tables without AÇIKLAMA, columns with empty AÇIKLAMA (count + first 20 names). `db_check` (only with
      a skeleton): `merge.diff_map(read.schema, skeleton)` -> workbook-only tables/columns are errors, DB-only ones a
      warning; `{"checked": true, "missing_in_db": [...], "only_in_db": [...], "message": null}`; no connection ->
      `{"checked": false, "message": "Canlı veritabanı bağlantısı yok; karşılaştırma yapılmadı."}`.
R6-16. **Preview and apply** (`schema_map/onboard.py`, admin routes in `web/map_api.py`). `POST
      /api/schema-map/preview {filename, content_b64}`: decoded size > `MAP_MAX_BYTES` -> 413; not a zip holding
      `[Content_Types].xml` -> 422 "Yalnız .xlsx dosyası yüklenebilir." (judged by content, not name); the bytes go to
      a temp file, `read_template` + `validate`, and the whole result is saved as
      `MAP_PREVIEWS_DIR/<preview_id>.json` (`uuid4().hex`), nothing else written; previews older than
      `MAP_PREVIEW_TTL_MIN` are deleted on every preview/apply call and load as 404 "Önizleme bulunamadı ya da süresi
      doldu.". `POST /api/schema-map/apply {preview_id}`: errors present -> 409; name taken now -> 409 (re-checked);
      `apply_preview(preview, username)` creates `real_datasets_dir()/<name>/` with `mkdir(exist_ok=False)` and
      writes `dataset.json` (`connection`, `default_schema`, `as_of`, `seed 42`, files, `builder/generator/references
      = "real.py:..."`, outputs `data/<name>.db`, `db/mssql/build_<name>.sql`, `index/<name>`, `eval_out/<name>`,
      `fake_fallback_sql = SELECT COUNT(*) AS KAYIT_SAYISI FROM <first table>` so the no-model demo answers),
      `schema.json` (`doc` shape, kind data), `rules.json`, `profile.json` (`{"name", "pairs": []}`), empty
      `golden.jsonl`, `real.py` (stub like wwi_real's, Turkish SystemExit lines), `readonly_login.sql`
      (`login_script.readonly_login_sql(schema, f"bilgin_{name}_ro")`, `__DEGISTIR__` placeholder), then appends
      `{username, ts, name, counts}` to `MAP_CHANGES_LOG` and starts the index job in a daemon thread:
      `cli.build_index(embed, dataset=name)` with embed `fake` under `--llm fake` else `openai`. Status lives in
      memory per preview id: `writing` -> `indexing` -> `done` | `failed` (+ Turkish message); `GET
      /api/schema-map/status/{preview_id}`. An existing folder is never written; a failed write removes only the
      folder it created.
R6-17. **Template download.** `GET /api/schema-map/template.xlsx` (admin) -> blank template, `Content-Disposition:
      attachment; filename=bilgin-veritabani-sablonu.xlsx`. `?from_db=1`: only when `config.backend() == "mssql"` and
      `NL2SQL_MSSQL_CONN` is set (`GET /api/schema-map/info` -> `{"db_connection": bool}` tells the UI whether to show
      the button); `introspect.mssql_skeleton()` pre-fills; a metadata/permission failure returns the blank template
      with header `X-Bilgin-Note` (percent-encoded) "Salt okunur giriş tablo bilgisini okuyamadı (VIEW DEFINITION);
      boş şablon verildi." - never another login. `GET /api/schema-map/sample.xlsx` (admin) =
      `filled_example_workbook("ornek_fatura")`.
R6-18. **Datasets API** (`web/datasets_api.py`, admin): `GET /api/datasets` -> `{"active", "datasets": [all_datasets()
      item + "active": bool, "index": {"exists", "fresh", "reason"}]}`; `POST /api/datasets/active {name}` ->
      `open_session(name, model, llm, models_file)` of the current session (paths from the dataset) -> swap (R6-10),
      store the setting, 200 `{"active", "dataset": {"name","display_name","connection"}, "notice"}` where notice is
      `{"login_script_url": "/api/datasets/<name>/login-script.sql", "env": "NL2SQL_MSSQL_CONN", "message"}` for an
      mssql dataset and null otherwise; unknown 404; `SessionError` -> 409 with its sentence (the old session stays).
      `GET /api/datasets/{name}/login-script.sql` -> the folder's `readonly_login.sql`, else generated from its schema.
R6-19. **What the user sees (web).** Same tokens, dark mode, 8px grid and the one `@media (max-width: 720px)` block
      (phone rules go inside it). `main.jsx` mounts `Root.jsx`; `App.jsx` stays the workspace and gains optional
      `user`/`onLogout` props (without them it renders as in Run 5, so its tests hold).
      - Gate: `lib/auth.js` `boot(api, hash)` calls only `api.me()`: 401 -> `{screen: "login", requested: hash}`;
        ok -> `{screen: "app", user, route}`; `afterLogin(user, requested)` -> requested route if `canSee(route,
        role)` else `#/` + note "Bu sayfa yalnız yöneticiye açık."; `api.onUnauthorized(handler)` fires on any 401
        except `/api/auth/login`, and Root drops to login with "Oturumunuz sona erdi, lütfen yeniden giriş yapın.",
        remembering the hash. Until `me` answers Root renders a bare centred wordmark (no header, no sidebar, no
        chip, no fetch but `me`). Logout: `POST /api/auth/logout`, then App unmounts (answers, history, rules state
        gone) and the login screen shows.
      - Login (`#login-form`): centred 360px card on `--bg`, "Bilgin" wordmark, "Giriş yapın", `#login-username`
        (autocomplete username), `#login-password` (current-password), `#login-submit` ("Giriş" ->
        "Giriş yapılıyor…" disabled), `#login-error` (err tokens, server sentence), `#login-note` (warn tokens:
        expired / not allowed). No dataset name or other app data on it. Phone: card = viewport - 32px.
      - Header: `#user-chip` "<ad> · Yönetici|Kullanıcı", `#logout` "Çıkış"; admin-only `#nav-map` "Veritabanı
        haritası" (`#/harita`) and `#nav-users` "Kullanıcılar" (`#/kullanicilar`); route.js maps both (unknown
        still -> ask). At < 720px the nav takes its own row (T221 rule kept).
      - Rules for a user: `#rules-readonly-note` "İş kurallarını yalnız yönetici değiştirebilir." (muted band), no
        `#rule-add`, no Düzenle/Sil, no `#index-rebuild` (the stale banner text stays).
      - Users (`#users-screen`): add form `#user-add-form` (`#user-new-username`, `#user-new-password`,
        `#user-new-password2`, `#user-new-role`, `#user-add-submit`, field errors from `lib/usersForm.js` mirroring
        the server), table (Kullanıcı, Rol, Durum, Son giriş, İşlemler) with `select[data-user-role]`,
        `button[data-user-toggle]` (Pasifleştir/Etkinleştir), `button[data-user-reset]` -> inline new password +
        Kaydet; server 409/422 sentence in `#users-error`. Phone: rows stack (name+role, status, actions).
      - Map (`#map-screen`, "Yeni veritabanı"): card 1 three numbered steps (İndir · Doldur · Yükle) + `#map-template`
        "Boş şablonu indir", `#map-template-db` (only when info.db_connection; download via fetch, shows the
        X-Bilgin-Note), `#map-try-sample` "Örnek dolu şablonla dene"; card 2 `#map-file` (.xlsx), `#map-preview`
        "Kontrol et" (no file -> "Önce doldurduğunuz şablonu seçin."; "Kontrol ediliyor…"), `#map-report`: stat row
        (Tablo, Kolon, Kişisel veri, Kapalı, Referans, Kural), `#map-errors` table (Sayfa, Satır, Kolon, Sorun) on
        err tokens, `#map-warnings` amber list (first 20 + "ve N tane daha"), live-DB line, `#map-apply` "Oluştur"
        disabled with "Önce hataları düzeltin." while errors exist, `#map-progress` (Yazılıyor → İndeks kuruluyor →
        Hazır, or the failure sentence; polls status every 1 s), `#map-activate` "Bu veri kümesine geç"; card 3
        `#dataset-list` (name, display name, connection, index state, "Etkin" badge, `button[data-dataset-activate]`,
        disabled without an index) and `#dataset-notice` (mssql: login-script link + "Sunucuyu NL2SQL_MSSQL_CONN
        ile başlatın.", shown once per dataset - localStorage key `bilgin-notice-<name>` in try/catch). Phone: stat
        row 3 columns, error rows stack.
R6-20. **Visual flows.** `scripts/visual_serve.py --port P`: sets `NL2SQL_APP_DB=data/visual/bilgin.db` and
      `NL2SQL_REAL_DATASETS_DIR=data/visual/real_datasets` (both wiped first; refuses any path outside
      `data/visual/`), creates `admin` (admin) and `analist` (user) with the fixture password `VISUAL_PASSWORD`
      (a throwaway value valid only in that wiped file - not a dev or production password), builds
      `data/ornek_fatura.db` with the example table (empty), then runs `serve --llm fake --port P`. Every existing
      page gains the login steps first (they would otherwise shoot the login screen); new pages R6-21.
R6-21. New pages: `login-deeplink` (`/#/kurallar` without a session -> login shot, wrong password -> error shot,
      right one -> rules shot), `logout-clears` (admin asks, `#logout`, login shot), `user-readonly-rules` (analist
      -> `#/kurallar`), `users-screen` (admin -> users -> add analist2 -> table shot), `admin-map-onboard` (admin ->
      map -> `#map-template`, `#map-try-sample` -> report shot -> `#map-apply` -> progress shot -> `#map-activate`
      -> switched shot -> `#map-try-sample` again -> "name exists" error shot with `#map-apply` disabled).
R6-22. **Smoke.** `scripts/smoke_serve.py` (existing) runs serve with a tmp `NL2SQL_APP_DB`, a random
      `NL2SQL_DEV_ADMIN_PASSWORD` generated at run time (`secrets.token_urlsafe`), checks `/api/ask` is 401 without
      the cookie, logs in, then does its Run 5 steps with the cookie; `--roles` (M19) adds a `user` through
      `/api/users`, logs in as it and checks `POST /api/rules` 403 and another user's export 404.
      `scripts/smoke_onboard.py --port P`: tmp app DB + tmp real datasets dir + dev admin, template download, a
      filled workbook via `filled_example_workbook("smoke_fatura")`, preview (0 errors), apply, status until done,
      sqlite DB for it via `build.write_sqlite`, switch, `/api/ask` -> answered; always stops the server.
R6-23. **Test rules kept** (R5-22) plus: auth tests use tmp app DBs and an injected clock; no test sets a real
      password (values come from the test or `secrets`); a test hashes the tree of `datasets/` and `real_datasets/`
      before/after uploads (byte-identical); every new web test file is new (existing web tests are not edited
      unless a task names them).

## Contracts (Run 6 additions)

| Shape | Producer -> Consumer | Fields (optional = default) |
|---|---|---|
| error body | every 401/403/404/409/413/422/429 of Run 6 routes -> UI | `{"detail": str}` (Turkish sentence); rules 422 keeps `{"errors": [...]}` |
| User (public) | UserStore -> users API, CLI `user list`, authz | `{"id": int, "username", "role": "admin"\|"user", "active": bool, "created_at", "last_login_at": str\|null}` - never `password_hash` |
| me / login 200 | `/api/auth/me`, `/api/auth/login` -> Root | `{"username", "role"}`; login body `{"username": str, "password": str}` |
| users API | `/api/users` -> UsersScreen | GET `{"users": [User]}`; POST body `{"username","password","role"}` -> 200 `{"user": User}`; PUT body `{"role"?, "active"?, "password"?}` -> `{"user": User}`; 404/409/422 detail |
| stored password | passwords.hash_password -> users.password_hash | `scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>` |
| session row | UserStore -> current_user | `token_hash` = sha256 hex of the cookie value, `expires_at` ISO UTC |
| ask record (ext.) | asklog.record_ask | + `"username": str` only when known (absent = null) |
| audit source (ext.) | ask_payload/replay -> executor | `"<web\|cli>:<username>:<audit_id>"` with a username, `"<web\|cli>:<audit_id>"` without |
| saved row (ext.) | SavedStore (internal) | + column `username TEXT NULL`; API item shape unchanged |
| MapIssue | template_import -> preview, UI | `{"sheet": str, "row": int\|null, "column": str\|null, "message": str}` |
| TemplateRead | read_template -> validate, onboard | `{"dataset": {"name"="", "display_name"="", "connection"="mssql", "default_schema"=null, "as_of"=""}, "schema": {"tables": [doc table]}, "rules": [rule], "counts": {"tables","columns","pii","deny","references","rules"}, "errors": [MapIssue], "warnings": [MapIssue], "template": bool}` |
| db_check | validate -> preview | `null` (not asked) or `{"checked": bool, "missing_in_db": [str]=[], "only_in_db": [str]=[], "message": str\|null}` |
| preview response | `/api/schema-map/preview` -> MapScreen | `{"preview_id", "dataset", "counts", "errors", "warnings", "db_check"}`; same object saved as `data/map_previews/<id>.json` + `{"created_at", "username", "filename", "schema", "rules"}` |
| apply / status | `/api/schema-map/apply`, `/status/{id}` -> MapScreen | `{"preview_id", "name", "phase": "writing"\|"indexing"\|"done"\|"failed", "message": str\|null}` |
| map change line | onboard -> logs/map_changes.jsonl | `{"ts", "username", "name", "counts"}` |
| template info | `/api/schema-map/info` -> MapScreen | `{"db_connection": bool}` |
| new dataset folder | onboard.apply_preview -> datasets.load_dataset, build_index, session | dataset.json (R6-16) + schema.json + rules.json `{"rules": []}` + profile.json `{"name", "pairs": []}` + golden.jsonl (empty) + real.py + readonly_login.sql |
| datasets list | `/api/datasets` -> DatasetList, header | `{"active": str, "datasets": [{"name","display_name","connection","root","active": bool,"index": {"exists","fresh","reason"=null}}]}` |
| switch | `/api/datasets/active` -> App | body `{"name"}`; 200 `{"active","dataset": {"name","display_name","connection"},"notice": null\|{"login_script_url","env","message"}}` |
| settings | UserStore.settings -> serve, switch | key `active_dataset` -> dataset name |
| auth state (UI) | lib/auth.boot -> Root | `{"screen": "checking"\|"login"\|"app", "user": {username, role}\|null, "requested": hash="#/", "note": str\|null}` |

## Run 6 milestones

- **M18 - Auth core** (T223-T236): config, passwords, UserStore + sessions + lockout, saved per user, auth routes +
  `require` + cookie, SPA fallback, CLI `user`, serve store/refusal/dev bootstrap, smoke login, and - because a served
  app requires login from this milestone on - the web auth libs, Root gate + login screen + header chip/logout and the
  visual server with login steps in every flow (deviation from brief §3, which puts the login screen in M19: the M18
  visual review would otherwise shoot nothing but 401 states). Integration: CLI `user add` -> real store -> real
  create_app with the real session -> login, me, ask, logout, 401, lockout.
- **M19 - Roles everywhere** (T237-T243): route matrix walk, per-user ask log/audit/history/replay/export, users API,
  read-only rules, users screen (+ `#nav-users`, its visual pages). Integration: two users + one admin through
  TestClient on the real stack; vitest + build; smoke `--roles`.
- **M20 - New database from a template** (T244-T257): reader fields, template writer, reader, validation, datasets in
  two roots, session holder + datasets API, preview/apply/index job, map API, map UI, README, visual + smoke
  onboarding. Integration: real template -> filled in code -> preview API -> apply -> real fake index -> switch ->
  `/api/ask` answered; existing datasets byte-identical; non-admin 403 on all of it.


# PLAN - NL2SQL Run 7 (conversations, start screen per business role, database connections in the admin panel)

Brief: `PROJECT_BRIEF_RUN7.md`. Product name Bilgin (package/CLI stay `nl2sql`). No commercial ERP product or company
name in code, docs, UI text or test data. Milestones M21-M25 as the brief numbers them. No new dependency: DPAPI is
`ctypes` over `crypt32`, everything else is stdlib + what pyproject already pins.

## Run 7 architecture

```
POST /api/ask {question, mode?, choice?, conversation_id?}
   -> web/app.py ask: db_status.state()=="down" ? ask.down_payload (no agent)  [M25]
   -> app/ask.py ask_payload(session, q, ..., conversations=store, conversation_id=id|None, username)
        conversations.get(id, username) -> 404 when not theirs / missing
        turns = store.last_turns(id, CONV_TURNS)            (summary_json only: <= CONV_KEEP_ROWS masked rows)
        refine.chart_only(q, turns) ----------------------> rerun previous SQL, chart by code, no LLM call   [M22]
        refine.ambiguous_entity(q, turns, schema) -------> needs_clarification with kept-row options          [M22]
        agent/loop.run_agent(q, ..., history=turns)
             agent/context.fit_history -> "## Önceki turlar" section appended to the ONE system message
             submit_sql gains optional `context` arg (only when history is given)
        agent/context.validate_note(note, turns) -> payload.context (+ evidence line) | dropped + logged
        app/ask._answer / _report (unchanged: guard sees only this turn's rows + this question)
        store.add_turn / complete_turn(summary = context.turn_summary(payload))
   -> payload + {conversation_id, turn, context}

GET /api/start -> start/cards.StartCache(dataset, card) -> executor (approved stored SQL only, never the model)
/api/ready-questions* (admin) -> start/ready.ReadyStore ; SQL always taken from an ask record (audit_id), never from the client
POST /api/ready-questions/suggest -> start/suggest job: model writes texts -> ask_payload per text -> approved=false

engine/connections.py ConnectionStore(app DB) + dpapi.py ; resolve(dataset) env_dataset > env(backend mssql) > stored > none
   -> open_session(..., connections=store) -> LocalExecutor(backend, conn_str)       (switch = new session, no restart)
engine/guard.py readonly_guard(conn_str, tables, connect=pyodbc.connect)   (before every save / "test")
engine/dbstatus.py DbStatus thread: SELECT 1 (3 s) every DB_CHECK_S, kick() after a change or a connection error
   -> /api/health.db -> header "Veritabanı" dot (every user), red banner, fail-fast ask
```

## Run 7 file layout additions

```
nl2sql/app/conversations.py      ConversationStore (conversations, turns) on the app DB
nl2sql/agent/context.py          turn_summary, followup_hints, context_block, fit_history, validate_note, evidence_line
nl2sql/agent/refine.py           CHART_WISHES table, chart_wish, chart_only, refine_hint, ambiguous_entity
nl2sql/eval/followups.py         load_followups, run_followups, followup_metrics
nl2sql/start/__init__.py ready.py (ReadyStore) cards.py (card_result, StartCache) seed.py suggest.py
nl2sql/engine/dpapi.py connections.py (ConnectionStore, resolve, build_conn_str, scrub, newest_driver)
nl2sql/engine/guard.py dbstatus.py
nl2sql/web/conversations_api.py start_api.py connections_api.py
datasets/synthetic_erp/followups.jsonl ready_questions.json          (fixtures for fake serve, smoke, visual)
real_datasets/wwi_real/followups.jsonl ready_questions.json
web/src/lib/{thread,startCards,connForm}.js
web/src/components/{Thread,TurnCard,ConversationList,StartScreen,StartCard,ReadyQuestionForm,ReadyQuestionsScreen,
                    ConnectionsScreen,DbStatus}.jsx
```

## Run 7 decisions

R7-1. **Config** (`nl2sql/config.py`, existing names unchanged): `CONV_KEEP_ROWS=5`, `CONV_TURNS=3`,
      `CONV_TITLE_CHARS=80`, `FOLLOWUP_MARKERS=("bu","bunlar","bunları","bunların","şu","şunlar","o","onlar","aynı",
      "sadece","yalnız","bunu","peki","ya","bunlardan","onun","bunun")`, `BUSINESS_ROLES` (ordered dict `satis: Satış`,
      `satin_alma: Satın alma`, `muhasebe: Muhasebe`, `yonetim: Yönetim`, `genel: Genel`), `DEFAULT_BUSINESS_ROLE="genel"`,
      `PERSONAL_CARDS=6`, `START_CACHE_S=300`, `CARD_REFRESH_MIN_S=30`, `CARD_TABLE_ROWS=10`, `SUGGEST_PER_ROLE=(2, 4)`,
      `DB_CHECK_S=60`, `DB_CHECK_TIMEOUT_S=3`, `CONN_ENV_PREFIX="NL2SQL_MSSQL_CONN_"`, `CONN_TABLE_SAMPLE=10`.
R7-2. **ConversationStore** (`app/conversations.py`, same SQLite file as saved/users = `saved_path` in create_app,
      `config.app_db_path()` on the CLI; short-lived connections like `SavedStore`; injectable clock). Tables exactly as
      the brief; `conversations.id` = `uuid4().hex` (text: a URL `#/c/<id>` must not be guessable), `username` NULL in
      single-user mode, `title` = first question cut to `CONV_TITLE_CHARS`. `turns.n` starts at 1. Methods: `create(username,
      dataset, title) -> id`, `add_turn(id, turn) -> n`, `complete_turn(id, n, turn)` (only the pending clarification
      turn), `get(id, username=ALL) -> {conversation, turns} | None`, `list(username, dataset)` newest `updated_at`
      first, `delete(id, username) -> bool`, `last_turns(id, k)` (answered turns only, oldest first). A row of another
      user, or of another dataset than the session's, is None -> API 404 "Konuşma bulunamadı." (never 403, as R6-9).
R7-3. **Turn summary** (`context.turn_summary(payload)`): `{"columns", "row_count", "rows": payload.rows[:CONV_KEEP_ROWS]
      (already masked by the executor - masked cells stay masked), "facts", "chart_kind": chart.type|null, "context":
      payload.context, "clarification": payload.clarification}`. Nothing else of the result is stored: no chart option,
      no row 6+. A failed turn is stored (status, answer_text = message) but never enters a context block.
R7-4. **Context block.** `run_agent(..., history=None)`: None or [] -> prompt, messages and tools byte-identical to Run 6
      (every pinned prompt test holds). With history: `context_block(turns, hints)` is appended to the single system
      message as `## Önceki turlar` - per turn `Tur n sorusu: ...`, `Tur n SQL: ...`, `Tur n kolonlar: ...`, `Tur n
      satırlar (k / toplam): ...` - then the hint line and the rules text: resolve "bu / bunlar / o müşteri / aynı dönem
      / sadece X / bunu" from these turns, start from the earlier SQL when the user refines a report, never copy a
      number from an earlier turn into the answer, fill `submit_sql.context`. The user message stays the bare question
      (fake scripts key on it). `fit_history(turns, messages, tools, budget)`: if the estimate exceeds the budget, drop
      the oldest turn, repeat; then drop rows (oldest kept turn first); the current question is never touched; still
      over -> the loop's existing `context_overflow`. Run gains `history_turns` and `history_rows_dropped`.
R7-5. **Context note.** With history, `submit_sql` takes an optional `context` object `{uses_turns: [int],
      entities: [{column, value}], refines_sql_of: int|null}`; `AgentRun.context_note` keeps it raw.
      `validate_note(note, turns, question) -> (note|None, reason|None)`: every turn number exists among the given turns,
      `refines_sql_of` in `uses_turns`, each entity's `value` (compared as folded text) appears in a used turn's kept
      rows or SQL, `column` is in that turn's columns. Invalid -> dropped, the answer stands, the ask record gets
      `context_dropped: <reason>`. A missing note = `{uses_turns: [], ...}` (stood alone). `evidence_line(note, turns,
      schema)` -> "Önceki cevaptan: müşteri 832 (Tailspin Toys (Head Office))" - the label is the column's schema
      description head (never the technical name; fallback "değer"), the parenthesis is the first other text cell of
      the kept row holding the value; no entity -> "Önceki cevaptan: 2. turun sorgusu temel alındı."
R7-6. **Numbers.** The narrator's allowed set stays `allowed_values(columns, rows, facts, question)` of THIS turn -
      earlier turns' values are never added (contract test in M21). Values the user typed are in `question` already.
R7-7. **ask_payload(..., conversations=None, conversation_id=None).** Without `conversations` the payload and record
      are exactly Run 6 (`tests/test_app_ask.py`, `test_app_clarify.py`, `test_cli_ask_json.py` PAYLOAD_KEYS hold).
      With it: no id -> new conversation; unknown/foreign id -> `ConversationNotFound`; payload gains
      `conversation_id`, `turn`, `context` (null when stood alone or dropped); the record gains `conversation_id`
      and `turn`. A `choice` on a conversation whose last turn is `needs_clarification` with the same question
      completes that turn (same n) instead of appending.
R7-8. **API.** `POST /api/ask` always passes `app.state.conversations` (payload keys grow on the web; no web test pins
      them). `GET /api/conversations` -> `{"conversations": [{id, title, dataset, created_at, updated_at, turns}]}`
      (own, current dataset); `GET /api/conversations/{id}` -> `{conversation, turns: [StoredTurn]}` - no SQL runs;
      `DELETE` -> `{"deleted": true}`; all `user` in ROUTE_ROLES. `GET /api/history` items gain `conversation_id`,
      `turn` (null for old lines). Replay unchanged.
R7-9. **CLI.** `ask "..." --conversation ID` continues, `ask "..." --new` starts one (both use
      `ConversationStore(config.app_db_path())` and print a last line `Konuşma: <id> · tur <n>`); plain `ask` is Run 6
      (no store write - so CLI tests never touch `data/bilgin.db`); `--json` with either flag carries the three keys.
      Unknown id -> "Konuşma bulunamadı." exit 2.
R7-10. **Chart-only refinement** (`agent/refine.py`). `CHART_WISHES = {"line": ("çizgi","line","trend"), "bar":
      ("çubuk","sütun","bar"), "pie": ("pasta","dilim","pie"), "table": ("tablo","tablo olarak")}`; `chart_wish(q)`;
      `chart_only(q, turns)` = a wish, the last answered turn exists, and after removing the wish, markers and
      `grafik/grafiği/göster/yap/çevir/olarak/olsun/lütfen` nothing is left. Then ask_payload reruns the previous
      turn's SQL through the executor (same SQL string, new audit line), `chart_spec(columns, rows, q, kind=wish)`,
      facts by code, `answer_text` = code sentence ("Grafik çubuk olarak gösteriliyor." or the reason "Bu sonuç çizgi
      grafiğe uygun değil: tarih ya da sıralı bir kolon yok."), `narration_source="template"`, steps
      `[{tool: "chart", ...}]`, context `{uses_turns:[n], entities: [], refines_sql_of: n}`. Zero agent and zero narrator
      calls. `chart_spec(..., kind=None)`: None = Run 5 behaviour; a kind the shape allows is forced; otherwise the
      auto chart and `reason`.
R7-11. **Other refinements** go through the agent with the block; `refine_hint(q)` adds one hint line by keyword
      (`sadece|yalnız` filter, `karşılaştır|geçen yıl|önceki` compare, `aylık|çeyreklik|haftalık|yıllık` period,
      `ilk N|en çok N` top) telling the model to rewrite turn n's SQL. Standalone hints: `followup_hints(q, schema)` ->
      `{markers: [...], table_noun: bool}` (table noun = a folded word matching a table name/keyword/description head).
R7-12. **Ambiguous follow-up** (deterministic, before the agent): `ambiguous_entity(q, turns, schema)` - a singular
      demonstrative + an entity noun (`ENTITY_NOUNS = {"müşteri": ("customer","müşteri","cari"), "ürün":
      ("stockitem","product","ürün","stok"), "tedarikçi": ("supplier","tedarikçi"), "fatura": ("invoice","fatura")}`
      folded against the last answered turn's column names + descriptions) and that column has >= 2 distinct kept
      values -> `needs_clarification` `{question: "Hangi müşteriyi kastediyorsunuz?", options: ["<value> (<name>)",
      ...]}` from the kept rows. The choice runs the agent with `follow_up_text` and the chosen value is put into the
      context note as the entity by code. One distinct value -> no question.
R7-13. **Follow-up golden set.** Line = chain `{"id": "F01", "tags": [...], "turns": [{"question", "sql", "uses_turns":
      [int], "tags": [...]}]}`; `dataset.json files.followups` (optional; `Dataset.followups()` -> [] when absent).
      wwi_real: 8-12 chains (entity customer/product/supplier/invoice, set "bunlardan", period + filter refinements, one
      chain standing alone in the middle, one chart-only turn whose `sql` equals the previous). Every SQL passes
      `policy.check` against the wwi_real allowlist in a test; the run on the real SQL Server is Eren's manual step
      (README: `NL2SQL_BACKEND=mssql ... eval --followups --dataset wwi_real --llm fake`), never a task accept.
      synthetic_erp gets 3 chains (deviation from the brief: the fake-served app, smoke and visual flows need chains on
      a dataset that builds locally). `fake.for_golden(..., followups=)` replays chains keyed by (question, previous
      questions read from the `Tur n sorusu:` lines) and submits the golden `uses_turns` as the note;
      `make_client("fake")` passes the dataset's followups.
R7-14. **eval --followups** (`eval/followups.py`): each chain runs turn by turn through `ask_payload` with a tmp
      `ConversationStore` under `eval_out/<ds>/followups/` (real producer, not a copy of the loop); turn correct = the
      existing result-set verdict vs the turn's golden SQL; chain correct = all turns; context correct = set of note
      `uses_turns` == golden (empty = stood alone). report.json `followups: {turns, turn_accuracy, chains,
      chain_accuracy, context_accuracy, items: [...]}`, report.md section "Ardışık sorular", console one line per chain.
      `--llm fake` = 100 %. Target (manual): Flash-Next `full_rules` >= 80 % of turns.
R7-15. **Thread UI.** `#/c/<id>` route (route.js); `lib/thread.js` reducer (load stored turns, append pending, settle,
      complete clarification, expand/collapse). `#thread` holds `.turn` per turn: `.turn-question` bubble + card; the
      last turn's card is the full AnswerCard, earlier ones `.turn-collapsed` (sentence + kept rows) and expand on
      click. A stored turn (after reload / from the list) shows its sentence and kept rows plus "Tam tablo ve grafik
      için yeniden çalıştırın" with the replay button - opening never runs SQL. `#question` sits under the last turn;
      `#new-conversation` "Yeni konuşma" clears the thread and goes to `#/`. Evidence gets `#context-line` (the R7-5
      line). Sidebar: `#conversation-list` above history (title, time, `button[data-conversation-delete]`); history
      items show "tur n" when they belong to a conversation. Phone: bubbles full width, collapsed tables scroll
      inside their card; dark mode via tokens. All phone rules go inside the existing `@media (max-width: 720px)`.
R7-16. **Business role.** `users.business_role TEXT NOT NULL DEFAULT 'genel'` added by `ALTER TABLE` when missing;
      public User gains `business_role` (Run 6 pins in `tests/test_auth_store.py` and `tests/test_web_users_api.py`
      FIELDS are edited by T316, named there - the brief's shape wins); `/api/auth/me` and login 200 gain it. Admin sets
      it (POST/PUT `/api/users`); a PUT on one's own id with `business_role` -> 403 "Kendi iş rolünüzü
      değiştiremezsiniz."; unknown value 422. CLI `user add ... --business-role R`, `user set NAME --business-role R`,
      `user list` column "İş rolü". Header chip "<ad> · <İş rolü> · Yönetici|Kullanıcı".
R7-17. **Ready questions** (`start/ready.py`, app DB): table per the brief + `audit_id` of the approving ask.
      **The client never sends SQL**: admin `POST /api/ready-questions {audit_id, title, question?, display,
      business_role, position?}` takes the SQL from the ask record the admin can see (`find_ask`), reruns it through
      the executor - policy/exec error -> 422 with the sentence (a closed column is rejected here) - and stores
      `approved=1`. `PUT {title?, question?, display?, business_role?, position?, approved?, audit_id?}` (audit_id =
      "SQL'i yeniden onayla"). `DELETE`. `GET ?dataset=&pending=` lists all (admin). Personal: `POST /api/start/cards
      {audit_id, title, display}` (own ask only, `business_role NULL`, `created_by` = user, max `PERSONAL_CARDS` ->
      409 "En fazla 6 kişisel kart ekleyebilirsiniz."), `DELETE /api/start/cards/{id}` (own only, else 404).
      `suggest_display(columns, rows, chart)`: 1x1 numeric -> number; a chart spec -> chart; else table.
R7-18. **Start screen data.** `list_for(dataset, business_role, username)` = approved rows with role = theirs or `*`,
      plus their personal rows, by `position`, then id. `card_result(executor, card)` -> number: `value` + `label`;
      chart: `chart` (chart_spec); table: `columns`, `rows[:CARD_TABLE_ROWS]`; failure: `error` sentence (scrubbed),
      the other cards unaffected. `StartCache` keyed (dataset, card id, sql hash), TTL `START_CACHE_S`, one lock per key
      (single flight: two users in the TTL = one execute). `POST /api/start/cards/{id}/refresh` bypasses the TTL at most
      once per `CARD_REFRESH_MIN_S` per card, else 429 "Bu kart az önce yenilendi; {n} sn sonra yeniden deneyin.".
      `POST /api/start/cards/{id}/open` -> replay-shaped payload (stored SQL, narrator, no agent) recorded as turn 1 of a
      new conversation. An unapproved row never appears and never runs (open/refresh -> 404 for it).
R7-19. **Seeds.** `dataset.json files.ready_questions` (optional) -> `[{business_role, title, question, sql, display,
      position}]`; `seed.ensure_seeded(store, dataset, executor)` once per dataset (settings key `ready_seeded:<name>`)
      at serve start and after a dataset switch; rows whose SQL fails the policy are skipped with one log line.
      wwi_real: 2-3 per business role from golden SQLs; synthetic_erp: 2 per role (visual + smoke).
R7-20. **Suggestions.** `suggest.suggest_texts(schema, rules, llm) -> {role: [text]}` - one model call, JSON only,
      2-4 per role, parsed and capped by code; the fake returns golden questions round-robin. A job (thread, status in
      memory like R6-16: `asking` -> `done` | `failed`, counts) opens its own session for the dataset (no swap), runs
      `ask_payload` per text and stores answered ones `approved=0` with the SQL of that ask. `POST
      /api/ready-questions/suggest {dataset}` -> `{job_id}`; `GET /api/ready-questions/suggest/{job_id}`. Onboarding
      (`onboard` index job) starts it when the index is done.
R7-21. **Start screen UI.** `#/` renders `#start`: card grid (`.start-card[data-card-id]`, `data-display` number|chart|
      table; title, big value / small chart / mini table, "x dk önce yenilendi", `button[data-card-refresh]`; error card
      in err tokens + admin `button[data-card-reapprove]`), then the existing AskBox (`#question`, placeholder "Sorunuzu
      yazın") and the example chips. No cards -> one muted line (admin: pointer to "Hazır sorular"). Card click ->
      open -> `#/c/<id>`. AnswerCard: `#pin-card` "Panoma ekle" (everyone) and admin `#make-ready` "Hazır soru yap" ->
      `ReadyQuestionForm` (`#ready-title`, `#ready-question`, `#ready-display`, `#ready-role`, `#ready-save`).
      Admin screen `#/hazir-sorular` (`#nav-ready`, `#ready-screen`): per role groups, "Onay bekliyor" badge,
      `button[data-ready-open|approve|edit|delete]`, `#ready-suggest` + job line. Phone: one card per row; desktop
      auto-fill grid min 260px.
R7-22. **Connections store** (`engine/connections.py`, app DB): table per the brief; `save(dataset, fields,
      password|None, username)` (None/"" keeps the stored secret); `public(dataset)` -> R7 Contracts shape, never the
      secret or a connection string; `dpapi.protect(bytes, entropy)` / `unprotect` with `CRYPTPROTECT_LOCAL_MACHINE`,
      entropy `sha256("bilgin-conn:" + dataset)`; non-Windows -> `DpapiUnavailable` (API 409 "Bu sunucuda parola
      saklanamaz; ortam değişkenini kullanın.", UI form disabled). `build_conn_str(row, password, driver)` (sql auth UID/
      PWD, windows `Trusted_Connection=yes`, Encrypt / TrustServerCertificate yes|no, port as `SERVER=host,port`);
      `ApplicationIntent=ReadOnly` still forced by `_mssql._read_only`. `newest_driver(drivers=pyodbc.drivers)`.
      `scrub(text, secret=None)` removes `PWD=...`/`Password=...` values and the literal secret.
R7-23. **Resolution order** `resolve(dataset, store, active) -> {"source": "env_dataset"|"env"|"stored"|"none",
      "conn_str"}`: `NL2SQL_MSSQL_CONN_<NAME>` > `NL2SQL_MSSQL_CONN` (only for the active dataset and only when
      `config.backend() == "mssql"` - that keeps every Run 1-6 test's backend unchanged although the variable is
      ambient in the dev shell) > stored > none. `open_session(..., connections=None)`: with an `env_dataset` or
      `stored` source and `dataset.connection == "mssql"` the executor is `LocalExecutor(backend="mssql",
      conn_str=...)`; otherwise Run 6 exactly. `LocalExecutor(conn_str=None)` passes it to `_mssql.run`. The dataset
      switch and a connection save rebuild the session (one assignment, R6-10). Env source -> form read-only, PUT 409
      "Bu bağlantı ortam değişkeninden geliyor; ekrandan değiştirilemez.".
R7-24. **Read-only guard** (`engine/guard.py`): `readonly_guard(conn_str, tables, connect)` runs the fixed checks of the
      brief + `HAS_PERMS_BY_NAME(t, 'OBJECT', 'SELECT')` on up to `CONN_TABLE_SAMPLE` allowlist tables; result
      `{"ok", "lines": [{"check", "ok", "message"}], "missing_tables"}` in Turkish; any power -> ok false with "Bu giriş
      yazabiliyor ya da yönetebiliyor; salt okunur bir giriş kullanın." + login script URL. A connect failure is one
      scrubbed line. `PUT` runs it and saves nothing unless ok; `POST /api/connections/{dataset}/test` only reports.
R7-25. **Status** (`engine/dbstatus.py`): `DbStatus(resolver, ping, clock)`; `state(dataset) -> {state, checked_at,
      message}`; "none" for a dataset with no connection to check (sqlite) or none configured; `check_now()`, `kick()`,
      `start(interval)`/`stop()` (daemon thread; requests only read). `ping(conn_str, timeout)` = `SELECT 1` with
      `DB_CHECK_TIMEOUT_S`. Health `db` block; message for users is the generic sentence, admins also get the scrubbed
      driver text (`message_admin`). `tests/test_web_api.py` HEALTH_KEYS is edited by T339 (named). Ask when "down":
      `down_payload` (status failed, error kind `db_down`, "Veritabanına şu an bağlanılamıyor; cevap üretilemiyor.
      Yöneticinize haber verin.", recorded, no agent). An executor error whose text looks like a connection failure
      (`08001`, `08S01`, `Login failed`, `TCP Provider`) calls `kick()`.
R7-26. **Fake probe** (visual + smoke only): `serve --db-probe-file PATH` (hidden; exit 2 unless `--llm fake`) - JSON
      `{"status": {"<dataset>": "ok"|"down"}, "guard": {"<server>": "readonly"|"sysadmin"|"db_owner"|"writer"}}`
      re-read on each check; listed datasets count as connection-backed for the dot; the guard uses a fake connector
      answering per server name. No other code path reads it.
R7-27. **Connections UI** (`#/baglantilar`, `#nav-connections`, admin): table (dataset, `.db-dot` + state, server/
      database, Son başarılı, Son hata, source "Ortam değişkeninden" badge, `button[data-conn-edit]`); form per R7
      brief ids; password placeholder "değiştirmek için yazın"; `#conn-test` -> `#conn-result` lines (✓/✗ per check,
      missing tables, login script link); `#conn-save` (same guard; error band). MapScreen after apply links "Şimdi
      bağlantıyı girin" (`#map-connection-link`) for an mssql dataset. Header: `#db-dot` "Veritabanı" with tone
      ok/down/none and the tooltip (user generic + time; admin + scrubbed message + link), `#db-banner` red band on
      the ask/thread/start screens while down.
R7-28. **Visual server** additions: users `analist` business role `satis`, new `satinalma` (`satin_alma`), `admin`
      `yonetim`; synthetic_erp seeds; a probe file (`synthetic_erp: ok`, a second visual dataset `vitrin_kapali`:
      the sample workbook applied + fake index, `down`); the flows that switch dataset switch back at their end.
R7-29. **Test rules kept** (R5-22, R6-23) plus: conversation/start/connection tests use tmp app DBs; tests touching
      connection resolution `delenv` `NL2SQL_MSSQL_CONN`, `NL2SQL_MSSQL_CONN_*` and `NL2SQL_BACKEND` first; no test
      writes a real password (values from `secrets`); scripted fakes assert agent/narrator call counts.

## Contracts (Run 7 additions)

| Shape | Producer -> Consumer | Fields (optional = default) |
|---|---|---|
| ask body (ext.) | UI, smoke -> `/api/ask` | `{"question", "mode"=null, "choice"=null, "conversation_id"=null}` |
| AskPayload (ext.) | ask_payload with a store -> API, CLI `--json`, Thread | + `"conversation_id": str`, `"turn": int`, `"context": null\|ContextNote+{"line": str}`; without a store none of the three keys |
| ContextNote | model `submit_sql.context` -> validate_note -> payload, summary | `{"uses_turns": [int]=[], "entities": [{"column": str, "value": str}]=[], "refines_sql_of": int\|null=null}` |
| TurnSummary | context.turn_summary -> turns.summary_json -> context block, StoredTurn | `{"columns": [str], "row_count": int, "rows": [[cell]] (<= CONV_KEEP_ROWS, masked), "facts": [fact], "chart_kind": str\|null, "context": ContextNote\|null, "clarification": null\|{"question","options"}}` |
| history turn | store.last_turns -> run_agent(history), refine | `{"n", "question", "choice"=null, "sql", "summary": TurnSummary}` (answered only) |
| StoredTurn | `GET /api/conversations/{id}` -> Thread | `{"n", "question", "choice", "status", "sql", "answer_text", "audit_id", "created_at", "summary": TurnSummary}` |
| conversation item | `GET /api/conversations` -> ConversationList | `{"id", "title", "dataset", "created_at", "updated_at", "turns": int}` |
| ask record (ext.) | ask_payload -> asklog, history | + `"conversation_id"`, `"turn"` only with a store; + `"context_dropped": str` only when a note was dropped |
| history item (ext.) | `/api/history` -> Sidebar | + `"conversation_id": str\|null`, `"turn": int\|null` |
| chart_spec (ext.) | chart_spec(..., kind) -> payload.chart | + `"reason": str` only when the wished kind did not fit |
| followup chain | followups.jsonl -> fake, eval | `{"id", "tags"=[], "turns": [{"question", "sql", "uses_turns"=[], "tags"=[]}]}` |
| followups report | eval --followups -> report.json/md | `{"turns", "turn_accuracy", "chains", "chain_accuracy", "context_accuracy", "items": [{"id", "turn", "outcome", "context_ok"}]}` |
| User (ext.) | UserStore -> users API, me, CLI | + `"business_role": one of BUSINESS_ROLES` (default "genel") |
| ready question | ReadyStore -> admin API, start | `{"id", "dataset", "business_role": str\|"*"\|null, "title", "question", "sql", "display": "number"\|"chart"\|"table", "position"=0, "created_by", "approved": bool, "audit_id", "created_at"}` |
| ready create body | ReadyQuestionForm -> `POST /api/ready-questions` | `{"audit_id", "title", "question"=record.question, "display", "business_role", "position"=0}` - never `sql` |
| start card | `GET /api/start` -> StartScreen | `{"id", "title", "question", "display", "personal": bool, "value"?, "label"?, "chart"?, "columns"?, "rows"?, "refreshed_at": ISO\|null, "error"?: str}`; body `{"cards": [card], "business_role"}` |
| ready seed line | ready_questions.json -> seed | `{"business_role", "title", "question", "sql", "display", "position"=0}` |
| suggest job | `/api/ready-questions/suggest*` -> ReadyQuestionsScreen | `{"job_id", "dataset", "phase": "asking"\|"done"\|"failed", "asked", "stored", "message"=null}` |
| connection (public) | `GET /api/connections[/{ds}]` -> ConnectionsScreen | `{"dataset", "server", "database", "auth": "sql"\|"windows", "username", "options": {"encrypt": bool, "trust_server_certificate": bool, "port": int\|null, "driver": str}, "has_secret": bool, "source": "env_dataset"\|"env"\|"stored"\|"none", "read_only_form": bool, "last_ok_at", "last_error", "state"}` - never a password or connection string |
| connection PUT body | form -> `PUT /api/connections/{ds}` | `{"server", "database", "auth", "username"="", "password"="" (empty = keep), "options"}` |
| guard report | readonly_guard -> PUT/test -> `#conn-result` | `{"ok": bool, "lines": [{"check", "ok", "message"}], "missing_tables": [str], "login_script_url": str\|null}` |
| health db | DbStatus -> `/api/health.db` -> `#db-dot`, `#db-banner` | `{"state": "ok"\|"down"\|"none"\|"unknown", "checked_at": ISO\|null, "message": str\|null, "message_admin"?: str (admins only), "connections_url"?: "#/baglantilar" (admins)}` |
| probe file | visual_serve, smoke -> serve `--db-probe-file` | `{"status": {ds: "ok"\|"down"}, "guard": {server: "readonly"\|"sysadmin"\|"db_owner"\|"writer"}}` |

## Run 7 milestones

- **M21 - Conversation core** (T284-T295): config, store, turn summary, hints, context block + trimming, history in the
  loop + note arg, note validation + evidence line, ask_payload with conversations, number-guard contract, conversations
  API + history fields, CLI flags. Integration: real create_app + real store + real session (fake client from
  make_client) -> 3 turns through `/api/ask`, `GET` the thread, another user 404.
- **M22 - Refinements and clarification** (T296-T303): chart wishes, forced chart kind, chart-only path, ambiguous
  entity, refinement hints, synthetic followups + loader, fake chain replay. Integration: a 4-turn report refinement
  chain on synthetic_erp through ask_payload with the real fake and real store.
- **M23 - UI, golden set, eval** (T304-T315): wwi_real followups, eval runner + CLI/report, web libs, Thread/TurnCard +
  evidence line, App wiring + hash restore, conversation list, CSS, README, smoke `--conversation`, visual pages.
  Integration: API conversation with TestClient + reload from store + replay of one turn; vitest + build.
- **M24 - Start screen** (T316-T331): business role store/API/CLI, ready store, approval, card cache, start + ready
  APIs, seeds, suggestions, web libs, StartScreen, answer-card actions, admin ready screen, users screen + chip, CSS +
  visual pages, README + smoke `--start`. Integration: two roles + one admin on the real stack.
- **M25 - Connections and status** (T332-T345): DPAPI, connection store, resolution, executor/session per dataset,
  guard, status checker, connections API, health/fail-fast/serve wiring, secret scan, connections UI, header dot +
  banner, visual pages, README + smoke `--connections`. Integration: real store + real resolution + real session swap
  + injected connector/pinger through the API.

# PLAN - NL2SQL Run 8 (English everywhere, template in the program's language, Windows service)

Brief: `PROJECT_BRIEF_RUN8.md`. Product name Bilgin (package/CLI stay `nl2sql`). No commercial ERP product or company
name anywhere (already guarded by `tests/test_no_erp_brand.py`, T356). **Milestone renumbering:** the brief numbers
M24-M26, which Run 7 already used, so Run 8 continues at M26 and splits the brief's M25 in two:
M26 = brief M24 (language core), M27 = brief M25 server half (API, CLI, template, golden/eval, README),
M28 = brief M25 web half (catalogs, every screen, bundle scan, visual flows), M29 = brief M26 (Windows service).
**No new dependency**: catalogs are stdlib `json`, the web `t()` is our own hook (no i18n library), DPAPI is the
existing `ctypes` module, WinSW is downloaded by the operator's install script, never by pip/npm or a test.

Already delivered by Run 7 review tasks (do not redo): brand scrub + its test (T356), `serve` default chain
stored -> `wwi` -> first indexed -> default (T357), visual run on `wwi` (T370, T387), `wwi` golden/ambiguous/followups
coverage (T357). **Carry-over:** T376 was ticked but its commit changed nothing in `datasets/` - `wwi` still has no
`ready_questions.json`; T389 redoes it. T345/T377/T379 stay open as they are (REVIEW.md M25: do not re-implement).

## Run 8 architecture

```
lang sources:  web: users.lang -> Accept-Language (UI sets it from its own choice) -> NL2SQL_LANG -> "tr"
               cli: --lang -> NL2SQL_LANG -> "tr"
nl2sql/i18n/__init__.py  t(key, lang, **params) over tr.json / en.json ; resolve_lang(...) ; LANGUAGES
nl2sql/i18n/detect.py    detect_lang(question, fallback) -> "tr"|"en"     (deterministic, no model)
nl2sql/i18n/scan.py      user_literals(path, allow) -> Turkish string literals that are not docstrings/log/allowed

POST /api/ask -> web/lang.request_lang(request, user) = ui_lang
   -> ask_payload(..., lang=ui_lang): answer_lang = detect_lang(question, ui_lang)
        run_agent(..., answer_lang)  -> prompt gets ONE extra line for "en" (clarification wording); "tr" byte-identical
        compute_facts(cols, rows, lang=answer_lang)  labels t("facts.*"), display fmt.format_number(v, lang)
        chart_spec(..., lang) titles/reasons t("chart.*")
        narrate(..., lang): SYSTEM_EN twin, guard.check_text(text, allowed, lang), retry text in lang,
                            template_sentence(q, facts, lang)
        refine / context.evidence_line / chart-only sentence in answer_lang
   -> payload + "answer_lang"; error/warning sentences t(..., answer_lang); HTTP `detail` in ui_lang

GET /api/schema-map/template.xlsx?lang= -> template.build_template(skeleton, lang)   (sheet names, headers, Y/N, _bilgin.lang)
template_import.read_template: sheet/header aliases of BOTH languages (profiles/excel_headers.json), E/H/Y/N booleans

config: HOME = NL2SQL_HOME or ROOT (import time) -> app DB, logs, map previews, eval_out, index, secrets under HOME
python -m nl2sql paths | service-xml | service-check | secret-set
deploy/windows/bilgin.xml (WinSW template) <- nl2sql/service/winsw.render_xml <- scripts/install-service.ps1
service: C:\ProgramData\Bilgin\service\Bilgin.exe (WinSW) + Bilgin.xml -> .venv python -m nl2sql serve ...
```

## Run 8 file layout additions

```
nl2sql/i18n/__init__.py tr.json en.json detect.py scan.py
nl2sql/web/lang.py                       request_lang, PUT /api/auth/me {lang} lives in auth_api.py
nl2sql/service/__init__.py winsw.py paths.py secrets.py
deploy/windows/bilgin.xml                WinSW XML template (@TOKENS@), deploy/windows/.gitignore (WinSW-x64.exe)
scripts/install-service.ps1 uninstall-service.ps1 update-service.ps1
datasets/wwi/golden_en.jsonl followups_en.jsonl ready_questions.json
real_datasets/wwi_real/golden_en.jsonl followups_en.jsonl
README.tr.md (Turkish README), README.md (English)
web/src/i18n/index.js tr.json en.json, web/src/test-setup.js, web/src/components/LangToggle.jsx
tests/readme_text.py                     helper: README.md + README.tr.md text (README pins read both)
```

## Run 8 decisions

R8-1. **Config** (names kept): `LANGUAGES = ("tr", "en")`, `DEFAULT_LANG = "tr"`, `lang()` = `NL2SQL_LANG` if in
      LANGUAGES else DEFAULT_LANG (an unknown value -> DEFAULT_LANG, no crash), `TEMPLATE_FILENAMES = {"tr":
      "bilgin-veritabani-sablonu.xlsx", "en": "bilgin-database-template.xlsx"}` (TEMPLATE_FILENAME stays = tr),
      `SERVICE_NAME = "Bilgin"`, `SERVICE_PORT = 8777`, `SERVICE_HOME = r"C:\ProgramData\Bilgin"`,
      `DETECT_EN_WORDS`, `DETECT_TR_WORDS` (~25 stopwords each), `FOLLOWUP_MARKERS_EN = ("this","these","those","it",
      "them","that","same","only","just","their","its")`.
R8-2. **Catalogs.** `nl2sql/i18n/{tr,en}.json`: flat dotted keys (`api.ask.blank`, `facts.row_count`, `cli.ask.help`,
      ...), values with `{name}` placeholders. `t(key, lang, **params)`: unknown lang -> tr; key missing in that
      catalog -> tr value; missing everywhere -> `KeyError` (tests catch typos). A test asserts identical key sets
      and identical placeholder sets per key. Catalogs are read once (lru_cache). Each migration task adds only its
      own keys to both files.
R8-3. **Which strings move.** User-facing = HTTP `detail`/`errors`/`message`, payload text (`answer_text`, warnings,
      clarification, facts labels/display, chart titles/reasons, evidence lines, step summaries shown in the UI),
      template sentences, export headers, CLI stdout/stderr and argparse help, eval console + report.md text, preview
      errors/warnings, guard-report lines. **Stay:** docstrings, comments, log field names, prompts and tool texts
      sent to the model (`agent/prompt.py`, `agent/tools.py`, `narrate.SYSTEM`), regex word tables used for
      matching (refine/context markers), synthetic data (`schema_map/generator.py`, `extra.py`), dataset content.
      `ExecError`/policy messages stay Turkish (the model reads them); the user-facing failure sentence is
      `t("ask.fail.<kind>", answer_lang)` and the raw text remains in the evidence as technical detail.
R8-4. **Scan.** `i18n/scan.user_literals(path, allow=())` walks the AST: string constants (also inside f-strings)
      containing `[çğıöşüÇĞİÖŞÜ]` that are not a docstring, not an argument of a `logging`/`log.`/`logger.` call, and
      not assigned to a name in `allow`. Each migration task's test asserts `user_literals(<its module>, allow=...)
      == []` for its own module(s); T425 asserts the whole list. Scanned modules (final list): `nl2sql/web/*.py`,
      `nl2sql/cli/*.py`, `nl2sql/app/ask.py`, `nl2sql/report/{facts,narrate,chart,export,guard}.py`,
      `nl2sql/eval/{report,runner,followups,compare,compare_models,compare_modes,retrieval}.py`,
      `nl2sql/schema_map/{template,template_import,onboard,rules_edit,rules}.py`, `nl2sql/engine/{guard,connections,
      dbstatus,dpapi}.py`, `nl2sql/auth/store.py`, `nl2sql/start/{ready,cards,suggest,seed}.py`,
      `nl2sql/agent/{refine,context}.py`. Allow-lists name model-facing constants only (e.g. `narrate.SYSTEM`,
      `refine.CHART_WISHES`, `config.FOLLOWUP_MARKERS`).
R8-5. **Language resolution.** Web: `request_lang(request, user)` = `user["lang"]` if set -> first primary subtag of
      `Accept-Language` in LANGUAGES -> `config.lang()`. `users.lang TEXT NULL` added by `ALTER TABLE` when missing
      (NULL = no preference); public User gains `lang` (null default) - pins `tests/test_auth_store.py`,
      `tests/test_web_users_api.py` FIELDS edited by T403 (named). `PUT /api/auth/me {lang}` (user role; 422 for a
      value outside LANGUAGES) returns the me body; ROUTE_ROLES gets the row in the same task. CLI: a parent parser
      adds `--lang` to the top parser and every subcommand; help language = a pre-scan of argv for `--lang X`, then
      `NL2SQL_LANG`, then tr; `build_parser(lang)`.
R8-6. **Question language** `detect_lang(text, fallback)`: score_tr = Turkish-letter count*2 + TR stopword hits,
      score_en = EN stopword hits (words folded, ASCII split); higher wins, tie -> fallback. Payload key
      `answer_lang` always present (ask, replay, card open, chart-only, down_payload = ui lang, clarification).
      PAYLOAD_KEYS pins in `tests/test_app_ask.py`, `test_app_clarify.py`, `test_ask_conversation.py`,
      `test_cli_ask_json.py` gain `answer_lang` in T400 (named). A `choice` keeps the language of the original
      question. Clarification options from the model are shown as given; options built by code (R7-12) use the
      catalog.
R8-7. **Numbers** (`report/fmt.py`): `format_number(v, lang, decimals=None)`, `format_percent(v, lang)`,
      `format_compact(v, lang)` (`en`: "12.5K"/"3.4M"/"1.2B"; tr unchanged "12,5 bin"); `tr_*` stay as thin wrappers
      (every Run 5 pin holds). Guard: `extract_numbers(text, lang="tr")`, `check_text(text, allowed, lang="tr")`.
      en grammar: `1,234.56`, `1234.56`, `12.3%`, `-12.3%`; a token in the other language's shape (tr: `1.234,56` or
      `%12,3`; en: a `,` followed by not-exactly-3 digits, or `.` group separators) is **foreign** -> always rejected
      and reported in `rejected`. Ambiguous `1,234` / `1.234` read per lang (en 1234 / 1.234; tr 1.234 -> 1234).
      Tolerance unchanged (`NUMBER_TOLERANCE_UNITS`).
R8-8. **English narration.** `narrate(..., lang="tr")`: `SYSTEM_EN` is the rule-for-rule twin of SYSTEM (no invented
      numbers, numbers as shown in en format, no technical column names, natural English, values verbatim); rows and
      facts shown to the narrator formatted in `lang`; `_RETRY`/`_RETRY_NAMES` from the catalog; template sentence via
      `t("narrate.template.*", lang)`. tr path byte-identical (pinned prompt tests hold). Fake narrator unaffected.
R8-9. **Clarification and follow-ups in English.** `prompt.*_prompt(..., answer_lang="tr")`: "en" appends one line
      "Answer language: English - ask clarification questions and word their options in English."; tr unchanged.
      `refine.ambiguous_entity(..., lang)` question/options via catalog; `CHART_WISHES` and markers already hold
      English words (`line`, `bar`, `pie`; add `table`, `as a table`, `chart`, `show`); `followup_hints` also uses
      `FOLLOWUP_MARKERS_EN`; `ENTITY_NOUNS` gains English nouns (customer, product, supplier, invoice).
R8-10. **English golden sets.** `golden_en.jsonl` line = Turkish line with `id` "E01".., `source_id` "Q01".., English
      `question`, everything else (`sql`, `ordered`, `trap`, `tags`, `requires_tables`, `rules`, `review`) copied.
      `dataset.json files.golden_en` (optional; `Dataset.golden(lang)` -> golden_en when lang en and declared, else
      the Turkish set). **Deviation:** `wwi_real` only runs on the real SQL Server, so the brief's
      `eval --lang en --llm fake` 26/26 is proved on `wwi` (same translation job, its own 26 lines) and `wwi_real`'s
      file is structure-tested (same ids/SQL as its Turkish twin, policy passes its allowlist); the real run is Eren's
      manual step in README. `followups_en.jsonl` the same way (chains translated, SQL copied). `fake.for_golden`
      and `make_client("fake")` replay Turkish and English lines together (keys never collide).
R8-11. **Eval in English.** `eval --lang en` loads `golden(lang)`, prints progress/summary lines and writes report.md
      with catalog text, `report.json` and compare reports gain `"lang"`; `--followups --lang en` uses followups_en.
      Outcome codes (`pass`, `wrong_result`, ...) are data, not translated.
R8-12. **Template per language** (`schema_map/template.py`): `LABELS = {"tr": {...}, "en": {...}}` holding sheet
      names, header tuples, booleans (`E/H` | `Y/N`), how-to lines, example rows; `build_template(skeleton=None,
      lang="tr")`, `filled_example_workbook(..., lang="tr")`. `_bilgin` sheet gains row `lang`. Rules sheet gains
      column `EŞ ANLAMLILAR (EN)` / `SYNONYMS (EN)` -> rule `synonyms_en` (both templates). English headers exactly as
      the brief. Import: `profiles/excel_headers.json` gains every English header + a `sheets` map (both names ->
      canonical role); `_EH` accepts `e/h/y/n/evet/hayır/yes/no`; issues worded in the request lang
      (`read_template(path, llm=None, lang="tr")`, `validate(..., lang="tr")`). Same content in either template ->
      byte-identical `schema.json` and `rules.json`. API: `?lang=` > request_lang; filename by lang.
      CLI `python -m nl2sql template --lang tr|en --out FILE [--dataset NAME (skeleton)]`.
R8-13. **synonyms_en.** Optional list on a rule (rules.py validation: list of non-empty strings); rules API/editor
      field `synonyms_en` (`#rule-synonyms-en`); index rule document text includes both lists; BM25 synonym rewrite
      uses both. A rule without it behaves as today.
R8-14. **README.** `README.md` English, first line links `README.tr.md` ("Türkçe"); `README.tr.md` = today's Turkish
      README + Run 8 sections; both list the same commands (a test compares the set of `` `python -m nl2sql ...` ``
      commands). README pins in tests read both files through `tests/readme_text.py` (T422 edits only the read line
      of each named test).
R8-15. **Web i18n.** `web/src/i18n/index.js`: `registerCatalog(lang, obj)`, `loadCatalog(lang)` (dynamic
      `import("./en.json")` / `import("./tr.json")` -> separate chunks), `I18nProvider {lang}`, `useT()` -> `{t, lang}`,
      `t(key, params)` falls back to tr, then the key itself. `web/src/test-setup.js` registers both catalogs
      (vite.config `test.setupFiles`), so every existing vitest renders Turkish without a provider (default lang tr).
      `main.jsx` resolves lang (me.lang after login, else `localStorage["bilgin.lang"]`, else `navigator.language`
      primary tag if supported, else tr), awaits `loadCatalog`, renders. `document.documentElement.lang` follows.
      `api.js` sends `Accept-Language: <ui lang>` on every call. `lib/format.js` gains `lang` (`Intl.NumberFormat`
      `tr-TR`/`en-US`, dates `Intl.DateTimeFormat`); tr output identical to today.
R8-16. **Language switch.** `LangToggle` = `#lang-toggle` group with `button[data-lang="tr"]` "TR" and
      `button[data-lang="en"]` "EN", `aria-pressed` on the current one; in the masthead and on the login card. Click:
      set lang, `localStorage` (try/catch), and when logged in `PUT /api/auth/me {lang}`; the current screen
      re-renders without reload; server-made text (answers) stays in the language it was produced in.
R8-17. **Screens.** Every visible string, `aria-label`, `title`, `placeholder` of every component and lib message
      moves into `web/src/i18n/{tr,en}.json` (keys `<screen>.<name>`). Element ids, classes, data-attributes and hash
      routes (`#/kurallar`, `#/harita`, ...) never change. Each screen task adds `<Screen>.i18n.test.jsx`: render in
      tr and en, same ids set, en output has no `[çğıöşüÇĞİÖŞÜ]` outside server-provided fixture data. Phone layout:
      English strings are longer - buttons wrap inside the existing `@media (max-width: 720px)` block, never a
      horizontal scroll (visual pages at 390 check it).
R8-18. **Bundle scan.** After `vite build`, every `nl2sql/web/static/assets/*.js|*.css` except the tr catalog chunk
      (`tr-*.js`) contains no `[çğıöşüÇĞİÖŞÜ]`; `index.html` likewise (its `lang` attribute is set at runtime).
R8-19. **Facts panel** (brief §2, T359 follow-up): Evidence lists, under `#evidence-facts` heading "Diğer olgular" /
      "Other facts", exactly the facts not in the card's chip row (same selection function `chipFacts(facts)` exported
      from AnswerCard's lib, reused by Evidence); none left -> no list. Pins edited by T391 (named):
      `EvidenceRowDump.test.jsx` "no .facts list", `AnswerCard.test.jsx`, `AnswerCardFacts.test.jsx`.
R8-20. **NL2SQL_HOME.** `config.HOME = Path(NL2SQL_HOME or ROOT)` at import; under it `data/bilgin.db`,
      `data/map_previews`, `logs/{asks,audit,map_changes}.jsonl`, `eval_out/`, `index/`, `secrets/`. Dataset `outputs.
      index_dir` and `eval_out` resolve against HOME, `db`/`mssql_script` against ROOT (fixtures ship with the code).
      `NL2SQL_APP_DB`, `NL2SQL_DATASETS_DIR`, `NL2SQL_REAL_DATASETS_DIR` still override. Onboarded datasets: when
      `NL2SQL_HOME` is set -> `HOME/datasets` (also searched by the loader); unset -> `real_datasets_dir()` as today.
      Unset HOME = every path identical to Run 7. `python -m nl2sql paths [--json]` prints each name -> path
      (never a secret or connection string).
R8-21. **Secrets folder.** `service/secrets.py read_secret(env_name, home=None) -> str|None` reads
      `HOME/secrets/<ENV_NAME>.bin` (DPAPI machine scope, entropy UTF-8 `"bilgin-secret:" + ENV_NAME`); llm
      `_api_key` / `key_missing_reason`: env var first, then the secrets file. `python -m nl2sql secret-set ENV_NAME`
      (getpass, writes the blob; Windows only, exit 2 elsewhere). The install script writes the same blob with
      `[Security.Cryptography.ProtectedData]::Protect(..., 'LocalMachine')` and the same entropy.
R8-22. **WinSW.** v2.12.0 x64 (MIT), URL `https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW-x64.exe`,
      SHA-256 in `$WinSwSha256` at the top of `install-service.ps1`. The hash could not be fetched while planning, so
      the task leaves the constant empty and the script **refuses to download or install while it is empty**
      ("fill in the SHA-256 from the release page"); Eren fills it once (README manual step). Existing
      `deploy/windows/WinSW-x64.exe` -> hash check only. `deploy/windows/bilgin.xml` tokens: `@ID@ @NAME@ @DESCRIPTION@
      @PYTHON@ @ARGS@ @WORKDIR@ @LOGDIR@ @ENV@`; `render_xml(...)` fills them, `<startmode>Automatic</startmode>
      <delayedAutoStart>true</delayedAutoStart>`, `<onfailure action="restart" delay="10 sec"/>` 30 / 60,
      `<resetfailure>1 hour</resetfailure>`, `<log mode="roll-by-size"><sizeThreshold>10240</sizeThreshold><keepFiles>
      8</keepFiles></log>`, `<serviceaccount><domain>NT SERVICE</domain><user>Bilgin</user><allowservicelogon>true
      </allowservicelogon></serviceaccount>`; env keys exactly NL2SQL_HOME, NL2SQL_LANG, NL2SQL_BACKEND,
      NL2SQL_DATASETS_DIR; refuses any env key matching `PASSWORD|KEY|SECRET|CONN|TOKEN`. `python -m nl2sql
      service-xml --port --dataset --home --lang --out` writes it.
R8-23. **Install script.** Params `-Port 8777 -Dataset <active> -Home C:\ProgramData\Bilgin -Lang <NL2SQL_LANG|tr>
      -WhatIf -CopyAppDb`. Steps print as `[<id>] <text>` with ids in order: `admin, powershell, dev-admin-env, venv,
      port, model, connection, winsw, home, acl, copy-app-db, copy-index, secrets, admin-user, xml, install, start,
      health`. `dev-admin-env` refuses (exit 1, no change) when `NL2SQL_DEV_ADMIN_PASSWORD` is set at Machine level
      or in the process. `-WhatIf`: no change, no download, prints every step with "WHATIF" and the generated XML;
      the admin check is reported and does not stop a WhatIf. `model` and `connection` use `python -m nl2sql
      service-check --dataset D --json` -> `{"model": {"ok", "message"}, "connection": {"source", "ok", "lines"}}`
      (warnings only). update: stop -> `vite build` if `web/` is newer than `nl2sql/web/static/index.html` -> start ->
      health. uninstall: stop, uninstall, keep HOME unless `-RemoveData` (+ confirmation). Scripts are ASCII-only
      (Windows PowerShell 5.1 reads UTF-8 without BOM as ANSI).
R8-24. **Test rules kept** (R5-22, R6-23, R7-29) plus: tests that read `NL2SQL_LANG` or `Accept-Language` set them
      explicitly (`monkeypatch.delenv("NL2SQL_LANG")` where tr is expected); no test installs a service, downloads
      WinSW, or needs admin; PowerShell tests run `powershell.exe -NoProfile -ExecutionPolicy Bypass -File ...
      -WhatIf` and skip off Windows; DPAPI tests skip off Windows.
R8-25. **Visual pages in English** (`.hybrid/visual.json`, all `"from": "M28"`, both widths; each ends by clicking
      `button[data-lang='tr']` while logged in, so the shared server's admin preference and every later page stay tr):
      `en-login` (`/`: click `button[data-lang='en']` on the login card -> shot `login-en`; wrong password -> shot
      `login-error-en`; right password -> shot `start-en`), `en-ask-chart` (`/`: login admin, EN, fill `#question` with
      wwi golden_en E01 "What is the name of each country and how many cities belong to it?", `#ask-button`, wait
      4 -> shot `answer-chart-en`, open `#evidence` -> shot `evidence-en`), `en-map-screen` (`/#/harita`: login admin,
      EN, `#nav-map` -> shot `map-blank-en`, `#map-try-sample`, wait 3 -> shot `map-sample-preview-en`; nothing applied).

## Contracts (Run 8 additions)

| Shape | Producer -> Consumer | Fields (optional = default) |
|---|---|---|
| catalog | `nl2sql/i18n/*.json`, `web/src/i18n/*.json` -> `t()` | `{"dotted.key": "text with {param}"}`; both langs same keys, same params per key |
| AskPayload (ext.) | ask_payload, replay, card open, down_payload -> API, CLI `--json`, UI | + `"answer_lang": "tr"\|"en"` (always) |
| Fact (ext.) | compute_facts(lang) -> payload, guard, narrator | same keys; `label`, `display` in answer_lang |
| chart_spec (ext.) | chart_spec(lang) -> payload.chart | titles/`reason` in answer_lang; option numbers raw (UI formats) |
| GuardResult (ext.) | check_text(text, allowed, lang) -> narrate | same fields; foreign-format tokens appear in `rejected` |
| User (ext.) | UserStore -> me, login 200, users API | + `"lang": "tr"\|"en"\|null` (null = no preference) |
| me PUT body | LangToggle -> `PUT /api/auth/me` | `{"lang": "tr"\|"en"}` -> 200 me body; other value 422 |
| request lang | request_lang -> every route's text | user.lang > Accept-Language primary tag > NL2SQL_LANG > "tr" |
| golden_en line | golden_en.jsonl -> eval, fake | Turkish line + `"source_id": "Q.."`, `id` "E..", English `question` |
| dataset.json (ext.) | dataset -> loader | `files.golden_en`?, `files.followups_en`? (absent = Turkish only) |
| eval report (ext.) | eval -> report.json, compare report | + `"lang": "tr"\|"en"` |
| rule (ext.) | rules.json, rules API, template -> index, prompt | + `"synonyms_en": [str]` = [] |
| template `_bilgin` (ext.) | build_template -> import | rows mark, version, + `lang` |
| template preview (ext.) | read_template/validate(lang) -> map screen | same shape, `message` texts in request lang |
| paths | `python -m nl2sql paths --json` -> install script, README | `{"home", "app_db", "logs", "ask_log", "audit_log", "map_changes", "map_previews", "eval_out", "index", "secrets", "datasets": [..], "onboard_dir"}` |
| service-check | `nl2sql service-check --json` -> install script | `{"model": {"ok": bool, "message": str}, "connection": {"source": str, "ok": bool\|null, "lines": [str]}}` |
| service XML | render_xml -> WinSW | id/name/description/executable/arguments/workingdirectory/logpath/env(4 keys)/serviceaccount/onfailure x3; no secret |
| secret blob | install script / secret-set -> read_secret | `HOME/secrets/<ENV>.bin`, DPAPI LocalMachine, entropy `bilgin-secret:<ENV>` |

## Run 8 milestones

- **M26 - Language core** (T389-T402): wwi ready questions (carry-over), facts panel, i18n core + detect + scan,
  number formatting + guard per lang, facts/chart/template sentence per lang, English narration + clarification line,
  refine/context English, ask_payload `answer_lang`. Integration: real ask_payload on built wwi with the real fake ->
  an English golden question gives an English answer with en numbers that pass the guard, a Turkish one is unchanged.
- **M27 - Server in English** (T403-T427): users.lang + me PUT + request_lang, every API module, CLI `--lang` + help +
  output, template en + bilingual import + CLI, synonyms_en, wwi/wwi_real golden_en + followups_en, eval `--lang`,
  README en/tr. Integration: real create_app with an `en` user: ask, template download -> preview -> apply, errors.
- **M28 - Web UI in English** (T428-T445): i18n core, format, api header, LangToggle, every screen, bundle scan,
  visual pages in English. Integration: built bundle scan + served app returning English for an en user.
- **M29 - Windows service** (T446-T455): NL2SQL_HOME paths, paths CLI, secrets reader + secret-set, service-check,
  WinSW template + render, install/uninstall/update scripts with -WhatIf, README section, full-repo scan.
  Integration: `NL2SQL_HOME=tmp` serve started for real -> app DB, logs, index under tmp, `/api/health` answers.
