# REVIEW M6 (T62-T66, T72-T75)

Base 5a36efb (M5 review) -> HEAD c060ed1. Suite: 2143 passed, 1 red (stale test, below). T73/T74/T75 fixes from the first M6 review are in and tested.

- **RED (T76)**: tests/test_config_run2.py `test_index_dir_is_build_output_and_ignored` asserts the line `index/`; T75 intentionally changed it to `/index/`. Code is right, the test is stale -> T76 edits only that test.
- Bookkeeping: T71 is still `[ ]` in TASKS.md although T75 says it closes it (package tracked, .gitignore root-only). Tick it.
- ASSUMPTIONs rechecked: `_embedder_id` (embedder stored in report config, not in the fingerprint) is consistent across `evaluate`, `compare_modes` and `reusable`; non-rag modes store "" and compare equal. OK.
- Risk: `SCHEMA_HIT` accepts only upper-case names; fine for Netsis (TBLSTHAR), a lower-case schema would show "-> <first line>" instead of names.
- Risk: with no index `_index_embedder` returns ""; rag cannot run then (`_context` exits 2), so a "" match is harmless.
- Risk: `get_schema` is still uncapped and in the `full_rules` tool list; it inflates the full_rules peak and favours the verdict's "rag peak < full_rules peak" (open since M5).
- Risk: `eval --compare` silently ignores `--only`, `--tag`, `--mode`; only the score line shows when both verdict conditions fail.
- Risk (open from M4/M5): rules' `sql_hint` ~ golden SQL makes `full_rules` and `rag` easier than a real ERP; the `SAMPLE_VALUES_N` comment is stale.
- Missing tests: `--compare` with `--only`; `_search_notes` for get_table_details/find_join_path error answers.
