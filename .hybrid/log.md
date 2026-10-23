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
