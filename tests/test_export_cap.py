"""T206: dışa aktarım TOP_N'de kesiliyordu (PLAN R5-16, Contracts export file).

Politika her sorguya `TOP config.TOP_N` enjekte eder; bütçeyi genişletmek o tavanı değiştirmez,
yani 1050 satırlık bir cevap 100.000 satırlık bütçeyle de 1000 satır döner ve `truncated` False
kalır — dosya eksik, uyarısız. İddia iki yerden denetlenir: yürütücünün kendisi (tavan bütçeyle
birlikte yürür, söylenmeyince etkisi byte byte aynı kalır) ve arayüzün indirdiği CSV.
"""

import csv
import io
import sqlite3

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.agent import fake
from nl2sql.app.session import open_session
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.web.app import create_app

BOM = chr(0xFEFF)
TABLE = "DEPO"  # kümenin izinli listesinde, PII işareti olmayan tek tablo
SQL = f"SELECT DEPO_KODU FROM {TABLE}"
ROWS = config.TOP_N + 50


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    return tmp_path


@pytest.fixture
def db(project):
    """Satır sayısını tohumun değil testin belirlediği tek tablo: tavan burada ölçülür."""
    path = project / "cap.db"
    with sqlite3.connect(path) as conn:
        conn.execute(f"CREATE TABLE {TABLE} (DEPO_KODU TEXT, DEPO_ISIMI TEXT)")
        conn.executemany(
            f"INSERT INTO {TABLE} VALUES (?, ?)",
            [(f"D{n:06d}", f"Depo {n}") for n in range(ROWS)],
        )
    return path


def make_executor(db, project) -> LocalExecutor:
    return LocalExecutor(
        backend="sqlite",
        db_path=db,
        allowlist={TABLE},
        audit_path=project / "audit.jsonl",
    )


def make_client(db, project):
    """Kümenin kendi izinli listesi, sahte model ve tmp yollar: yol testlerinin dünyası (R5-22)."""
    session = open_session(
        dataset="wwi",
        llm="fake",
        db_path=db,
        index_dir=project / "index",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
        client_factory=lambda mode: fake.FakeLLM(fake.wrong_sql(SQL)),
    )
    return TestClient(
        create_app(session, saved_path=project / "bilgin.db", static_dir=project / "static")
    )


def csv_rows(content: bytes) -> list[list[str]]:
    text = content.decode("utf-8")
    assert text.startswith(BOM), "Excel UTF-8'i ancak BOM'u görünce tanır"
    return list(csv.reader(io.StringIO(text[len(BOM) :]), delimiter=";"))


# ------------------------------------------------------------------ yürütücünün tavanı


def test_a_wider_top_returns_every_row(db, project):
    result = make_executor(db, project).execute(
        SQL, Budget(max_rows=config.EXPORT_MAX_ROWS), "test", top_n=config.EXPORT_MAX_ROWS
    )

    assert result.error is None
    assert len(result.rows) == ROWS and result.row_count == ROWS
    assert result.truncated is False, "tavan satırların üstünde: kesinti yok, uyarı gerekmez"


def test_the_default_top_stays_at_the_interactive_cap(db, project):
    result = make_executor(db, project).execute(SQL, Budget(max_rows=config.UI_MAX_ROWS), "test")

    assert result.error is None
    assert len(result.rows) == config.UI_MAX_ROWS
    assert result.row_count == config.TOP_N and result.truncated is True


# ------------------------------------------------------------------ arayüzün indirdiği dosya


