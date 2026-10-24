# REVIEW M13 (T146-T155)

Base 4b9f79d (M12 review) -> HEAD c257bf6 (T155). The 11 suite/smoke commands pass. Checked every worker ASSUMPTION (budget TRIM_MARKER with the removed count, EXIT_NO_CELLS=3, ping via `models.list()` with retries off, auto limit floor(budget*0.5)) and the R4 Contracts: AgentRun -> QuestionResult -> report/compare_models fields, profile block, fingerprint `budget`, model-compare keys.

- **BUG (T160)**: `budget.trim_tool_answers` re-cuts an already trimmed answer on every later over-budget turn (trimmed text is 400+marker chars, still > TRIM_TOOL_CHARS): `trimmed` is inflated, the marker's "N karakter" becomes the old marker's length (47), and an answer just over the limit grows (410 -> 447 chars). Verified by running it. Contradicts R4-11 "the cut is permanent".
- **BUG (T161)**: `eval --compare --models a,b --repeat 0/-1` skips the BAD_REPEAT check (only the adsız --compare has it): writes an all-zero compare report, exit 0.
- **BUG (T162)**: `compare_models_cmd` ignores the reason `llm.ping` returns; a missing `UNSLOTH_API_KEY` is reported as "uç nokta yanıt vermiyor ... GPU'da modeli açın", sending the user to the wrong fix.
- Risk: the loop now always records `peak_estimate` (also without a budget), so Run 3-style reports get a "Bağlam bütçesi: tepe tahmin N, 0 soru sığmadı" line and context keys; the report.py comment ("not written when both are zero") no longer matches.
- Risk: on a turn-1 overflow the rejected estimate is the peak (AgentRun comment), on a later-turn overflow it is not recorded - the peak only means "sent", inconsistent between the two.
- Risk: the estimate is chars/CHARS_PER_TOKEN (Turkish text tokenizes denser); real 16K Studio may still reject a request the budget passed - `max_prompt_tokens` vs `peak_estimate` in the table is the only check.
- Risk: the compare shares one client across questions and repeats (as `evaluate` does); fine for FakeLLM, a stateful real client would carry history.
- Missing tests: re-trim idempotence (T160), `--repeat < 1` on the models compare (T161), missing key in the compare (T162); no test covers `ask --model` on an overflow printing the exit-1 "Cevap gönderilmedi: Bağlam bütçesi aşıldı" line end to end.
- Contracts checked, no mismatch: model-compare json keys vs Contracts, `profile.prompt_limit`, outcome list (9) in runner/report, fingerprint `budget`/`dataset` only when non-default, `--modes` without `--models` exit 2.
