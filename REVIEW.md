# REVIEW M25 (T332-T345; range 7fcebc1^ -> 22dc425, + working-tree tests/test_integration_m25.py)

Whole-project checks: pytest 4 red / 5524 green, vitest 1 red. All 5 reds traced to commits (below); tests/test_integration_m25.py itself passes (6).
- **STALE (T385)**: T377's `report/chart.py` edit (truncate, width 64, rotate 45, pie labels, no legend) landed inside cfc0fef (T378); T266/T368 pins in tests/test_chart.py and tests/test_chart_pie_legend.py (3 tests) still assert the old shape. Intended change, stale tests.
- **STALE (T386)**: T379's `columnLabel` in ResultTable.jsx landed inside f6f2b0a (T380); AnswerCard.test.jsx:162 still expects the raw `SATIS_MIKTARI` header.
- **BUG (T387)**: T343's pages `db-dot-user-ok`/`db-dot-user-down` end on `synthetic_erp`, the run opens on `wwi`; T370's restore-world test is right, the pages poison every later frame.
- **BUG (T388)**: `mark_ok`/`mark_error` have no caller; `last_ok_at`/`last_error` (contract "connection (public)", "Son başarılı/Son hata" columns) are always null.
- Process risk: T377 and T379 are still `[ ]` though their code is in HEAD (leaked into the T378/T380 commits); their accepts stay red until T385/T386 land. Do not re-implement them.
- ASSUMPTIONs checked, holding: Encrypt/Trust default true (connections.py:36), only a power refuses a save (guard.py:67), saving the active dataset rebuilds the session (connections_api.py:91), DPAPI failure -> 409 (dpapi.py:109).
- Contracts traced OK: health `db` keys vs DbStatus.jsx, guard report keys vs ConnectionsScreen, env source -> read_only_form.
- Risk: `DbStatus._asked` only grows; admin error text is scrubbed by pattern, not by knowing the password.
- Missing tests: DPAPI-unavailable path off Windows; a second kick during a running ping; a saved connection reaching a question on the already-open session beyond the integration file.
