"""T334: bağlantının nereden geleceği sırası (PLAN R7-23).

Bir veri setinin SQL Server bağlantısı dört yerden biridir: o veri setinin kendi ortam
değişkeni, genel ``NL2SQL_MSSQL_CONN`` (yalnız etkin veri seti ve yalnız mssql yedeğinde),
ekrandan saklanan satır, hiçbiri. Sıranın kendisi ölçülebilsin diye kabuktan gelen her bağlantı
değişkeni testten önce silinir: geliştiricide ``NL2SQL_MSSQL_CONN`` ambiyans durur.
"""

from __future__ import annotations

import os
import sys

import pytest

from nl2sql import config
from nl2sql.engine._mssql import CONN_ENV
from nl2sql.engine.connections import ConnectionStore, resolve

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="parola kutusu (DPAPI) yalnız Windows'ta vardır")

PAROLA = "Bilgin2026!parola"
FIELDS = {"server": "10.0.0.5", "database": "DNAEGITIM", "auth": "sql", "username": "bilgin_ro"}

# Sözleşme "connection (public)": kaynak adları; conn_str hiçbiri için None'dır.
GENEL = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=genel;DATABASE=WWI;"
KENDI = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=kendi;DATABASE=WWI;"
ENV_ADI = config.CONN_ENV_PREFIX + "WWI_REAL"  # NL2SQL_MSSQL_CONN_<BÜYÜK HARFLERLE AD>


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Kabuktaki her bağlantı değişkeni silinir; yedek de silinir ki varsayılan sqlite olsun."""
    monkeypatch.delenv(CONN_ENV, raising=False)
    monkeypatch.delenv("NL2SQL_BACKEND", raising=False)
    for name in [n for n in os.environ if n.startswith(config.CONN_ENV_PREFIX)]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def store(tmp_path):
    return ConnectionStore(tmp_path / "app.db")


# ------------------------------------------------------------------------ sıranın kendisi


def test_a_stored_row_is_the_source_when_the_environment_is_clean(store):
    store.save("wwi_real", FIELDS, PAROLA, "eren")

    found = resolve("wwi_real", store, "wwi_real")

    assert found["source"] == "stored"
    assert "SERVER=10.0.0.5;" in found["conn_str"]
    assert "UID=bilgin_ro;" in found["conn_str"]
    assert f"PWD={PAROLA};" in found["conn_str"]  # kurulurken çözülür, bir yere yazılmaz


def test_the_datasets_own_variable_wins_over_the_generic_one_and_over_the_row(store, monkeypatch):
    store.save("wwi_real", FIELDS, PAROLA, "eren")
    monkeypatch.setenv("NL2SQL_BACKEND", "mssql")
    monkeypatch.setenv(CONN_ENV, GENEL)
    monkeypatch.setenv(ENV_ADI, KENDI)

    assert resolve("wwi_real", store, "wwi_real") == {"source": "env_dataset", "conn_str": KENDI}


def test_the_generic_variable_wins_over_the_stored_row_of_the_active_dataset(store, monkeypatch):
    store.save("wwi_real", FIELDS, PAROLA, "eren")
    monkeypatch.setenv("NL2SQL_BACKEND", "mssql")
    monkeypatch.setenv(CONN_ENV, GENEL)

    assert resolve("wwi_real", store, "wwi_real") == {"source": "env", "conn_str": GENEL}


def test_nothing_is_resolved_for_a_dataset_with_no_row_and_no_variable(store):
    assert resolve("wwi_real", store, "wwi_real") == {"source": "none", "conn_str": None}


def test_nothing_is_resolved_when_there_is_no_store_at_all():
    assert resolve("wwi_real", None, "wwi_real") == {"source": "none", "conn_str": None}


# ----------------------------------------------------------------- genel değişkenin iki koşulu


def test_the_generic_variable_is_ignored_while_the_backend_is_sqlite(store, monkeypatch):
    store.save("wwi_real", FIELDS, PAROLA, "eren")
    monkeypatch.setenv(CONN_ENV, GENEL)  # NL2SQL_BACKEND silindi: yedek sqlite

    assert resolve("wwi_real", store, "wwi_real")["source"] == "stored"


def test_the_generic_variable_is_ignored_for_a_dataset_that_is_not_active(store, monkeypatch):
    store.save("wwi_real", FIELDS, PAROLA, "eren")
    monkeypatch.setenv("NL2SQL_BACKEND", "mssql")
    monkeypatch.setenv(CONN_ENV, GENEL)

    assert resolve("wwi_real", store, "synthetic_erp")["source"] == "stored"
    assert resolve("synthetic_erp", store, "wwi_real")["source"] == "none"


# --------------------------------------------------------------------------- değişkenin adı


def test_the_variable_name_is_the_upper_cased_dataset_name_whatever_the_backend_is(store, monkeypatch):
    # Etkin olmayan veri seti ve sqlite yedeği: kendi değişkeni yine de geçerlidir.
    monkeypatch.setenv(ENV_ADI, KENDI)

    assert resolve("wwi_real", store, "synthetic_erp") == {"source": "env_dataset", "conn_str": KENDI}


def test_another_datasets_variable_is_not_used(store, monkeypatch):
    monkeypatch.setenv("NL2SQL_BACKEND", "mssql")
    monkeypatch.setenv(config.CONN_ENV_PREFIX + "SYNTHETIC_ERP", KENDI)

    assert resolve("wwi_real", store, "wwi_real")["source"] == "none"


@pytest.mark.parametrize("value", ["", "   "])
def test_a_blank_variable_is_no_connection(store, monkeypatch, value):
    monkeypatch.setenv(ENV_ADI, value)
    monkeypatch.setenv(CONN_ENV, value)

    assert resolve("wwi_real", store, "wwi_real") == {"source": "none", "conn_str": None}
