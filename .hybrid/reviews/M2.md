# REVIEW M2 (T08-T12)

Base 365bc7e (end of M1; T08 landed before the M1 review commit f5c6cb4) -> HEAD 98dd11e. Full suite: 502 passed.

- **Smoke RED (`No module named nl2sql.__main__`)**: not a regression, no stale test. `nl2sql/__main__.py` and `nl2sql/cli` were never created (git log: only PLAN mentions them); T20/T24 own it. No fix task.
- **BUG (T25)**: `DATEDIFF(day, a, b)` through LocalExecutor is always 0 on SQLite. policy re-renders tsql with `CAST(x AS DATETIME2)`, transpiled to `CAST(x AS TIMESTAMP)` = numeric cast ('2026-02-01' -> 2026). `CONVERT(varchar(7), d, 120)` also silently returns the full datetime. Wrong number, no error - the worst kind.
- **BUG (T26)**: policy keeps any existing row limit: `TOP 99999999`, `TOP (@n)`, `OFFSET n ROWS` without FETCH are not capped to TOP_N (1000); the backend still counts every row.
- **BUG (T27)**: `MONTH()/YEAR()/DAY()/LEFT()/DATEPART()` fail on the SQLite backend ("no such function") while valid on SQL Server; "Eylül ayında ..." style questions will hit it in M3.
- ASSUMPTION _sqlite.py:46 (row_count = true total): OK, but capped at TOP_N by the policy, so "toplam" is never above 1000.
- ASSUMPTION executor.py:39 (allowlist from schema.json when None): OK, matches PLAN Decision 6.
- ASSUMPTION policy.py:94 (EXCEPT/INTERSECT denied) and :161 (UNION ORDER BY moved to outer wrapper): OK, verified on a UNION+ORDER BY case.
- Risk: `COMPARE_MAX_ROWS=100000` (Decision 8) is unreachable - TOP_N=1000 is injected into golden and predicted SQL alike; fine for the 10 goldens, decide in M3 if the runner should pass a larger top_n.
- Risk: scalar UDFs / `@@version` / `FOR XML` / `OPTION(...)` pass the policy (read-only anyway); sqlglot prints "Unsupported query option" to stderr and drops it.
- Risk: audit write failure (read-only dir) raises out of `execute` after the query ran; MSSQL backend untested (no server), pyodbc rows may be `Decimal` - compare.py (T17) must handle it.
- Missing tests: executor on date/string functions, TOP cap with large literals, mssql `_read_only()` string handling beyond the env check.
