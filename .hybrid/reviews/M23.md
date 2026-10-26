# REVIEW M23 (T304-T315 + visual review T366-T372; range 5911118^ -> 2cab047)

Whole-project checks: the listed smoke failure is stale, not a regression - `tests\fixtures\map_netsis_style.xlsx` was renamed `map_erp_style.xlsx` by T356 and `.hybrid/checks.json` already follows it (f34f419); build-db, both import-map runs, `eval --followups --llm fake` (100 %) and `smoke_serve.py --conversation` all pass now. Full pytest here: 5397 passed, 1 failed + 14 errors, all worktree artefacts: `web/node_modules/.bin/vite` is missing in this worktree (14 build-fixture errors), and `test_dataset_move` hashes `datasets/synthetic_erp/schema.json` which this checkout has as CRLF (index is LF) - no task changed the file since T123.

- **BUG (T373)**: the stored-turn replay button appends a local turn that the server never stored (`replay_payload` has no `turn`/`conversation_id`); the next ask gets the same number -> duplicate `n`, reload loses it.
- **BUG (T374)**: deleting the open conversation from the list only refreshes the list; the next question is sent with the dead id and 404s.
- **BUG (T375)**: the last turn of a reloaded conversation shows a "Kapat" that cannot do anything (`mark` never folds the last turn).
- Visual-review findings already queued: T366-T372 (start-card chart box, composer not cleared, pie legend, card table columns, shared-server dataset restore, conversation row, start grid).
- ASSUMPTIONs checked and holding: loop hints (loop.py:131), eval followups default dataset, GET conversation NULL-dataset skip, ConversationList sorts/times by updated_at.
- Contracts traced: eval followups report keys == CLI/report.md; TurnSummary rows cap (5) == COLLAPSED_ROWS; ask payload `conversation_id`/`turn` consumed by thread.js `receive`; replay payload is the one producer that omits them.
- Risk: `test_dataset_move` pins raw bytes, so a CRLF checkout (autocrlf) turns it red on Windows; risk: `run_followups` scores a clarification turn wrong (runner never supplies a choice).
- Missing tests: replay inside a thread, delete of the open conversation, last stored turn controls, `eval --compare --followups` (flag silently ignored).
