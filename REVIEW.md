# REVIEW M10 (T102-T109)

Base 223cf2d (T100) -> HEAD 795fba0 (T108) + uncommitted T109 work. Suite: 1 failed (test_tools_rag), 2550 passed; smoke build-db / build-index / eval-retrieval / ask (auto) / eval --compare --repeat 2 all exit 0. M10's own ASSUMPTIONs (repeat disables reuse, first run is primary, variant lines show hybrid only, expansion needs graph+schema) all check out correct.

- **BUG (T116)**: tests/test_tools_rag.py asserts the search_schema answer is exactly SEARCH_K lines - stale since T102 (d702360) appended "(komşu)" neighbours (R3-9, intended); T102's accept ran only its own file; the T109 rescue's fix was restored. The only thing blocking final green.
- **BUG (T117)**: eval-retrieval's "base" variant is measured with synonym rewriting ON - retrieval.py `_ask` omits `rewrite=False` and `HybridSearch.search` defaults `rewrite=config.SYNONYM_REWRITE` (True); the live run prints taban == +eşanlam (0.57/0.65/0.49 both) - R3-9's variant comparison is vacuous by construction.
- **BUG (T118)**: uncommitted policy.py exempts ORDER BY over a "shown" pii column from the R3-6 filter - no task, no PLAN change, no test; `_is_shown`'s `("", column)` fallback also exempts a same-named column of another table when the shown prefix is unresolvable.
- **BUG (T119)**: uncommitted world drift from the T109 rescue - schema.json kind-flips 4 Personel tables to data and adds 2 tables, extra.py fills TBLDEPARTMAN/DEPARTMAN_KODU, fixtures regenerated; nothing requires it, HEAD is self-consistent, and the flip makes T102's expansion surface TBLMAAS as "(komşu)" in ask (observed) - a PII salary table in model context.
- **BUG (T120)**: T102's commit swept `_t101check/` scratch (13 files incl. binaries) and T101's output (README Run 3 section, test_integration_m9.py, M7/M8 test fixes) under T102's message; T101 still `[ ]` in TASKS.md.
- Risk: synonym_query matches rule terms/synonyms as folded substrings - short synonyms ("kur") fire inside longer words, and the broken base variant cannot reveal the damage.
- Risk: `--repeat` without `--compare` is silently ignored; `_ask_mode` is dead in production (kept alive only by tests/test_cli_ask_modes.py).
- Missing tests: the ORDER BY filter is pinned in neither direction (T118); nothing asserts the base variant runs without rewriting (T117); `--repeat` without `--compare` has no defined-and-tested behaviour.
