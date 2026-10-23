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
