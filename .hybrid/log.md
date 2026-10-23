2026-10-23 11:10:37 | ORCH   | brain: cloud Claude (panel: cloud)
2026-10-23 11:10:37 | BRAIN  | planning with opus
2026-10-23 11:29:26 | ORCH   | brain: cloud Claude (panel: cloud)
2026-10-23 11:29:26 | BRAIN  | planning with opus
2026-10-23 11:33:24 | BRAIN  | plan done: 24 tasks
2026-10-23 11:34:25 | ORCH   | done: {"tasks": 0, "first_try": 0, "local_retries": 0, "rescues": 0, "failed": [], "reviews": 0, "minutes": 5.0, "brain_calls": 2, "brain": "cloud"}
2026-10-23 11:34:44 | ORCH   | brain: cloud Claude (panel: cloud)
2026-10-23 11:34:44 | HANDS  | T01 try 1: nl2sql/config.py: all tunables at top (AS_OF="2026-09-30", SEED=42, TOP_N=1000, MODEL_MAX_ROWS=50, COMPARE_MAX_ROWS=100000, QUERY_TIMEOUT_S, MAX_TOOL_CALLS=8, MAX_FAILED_RUNS=3, AGENT_TIMEOUT_S, LLM_CALL_TIMEOUT_S, ENABLE_THINKING=True, paths DB_PATH/MSSQL_SCRIPT/SCHEMA_PATH/GOLDEN_PATH/TRAPS_PATH/EVAL_OUT/AUDIT_LOG) plus llm_settings() and backend() reading NL2SQL_* env at call time with defaults
2026-10-23 11:38:48 | ORCH   | T01: PASSED (hands)
2026-10-23 11:38:48 | HANDS  | T02 try 1: schema/schema.json (10 tables from brief, every column with T-SQL type, description, fk, coded values per PLAN Decision 4) + nl2sql/schema_map/doc.py: load_schema(path), allowlist(), compact_text() (one line per table), table_detail(tables) (columns, types, fk, code values; unknown table -> short error text); tests validate shape and every fk points to an existing column
2026-10-23 11:42:25 | ORCH   | T02: PASSED (hands)
2026-10-23 11:42:25 | HANDS  | T03 try 1: nl2sql/schema_map/generator.py part 1: generate(seed) with seeded random.Random building master tables TBLSTGRUP, TBLSTSABIT, TBLDEPO, TBLPLASIYER, TBLCASABIT (A/S/H types, several cities, NULL optional fields); row keys equal schema.json columns in order; same seed -> equal Dataset, different seed -> different
2026-10-23 11:45:56 | ORCH   | T03: PASSED (hands)
2026-10-23 11:45:56 | HANDS  | T04 try 1: generator part 2: TBLFATUIRS, TBLSTHAR, TBLCAHAR, TBLSIPAMAS, TBLSIPATRA for Jun-Sep 2026 (few hundred movements) with every trap: returns (HTUR I), cancelled invoices (IPTAL E), same product in several depots, one product with several STHAR_NF prices, H-type cari with sales and purchases, transfers/sayım with FISNO NULL, NULL TESLIM_TARIHI order lines, an invoice with >=3 lines; GENELTOPLAM consistent with its lines; FK integrity test across all tables
2026-10-23 11:50:50 | ORCH   | T04: PASSED (hands)
2026-10-23 11:50:51 | HANDS  | T05 try 1: nl2sql/schema_map/build.py: write_sqlite(dataset, schema, path) (DDL from schema.json types), write_mssql_script(dataset, schema, path) (CREATE TABLE + batched INSERT, N'' strings, NULL, ISO dates), checksum(path) over ordered table dumps, build_db(seed, db_path, sql_path); tests: identical checksum for same seed, differs for other seed, row counts match dataset, every statement of the T-SQL script parses with sqlglot tsql
2026-10-23 11:53:32 | ORCH   | T05 hands edited TASKS.md - restored
2026-10-23 11:53:34 | ORCH   | T05: PASSED (hands)
2026-10-23 11:53:34 | HANDS  | T06 try 1: eval/golden.jsonl (10 questions per PLAN trap map, review "pending") + eval/reference.py REFERENCES computed in pure Python from Dataset; integration test: generate -> build_db(tmp) -> each golden SQL transpiled tsql->sqlite and run on the built DB == reference (rounded 2 dp, order-aware only when ordered)
2026-10-23 11:58:39 | ORCH   | T06: PASSED (hands)
2026-10-23 11:58:40 | HANDS  | T07 try 1: eval/traps.jsonl with one naive SQL per trap (8 traps, mapped to qid per PLAN); test: every trap is present in the Dataset and its naive SQL result on the built DB differs from the golden result of its question
2026-10-23 12:01:39 | ORCH   | T07: PASSED (hands)
2026-10-23 12:01:39 | ORCH   | M1: whole-project checks
2026-10-23 12:01:41 | ORCH   | M1: whole-project checks RED: ['.venv\\Scripts\\python -m nl2sql build-db --seed 42', '.venv\\Scripts\\python -m nl2sql eval --llm fake', '.venv\\Scripts\\python -m nl2sql ask "Eylül ayında en çok satan 5 ürün" --llm fake']
2026-10-23 12:01:53 | BRAIN  | M1: review with sonnet in the background - hands keep building
2026-10-23 12:01:53 | HANDS  | T08 try 1: nl2sql/policy/policy.py check(sql, allowlist, top_n) -> PolicyResult: sqlglot tsql parse, exactly one statement, SELECT/CTE/UNION-of-SELECT only, default-deny allowlist on real table refs (CTE-scope aware, shadowing cannot hide a real table), reject db/server-qualified names, sys/INFORMATION_SCHEMA, xp_/sp_, OPENROWSET/OPENQUERY/OPENDATASOURCE, SELECT INTO, table-valued functions; short reasons; all 10 golden SQLs pass
