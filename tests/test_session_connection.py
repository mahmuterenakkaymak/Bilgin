"""T335: oturumun kendi bağlantısı (PLAN R7-23).

Bir SQL Server kümesinin yürütücüsü, ekrandan kaydedilmiş satıra kurulur; satır yoksa Run 6'ın
hâli olduğu gibi sürer. Ölçüm ``_mssql.run``a kadar izlenir: dize oraya ``ApplicationIntent``
eklenmiş olarak değil, kurulduğu hâliyle gider - ReadOnly yemini bağlanırken eklenir. Dünya
tmp'dir: ``synthetic_erp`` adında bir SQLite kümesi ile onun SQL Server ilan edilmiş kopyası.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nl2sql import config, datasets
from nl2sql.app.session import open_session
from nl2sql.cli import main as cli
from nl2sql.engine import _mssql
from nl2sql.engine._mssql import CONN_ENV
from nl2sql.engine.connections import ConnectionStore
from nl2sql.engine.result import Result
from nl2sql.web.app import create_app

pytestmark = pytest.mark.skipif(
    sys.platform != "win32", reason="parola kutusu (DPAPI) yalnız Windows'ta vardır"
)

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
PAROLA = "Bilgin2026!parola"
FIELDS = {"server": "10.0.0.5", "database": "DNAEGITIM", "auth": "sql", "username": "bilgin_ro"}
KENDI = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=kendi;DATABASE=DNAEGITIM;"


def copy_dataset(root: Path, name: str, **over) -> Path:
    """Mini kümesinin tmp kopyası: ad, çıktı yolları ve söylenen birkaç alan değişir."""
    folder = root / name
    shutil.copytree(FIXTURE_ROOT / "mini", folder)
    meta = json.loads((folder / "dataset.json").read_text(encoding="utf-8"))
    meta.update({"name": name, **over})
    meta["outputs"] = {
        key: value.replace("mini", name) for key, value in (meta.get("outputs") or {}).items()
    }
    (folder / "dataset.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return folder


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    """Kabuktaki her bağlantı değişkeni silinir: geliştiricide ``NL2SQL_MSSQL_CONN`` ambiyans durur."""
    monkeypatch.delenv(CONN_ENV, raising=False)
    monkeypatch.delenv("NL2SQL_BACKEND", raising=False)
    for name in [n for n in os.environ if n.startswith(config.CONN_ENV_PREFIX)]:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def world(tmp_path, monkeypatch, capsys):
    """İki küme: ``synthetic_erp`` bir SQLite dosyasına, ``erp_live`` aynı şemayla bir sunucuya bakar."""
    root = tmp_path / "datasets"
    copy_dataset(root, "synthetic_erp")
    copy_dataset(root, "erp_live", display_name="ERP Canlı (Sunucu)", connection="mssql")
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(root))
    monkeypatch.setenv("NL2SQL_REAL_DATASETS_DIR", str(tmp_path / "real_datasets"))
    for name in ("synthetic_erp", "erp_live"):
        assert cli.build_database(dataset=name) == 0
    capsys.readouterr()
    return tmp_path


@pytest.fixture
def store(world):
    """Bağlantı deposu: uygulamanınkiyle aynı dosyada, yani ekrandan kaydedenle okuyan aynı satırı görür."""
    return ConnectionStore(world / "app.db")


@pytest.fixture
def mssql(monkeypatch):
    """``_mssql.run``ın yeri: hangi SQL hangi bağlantı dizesiyle çağrıldı, satırlar burada durur."""
    calls = []

    def fake_run(sql, budget, conn_str=None):
        calls.append({"sql": sql, "conn_str": conn_str})
        return Result(columns=["CIRO"], rows=[(1234.5,)], row_count=1)

    monkeypatch.setattr(_mssql, "run", fake_run)
    return calls


def open_for(world: Path, name: str, store: ConnectionStore | None = None):
    return open_session(
        dataset=name,
        llm="fake",
        audit_path=world / "audit.jsonl",
        ask_log=world / "asks.jsonl",
        connections=store,
    )


def sql_of(name: str) -> str:
    """Kümenin ilk altın sorusunun SQL'i: politikanın zaten kabul ettiği gerçek bir sorgu."""
    return datasets.load_dataset(name).golden()[0]["sql"]


# ------------------------------------------------------------------ oturumun bağlantısı


def test_a_stored_connection_reaches_the_backend_as_it_was_saved(world, store, mssql):
    store.save("erp_live", FIELDS, PAROLA, "eren")

    result = open_for(world, "erp_live", store).executor.execute(sql_of("erp_live"))

    assert result.error is None and result.rows == [(1234.5,)]
    assert len(mssql) == 1
    assert "SERVER=10.0.0.5;" in mssql[0]["conn_str"]
    assert f"PWD={PAROLA};" in mssql[0]["conn_str"]
    # ReadOnly yemini bağlanırken eklenir (_mssql._read_only): yürütücü onu bilmez, dize onsuz gider.
    assert "applicationintent" not in mssql[0]["conn_str"].lower()


def test_a_datasets_own_variable_moves_the_executor_although_no_row_is_saved(
    world, store, mssql, monkeypatch
):
    monkeypatch.setenv(config.CONN_ENV_PREFIX + "ERP_LIVE", KENDI)

    result = open_for(world, "erp_live", store).executor.execute(sql_of("erp_live"))

    assert result.error is None and result.rows == [(1234.5,)]
    assert [call["conn_str"] for call in mssql] == [KENDI]


def test_no_saved_connection_keeps_run_6_behaviour(world, store, mssql):
    session = open_for(world, "erp_live", store)

    result = session.executor.execute(sql_of("erp_live"))

    assert result.error is None and result.rows
    assert mssql == []  # sorgu klasördeki veritabanında koştu; sunucuya hiç gidilmedi


def test_a_connection_saved_for_a_sqlite_dataset_is_not_used(world, store, mssql):
    store.save("synthetic_erp", FIELDS, PAROLA, "eren")

    result = open_for(world, "synthetic_erp", store).executor.execute(sql_of("synthetic_erp"))

    assert result.error is None and result.rows
    assert mssql == []


# ------------------------------------------------------------------ küme geçişi


def test_a_switch_moves_the_executor_to_the_server_and_back(world, store, mssql, capsys):
    capsys.readouterr()
    store.save("erp_live", FIELDS, PAROLA, "eren")
    app = create_app(
        open_for(world, "synthetic_erp"),
        saved_path=world / "app.db",
        static_dir=world / "static",
    )
    client = TestClient(app)
    app.state.session.executor.execute(sql_of("synthetic_erp"))
    assert mssql == []

    assert client.post("/api/datasets/active", json={"name": "erp_live"}).status_code == 200
    app.state.session.executor.execute(sql_of("erp_live"))
    assert len(mssql) == 1
    assert "SERVER=10.0.0.5;" in mssql[0]["conn_str"]

    assert client.post("/api/datasets/active", json={"name": "synthetic_erp"}).status_code == 200
    app.state.session.executor.execute(sql_of("synthetic_erp"))
    assert len(mssql) == 1  # geri geçişte sunucu yok: dünya yeniden SQLite
