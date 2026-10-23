"""LocalExecutor: the single public door to the databases.

The order is fixed here - policy, then transpile, then backend, then audit - so a caller
cannot reach a backend without the guardrail, and every attempt, approved or refused, leaves
one audit line. The backends are private modules for the same reason; nothing in this package
exposes a policy-free way to run SQL.
"""

from __future__ import annotations

from pathlib import Path

from sqlglot import transpile
from sqlglot.errors import SqlglotError

from nl2sql import config
from nl2sql.engine import _mssql, _sqlite, audit
from nl2sql.engine.result import Budget, ExecError, Result
from nl2sql.policy import policy
from nl2sql.schema_map import doc

TRANSPILE_MESSAGE = "SQL çalıştırılabilir bir sorguya çevrilemedi; tek bir T-SQL SELECT yazın."


class LocalExecutor:
    """Runs read-only T-SQL against one backend under a Budget."""

    def __init__(
        self,
        backend: str | None = None,
        db_path: str | Path = config.DB_PATH,
        allowlist: set[str] | None = None,
        audit_path: str | Path = config.AUDIT_LOG,
    ) -> None:
        self._backend = backend or config.backend()
        if self._backend not in config.BACKENDS:
            raise ValueError(f"Geçersiz yedek: {self._backend}; {list(config.BACKENDS)} olmalı.")
        self._db_path = db_path
        # ASSUMPTION: allowlist verilmezse PLAN Decision 6 gereği schema.json tabloları alınır;
        # geç çözülür, böylece testler dosyaya dokunmadan kendi listesini verebilir.
        self._allowlist = allowlist if allowlist is not None else doc.allowlist(doc.load_schema())
        self._audit_path = audit_path

    def execute(self, sql: str, budget: Budget | None = None, source: str = "") -> Result:
        """The only public entry: policy -> transpile (sqlite backend) -> backend -> audit."""
        result = self._run(sql, budget or Budget())
        audit.record(sql, source, result, self._audit_path)
        return result

    def _run(self, sql: str, budget: Budget) -> Result:
        verdict = policy.check(sql, self._allowlist, config.TOP_N)
        if not verdict.ok:
            return _error("policy", verdict.reason)
        if self._backend != "sqlite":
            return _mssql.run(verdict.sql, budget)
        try:
            statements = transpile(verdict.sql, read="tsql", write="sqlite")
        except SqlglotError as exc:
            return _error("transpile", _explain(exc))
        if len(statements) != 1:
            return _error("transpile", TRANSPILE_MESSAGE)
        return _sqlite.run(statements[0], budget, self._db_path)


def _error(kind: str, message: str) -> Result:
    return Result(error=ExecError(kind, message))


def _explain(exc: SqlglotError) -> str:
    text = " ".join(str(exc).split())
    return f"{TRANSPILE_MESSAGE} ({text})" if text else TRANSPILE_MESSAGE
