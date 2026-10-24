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
