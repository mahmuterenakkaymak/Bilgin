"""Background database status checker (PLAN R7-25).

Every logged-in user sees a green or red "Veritabanı" dot, so somebody has to ask SQL Server
whether it answers - and no request can be the one that waits for it. A daemon thread runs
``SELECT 1`` every ``DB_CHECK_S`` (and right after a connection is saved or a query fails with a
connection error), while ``state`` only ever reads the last answer that check left behind.

The answer is written for two readers: users get the one generic Turkish sentence, admins
additionally get the driver's own text with its secrets out (``connections.scrub``), because "why"
is what they need in order to fix it. ``resolve`` and ``ping`` are the seams a test uses instead of
a live server.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from datetime import datetime, timezone

from nl2sql import config
from nl2sql.engine import connections

DOWN_MESSAGE = "Veritabanına bağlanılamıyor, yöneticinize haber verin."

# R7-25: the driver sentences that mean "the database is not reachable", not "this SQL is wrong".
_CONNECTION_MARKERS = ("08001", "08s01", "login failed", "tcp provider")


class DbStatus:
    """The last known answer to "does the database answer?", kept fresh by a daemon thread."""

    def __init__(
        self,
        resolve,
        ping=None,
        clock: Callable[[], float] = time.time,
        record: Callable[[str, bool, str | None], None] | None = None,
    ) -> None:
        # ``resolve(dataset) -> {"source", "conn_str"}`` is ``connections.resolve``; ``ping`` is this
        # module's own, replaceable so that no test has to reach a SQL Server. ``record(dataset, ok,
        # error)`` is the caller's ledger - the connection row's ``last_ok_at``/``last_error``, so
        # the screen still says when the database last answered once the process has restarted.
        self._resolve = resolve
        self._ping = ping
        self._clock = clock
        self._recorder = record
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._asked: set[str] = set()  # datasets somebody has read the status of
        self._answers: dict[str, dict] = {}  # dataset -> the last check's record
        self._thread: threading.Thread | None = None

    # ------------------------------------------------------------------ reads: never a wait

    def state(self, dataset: str) -> dict:
        """Contracts "health db": the last answer, and a first check asked for when there is none."""
        if self._conn_str(dataset) is None:
            return _record("none")  # a built SQLite dataset, or nothing configured yet
        with self._lock:
            self._asked.add(dataset)  # the loop only re-asks about datasets somebody reads
            answer = self._answers.get(dataset)
        if answer is not None:
            return dict(answer)
        self.kick()  # the first read starts the first check; this one can only answer "unknown"
        return _record("unknown")

    def check_now(self, dataset: str) -> dict:
        """One check in the caller's thread: the connection test asks, a request never does."""
        return self._check(dataset)

    def kick(self) -> None:
        """Ask again now instead of waiting for the interval: after a saved connection or a failed query."""
        self._wake.set()

    # ------------------------------------------------------------------ the thread

    def start(self, interval: float | None = None) -> None:
        """The daemon loop: a round of ``SELECT 1``s every ``DB_CHECK_S``, woken early by ``kick``."""
        if self._thread is not None:
            return
        self._stopping.clear()
        self._thread = threading.Thread(
            target=self._loop,
            args=(config.DB_CHECK_S if interval is None else interval,),
            name="dbstatus",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """End the loop; a check already running finishes on its own, bounded by the ping's timeout."""
        if self._thread is None:
            return
        self._stopping.set()
        self._wake.set()
        self._thread.join(timeout=config.DB_CHECK_TIMEOUT_S + 1)
        self._thread = None

    def _loop(self, interval: float) -> None:
        while True:
            self._wake.wait(interval)
            if self._stopping.is_set():
                return
            self._wake.clear()
            with self._lock:
                datasets = sorted(self._asked)
            for dataset in datasets:
                self._check(dataset)

    # ------------------------------------------------------------------ one check

    def _check(self, dataset: str) -> dict:
        failure: str | None = None
        try:
            conn_str = self._conn_str(dataset)
            answer = _record("none") if conn_str is None else self._pinged(conn_str)
        except Exception as exc:  # the driver's sentence, scrubbed, is the line; the loop survives
            failure = " ".join(str(exc).split())
            answer = _record(
                "down",
                checked_at=self._now_iso(),
                message=DOWN_MESSAGE,
                message_admin=connections.scrub(failure),
            )
        if answer["state"] != "none":  # a dataset with no connection has nothing to keep asking
            with self._lock:
                self._asked.add(dataset)
                self._answers[dataset] = answer
            self._mark(dataset, answer["state"] == "ok", failure)
        return dict(answer)

    def _mark(self, dataset: str, ok: bool, error: str | None) -> None:
        """One check's mark on the caller's ledger; a ledger that raises never stops the loop."""
        if self._recorder is None:
            return
        try:
            self._recorder(dataset, ok, error)
        except Exception:  # the mark is a line on a screen, not a reason to lose the answer
            pass

    def _pinged(self, conn_str: str) -> dict:
        (self._ping or ping)(conn_str, config.DB_CHECK_TIMEOUT_S)
        return _record("ok", checked_at=self._now_iso())

    def _conn_str(self, dataset: str) -> str | None:
        value = self._resolve(dataset).get("conn_str")
        return str(value) if value else None

    def _now_iso(self) -> str:
        return datetime.fromtimestamp(self._clock(), timezone.utc).isoformat(timespec="seconds")


def ping(conn_str: str, timeout: float | None = None) -> None:
    """``SELECT 1`` over a connection of its own; raises whatever the driver says when it fails."""
    import pyodbc

    # pyodbc wants whole seconds, the way the MSSQL backend rounds its own budget.
    seconds = max(1, math.ceil(config.DB_CHECK_TIMEOUT_S if timeout is None else timeout))
    conn = pyodbc.connect(conn_str, timeout=seconds)
    try:
        conn.cursor().execute("SELECT 1").fetchone()
    finally:
        conn.close()


def looks_like_connection_error(text: str | None) -> bool:
    """Whether an executor error means the database is unreachable, so the checker is kicked (R7-25)."""
    value = str(text or "").lower()
    return any(marker in value for marker in _CONNECTION_MARKERS)


def _record(
    state: str,
    checked_at: str | None = None,
    message: str | None = None,
    message_admin: str | None = None,
) -> dict:
    return {
        "state": state,
        "checked_at": checked_at,
        "message": message,
        "message_admin": message_admin,
    }
