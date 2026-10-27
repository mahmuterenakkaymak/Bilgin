# REVIEW M25 (T332-T345, range 92b157a -> HEAD; second pass after T385-T388 and the visual review T456-T462)

Whole-project checks pass (20 commands). Earlier reds (T385-T388) are closed; remaining findings are contract gaps.
- **BUG (T463)**: `_db_status` (nl2sql/cli/main.py:2215) freezes `active` at serve start, so after `POST /api/datasets/active` the generic `NL2SQL_MSSQL_CONN` still belongs to the startup dataset for the dot, while `_row`/`open_session` use the live one. The new active dataset shows no dot (state "none") though its queries run on the env database, and the old one keeps pinging it.
- **BUG (T464)**: `down_payload` (nl2sql/app/ask.py:340) skips the conversation: no `conversation_id`/`turn`, nothing stored. A question asked while the dot is red vanishes on reload, never opens a conversation, and breaks `/api/ask` "every ask is a turn" (R7-8, App.jsx:201 reads `payload.conversation_id`).
- Risk: map wizard live comparison (`map_api._db_connection`, map_api.py:165) reads only `NL2SQL_MSSQL_CONN`; a saved connection is never used there (introspect already takes `conn_str`). Not filed: R7-23 lists sessions only.
- Risk: `ConnectionStore.secret` -> `dpapi.unprotect` raises on a blob from another user/machine; `resolve` is called by `/api/health` and `/api/ask` via `DbStatus.state`, so a bad blob would 500 both. Needs a try in `resolve`/`state`.
- Risk: a connect failure in the guard returns 409 "Bu giriş salt okunur değil" (GUARD_REFUSED) although the lines say the connection failed; a server that is briefly down cannot be saved.
- Risk: `DbStatus._asked` only grows; stale "down" answer for a dataset lingers until the next loop round after a save.
- ASSUMPTIONs checked, holding: Encrypt/Trust defaults (connections.py:36), only a power refuses a save (guard.py:67), save rebuilds the active session (connections_api.py:91), DPAPI failure -> 409 on save.
- Contracts traced OK: health `db` keys vs DbStatus.jsx, guard report keys, `last_ok_at`/`last_error` now written (T388), `_mssql.run` scrub.
- Missing tests: dataset switch with the generic env set; ask while down with a `conversation_id`; unprotect failure through `/api/health`; DPAPI-off path off Windows.
