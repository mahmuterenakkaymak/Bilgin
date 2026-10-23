# REVIEW M6 (T62-T66, T72)

Base 5a36efb (M5 review) -> HEAD 5d3b780. Suite and smoke pass. T72 (M5 fix) is in and tested; the package from T71 is now tracked.

- **BUG (T73)**: `cli/main.py` `_search_notes` uses `LEADING_WORD = [A-Za-z0-9_]+` with `.match`; the empty answer "Eşleşen tablo yok." starts with `E`, so `ask --mode rag` prints `→ E` instead of the R2-14 empty state (same for "Hata: ..." -> `→ Hata`). Not covered by any test.
- **BUG (T74)**: the `--compare` reuse fingerprint (`_mode_fingerprint`, `_fingerprint`) sets `index_hash = content_hash(schema, rules)`, which ignores the embedder. README tells the user to swap to `NL2SQL_EMBED_MODEL=bge-m3` and rebuild; the schema/rules hash is unchanged, so `eval --compare` reuses the old rag report as "(önceki koşu)" and the verdict compares a stale rag run. Profile, prompts and tool limits are also outside the fingerprint (risk below).
- **BUG (T75)**: `.gitignore` still has `index/` (T71 is unchecked); the package is tracked only because it was force-added. `tests/test_repo_tracked.py` passes without the fix, since `git check-ignore` skips tracked files; a new file under `nl2sql/index/` is silently ignored again.
- ASSUMPTIONs checked OK: loop `_context` (context schema wins), runner wires `rules` for contextless `full_rules`, EXIT_NO_INDEX/EXIT_NO_TAG = 2, `_modes` order, verdict condition order (score, then context) matches R2-13. `compare_modes._summary` report path is built from `config.EVAL_OUT`, correct only because the CLI never overrides `out_dir` there.
- Risk: `get_schema` is still uncapped (R2-6 says every answer) and sits in the `full_rules` tool list; a `full_rules` run that calls it inflates its peak, which makes the verdict's "rag peak < full_rules peak" easier to win. Open since M5.
- Risk: `eval --compare` silently ignores `--only`, `--tag` and `--mode`; the user gets 40 questions x 3 modes.
- Risk: when both verdict conditions fail only the score line is shown; the context numbers are in the table, not the line.
- Risk (open from M4/M5): rules' `sql_hint` ~ golden SQL, so `full_rules` and `rag` have an easier job than in a real ERP; `SAMPLE_VALUES_N` comment is stale.
- Missing tests: `_search_notes` for empty/error answers of each tool; reuse after an embedder change; `.gitignore` root-only rule via `git check-ignore --no-index`; `--compare` with `--only`.
