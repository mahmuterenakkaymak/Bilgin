# REVIEW M5 (T47-T61)

Base ae4f0d0 (M4 review) -> HEAD 6d82a8b. Suite and smoke pass in the main checkout; this clean worktree cannot even import `nl2sql.index` (see T71).

- **BUG (T71)**: `.gitignore` has `index/` (for the runtime INDEX_DIR); it also matches `nl2sql/index/`, so the whole package (text, embed, docs, bm25, store, search, `__init__`) was never committed. `git ls-files nl2sql/index` is empty while cli/main.py, eval/retrieval.py and 9 tests import it - a clean checkout breaks, and the green suite only proves the working tree.
- **BUG (T72)**: `ToolContext(search=None, graph=None)` default + `dispatch` -> `ctx.search.search` / `ctx.graph.find_join_path` raise AttributeError in `rag` when `run_agent` gets no `context`; runner.py and cli/main.py still call `run_agent` without mode/context. `full_rules` without context silently gets `rules=[]` (= `full`, a quiet A/B error).
- ASSUMPTIONs checked OK: loop `_context` (context schema wins), tools `_run` (submit goes through policy), retrieval empty `requires_tables` = 1.0 (all 40 golden lines have tables, never hit), cli defaults `openai`/EXIT_EMBED 3, extra `_benzersiz_tarih`, rules markers, tools circular import of modes.
- Risk: tools.py ASSUMPTION leaves `get_schema` uncapped, but PLAN R2-6 says every tool answer in every mode is capped at 4000 chars; `full` can still pull a ~83-table summary into the transcript, `rag` cannot - the A/B context numbers are not symmetric. Decide: cap it (R2-6) or amend the plan.
- Risk: graph profile pairs fan out to every distractor holding TARIH / STOK_KODU / CARI_KOD (0.6-0.9 edges); `find_join_path` stays correct only because a direct edge is always cheaper - not tested on a pair whose shortest path crosses a distractor.
- Risk: `config.SAMPLE_VALUES_N` comment ("in the index text") is stale - it is the sample_values row cap.
- Risk: `build_index` timing excludes the store write; `seconds` is measured before `FileStore.save`.
- Risk (open from M4): rules' `sql_hint` ~ golden SQL, so `full_rules` and `rag` get an easier job than the model would in a real ERP.
- Missing tests: committed-file check for the whole package (T71); rag/full_rules with an incomplete context (T72); `find_join_path` never routes through a `distractor` table when a data-table path exists; `eval-retrieval`/`build-index` exit 3 on a dead embedder end-to-end.
