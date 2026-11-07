# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T114: a SQL Server that cannot be introspected fails with a one-line IntrospectError, not a traceback.

The two failures a real user hits first - pyodbc not installed, server or DSN refusing the
connection - are checked over a fake pyodbc module (PLAN R3-4: the driver path is never run
against a live server), so both arrive as the error the CLI already knows how to print.
"""

import sys
import types

import pytest

from nl2sql.engine._mssql import CONN_ENV
from nl2sql.schema_map import introspect

DRIVER_TEXT = "[42000] [Microsoft][ODBC Driver 18 for SQL Server]Login timeout expired"


class FakeDriverError(Exception):
    """Stands in for pyodbc.Error, the class the driver raises on a refused connection."""


class FakeConnection:
    def __init__(self):
        self.closed = False

    def execute(self, sql):
        raise FakeDriverError(DRIVER_TEXT)

    def close(self):
        self.closed = True


def _fake_pyodbc(connect):
    module = types.ModuleType("pyodbc")
    module.Error = FakeDriverError
    module.connect = connect
    return module


def test_a_refused_connection_names_the_env_var_and_the_driver(monkeypatch):
    def connect(dsn):
        raise FakeDriverError(DRIVER_TEXT)

    monkeypatch.setitem(sys.modules, "pyodbc", _fake_pyodbc(connect))
    with pytest.raises(introspect.IntrospectError) as excinfo:
        introspect.mssql_skeleton("DSN=erp-copy")
    message = str(excinfo.value)
    assert CONN_ENV in message
    assert DRIVER_TEXT in message


def test_a_missing_pyodbc_names_the_module_and_uv_sync(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyodbc", None)
    with pytest.raises(introspect.IntrospectError) as excinfo:
        introspect.mssql_skeleton("DSN=erp-copy")
    assert "pyodbc" in str(excinfo.value)
    assert "uv sync" in str(excinfo.value)


def test_a_failed_introspection_query_closes_the_connection(monkeypatch):
    conn = FakeConnection()
    monkeypatch.setitem(sys.modules, "pyodbc", _fake_pyodbc(lambda dsn: conn))
    with pytest.raises(introspect.IntrospectError) as excinfo:
        introspect.mssql_skeleton("DSN=erp-copy")
    assert DRIVER_TEXT in str(excinfo.value)
    assert conn.closed is True
