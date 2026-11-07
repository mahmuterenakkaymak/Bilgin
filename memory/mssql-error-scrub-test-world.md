---
name: mssql-error-scrub-test-world
description: bilgin — how to make a driver error reach the stored answer in a test (3 pyodbc connects per ask), and that _mssql.run is the scrub point for PWD=
metadata:
  type: project
---

To get a SQL Server driver sentence into **every** place an answer goes (response body, ask log,
audit log, `conversations.answer_text`), a fake `pyodbc.connect` must fail on the **third** connect
of one `POST /api/ask`: 1 = the agent's `run_sql` tool, 2 = the loop's own validation of
`submit_sql`, 3 = `ask._execute`'s UI-budget re-run. Fail earlier and the loop stops at
`no_submission` (generic `FAILED_STOP` sentence, `answer_text` stays clean, the app db never sees
the message). `dbstatus.ping` and the guard's `app.state.conn_connect` are separate seams, so they
do not consume those connects.

`bilgin/engine/_mssql.run` is where the driver text is born and where it is scrubbed
(`connections.scrub`); the ask log stores only the error *kind* and the audit log only
`error.kind`, so a leak there is impossible by construction — the leak sites are the payload
(`error.message`, `answer_text`, `steps[].summary`) and the stored turn.

**Why:** the scrub import is lazy because `connections` imports `_mssql` (`CONN_ENV`) — a
module-level import is circular.
**How to apply:** when a task touches connection error text or the ask path, reuse this
three-connect shape instead of monkeypatching `executor.execute` (that bypasses `_mssql.run` and
hides a real leak). See [[bilgin-hybrid-workflow]], [[hybrid-test-guard]].
