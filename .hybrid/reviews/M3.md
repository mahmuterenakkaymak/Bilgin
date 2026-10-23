# REVIEW M3 (T13-T24, plus fixes T25-T27)

Base 89bbcef (M2 review) -> HEAD c589ed6. Full suite: 714 passed. T25/T26/T27 fixes verified in diff (executor.py date/LEFT rewrites, policy.py `_cap_rows`); the M2 smoke failure is gone.

- **BUG (T28)**: blank `submit_sql` (also `{}` after bad tool JSON) gets "Sorgu boş: ..." without ERROR_PREFIX, so loop.py counts it ok -> run ends `submitted` with SQL `""`, no retry; `ask` then prints "submit_sql hiç çağrılmadı". Blank `run_sql` / unknown tool never count toward MAX_FAILED_RUNS. Reproduced with FakeLLM.
- **BUG (T29)**: `_count_turn` runs once per tool call, not once per response (docstring says once). A turn with 2 tool calls doubles its tokens: got 400/25, expected 300/15. Inflates total_tokens in progress lines and report.md. Reproduced.
- **BUG (T30)**: report `_delta` = passes now (all questions) minus previous passes (whole previous run), while `flipped` uses shared ids only. After `eval --only Q03` (overwrites `latest`) a full run shows a fake +9. tests/test_report_delta.py::test_a_shorter_run_compares_only_the_shared_questions asserts the wrong `-2`.
- ASSUMPTIONs checked OK: loop.py DEFAULT_MAX_TURNS, tools.py `_run` (submit_sql goes through the policy), runner.py `_truth` (broken golden -> RuntimeError) and `_outcome` (last attempt re-executed), compare.py (`ordered` affects row order only), cli/main.py (all llm_error -> exit 3, no report).
- Risk: COMPARE_MAX_ROWS=100000 is still dead, policy injects TOP_N=1000 on golden and predicted alike (open since M2); fine for the 10 goldens.
- Risk: report dirs use second-resolution stamps, two runs in one second overwrite each other. compare.py pairs columns by value multiset, identical-valued columns can pair wrongly (score unaffected).
- Risk: table.py prints int codes/years with thousands dots ("2.026"); prompt rule 2 still forbids MONTH/YEAR although T27 made them work.
- Missing tests: multi-tool-call turns, blank/unknown tool answers, `--only` then full-run delta, MSSQL path of ask/eval (no server).
