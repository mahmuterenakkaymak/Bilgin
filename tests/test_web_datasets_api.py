# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T249: veri kümeleri API'si ve etkin kümenin değişmesi (PLAN R6-10, R6-11, R6-18).

Dünya ``test_web_api`` ile aynı gerçeklikte ama üç kümeyle: tmp köküne kopyalanmış mini, onun
SQL Server ilan edilmiş kopyası (şeması bir tablo, kuralları başka) ve veritabanı hiç kurulmamış
bir kopya. Geçiş sunucunun hangi veritabanına baktığını değiştirdiği için ekranın her yeri de
peşinden gelmek zorundadır: başlığın çipi, örnekler, tablolar, kurallar, kenar çubuğu, geçmiş ve
dışa aktarımın küme süzgeci hepsi aynı oturumu okur.
"""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bilgin import config
from bilgin.app.session import open_session
from bilgin.auth.store import UserStore
from bilgin.cli import main as cli
from bilgin.web.app import create_app
from bilgin.web.datasets_api import ACTIVE_SETTING

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
PAROLA = "Bilgin2026!erp"

# Sözleşme "datasets list": all_datasets öğesi + etkinlik + indeks durumu, fazlası değil.
DATASET_KEYS = {"name", "display_name", "connection", "root", "path", "active", "index"}

# İkinci kümenin şeması bir tablo fazla: /api/tables geçişten sonra gerçekten ötekini gösterir.
EXTRA_TABLE = {
    "name": "Warehouse.Stocks",
    "description": "Depo sayım satırları; ikinci kümenin şeması bir tablo fazlasıyla ölçülür.",
    "module": "Warehouse",
    "kind": "data",
    "keywords": ["depo", "sayım"],
    "columns": [
        {
            "name": "StockID",
            "type": "INT",
            "description": "Sayım satırının anahtarı.",
            "fk": None,
            "values": {},
            "nullable": False,
        },
        {
            "name": "Quantity",
            "type": "DECIMAL(18,2)",
            "description": "Sayılan miktar.",
            "fk": None,
            "values": {},
            "nullable": False,
        },
    ],
}


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


@pytest.fixture
def project(tmp_path, monkeypatch, capsys):
    """Üç kümenin dünyası: mini ölçülmüş haliyle, mini2 sunucu kopyası, eksik veritabanlı bir üçüncü."""
    root = tmp_path / "datasets"
    copy_dataset(root, "mini")
    mini2 = copy_dataset(root, "mini2", display_name="Mini 2 (Sunucu)", connection="mssql")
    copy_dataset(root, "eksik")

    # Kopyanın şeması bir tablo, kuralları başka bir kimlik, altın kaydı tek soru: ekranlar
    # geçişten sonra gerçekten öteki kümenin içeriğini göstermek zorunda.
    schema = json.loads((mini2 / "schema.json").read_text(encoding="utf-8"))
    schema["tables"].append(EXTRA_TABLE)
    (mini2 / "schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    rules = json.loads((mini2 / "rules.json").read_text(encoding="utf-8"))
    rules["rules"][0].update({"id": "mini2_ciro", "term": "Mini 2 cirosu"})
    (mini2 / "rules.json").write_text(json.dumps(rules, ensure_ascii=False, indent=2), encoding="utf-8")
    golden = (mini2 / "golden.jsonl").read_text(encoding="utf-8").splitlines()
    (mini2 / "golden.jsonl").write_text(golden[0] + "\n", encoding="utf-8")

    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(root))
    monkeypatch.setenv("BILGIN_REAL_DATASETS_DIR", str(tmp_path / "real_datasets"))
    for name in ("mini", "mini2"):
        assert cli.build_database(dataset=name) == 0
        assert cli.build_index("fake", dataset=name) == 0
    capsys.readouterr()
    return tmp_path


@pytest.fixture
def session(project, capsys):
    capsys.readouterr()
    return open_session(
        dataset="mini",
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
    )


@pytest.fixture
def client(session, project):
    return TestClient(create_app(session, saved_path=project / "bilgin.db", static_dir=project / "static"))


def golden(session, qid):
    return next(item for item in session.dataset.golden() if item["id"] == qid)


def refuse(app, host, port):
    raise AssertionError("reddedilen bir koşum sunucu açmaz")


# ------------------------------------------------------------------ GET /api/datasets


def test_the_list_names_every_dataset_and_which_one_is_active(client):
    body = client.get("/api/datasets").json()

    assert body["active"] == "mini"
    assert [item["name"] for item in body["datasets"]] == ["eksik", "mini", "mini2"]
    assert all(sorted(item) == sorted(DATASET_KEYS) for item in body["datasets"])
    by_name = {item["name"]: item for item in body["datasets"]}
    assert by_name["mini"]["active"] is True and by_name["mini2"]["active"] is False
    assert by_name["mini"]["root"] == "datasets"
    assert by_name["mini"]["connection"] == "sqlite" and by_name["mini2"]["connection"] == "mssql"
    assert by_name["mini"]["index"] == {"exists": True, "fresh": True, "reason": None}
    assert by_name["eksik"]["index"]["exists"] is False
    assert by_name["eksik"]["index"]["fresh"] is False
    assert "build-index" in by_name["eksik"]["index"]["reason"]


# ------------------------------------------------------------------ POST /api/datasets/active


def test_a_switch_moves_every_screen_that_names_the_dataset(client, session):
    before = {
        "health": client.get("/api/health").json()["dataset"],
        "examples": [item["question"] for item in client.get("/api/examples").json()["examples"]],
        "tables": client.get("/api/tables").json()["tables"],
        "rules": [rule["id"] for rule in client.get("/api/rules").json()["rules"]],
    }
    assert before["health"] == {"name": "mini", "display_name": "Mini (Satış/Depo)"}
    assert len(before["examples"]) > 1

    assert client.post("/api/datasets/active", json={"name": "mini2"}).status_code == 200

    assert client.get("/api/health").json()["dataset"] == {
        "name": "mini2", "display_name": "Mini 2 (Sunucu)",
    }
    assert [item["question"] for item in client.get("/api/examples").json()["examples"]] == (
        before["examples"][:1]
    )
    assert client.get("/api/tables").json()["tables"] == before["tables"] + ["Warehouse.Stocks"]
    assert [rule["id"] for rule in client.get("/api/rules").json()["rules"]] == ["mini2_ciro"]


def test_history_and_saved_are_filtered_by_the_current_dataset(client, session):
    question = golden(session, "Q01")["question"]
    client.post("/api/ask", json={"question": question})
    client.post("/api/saved", json={"question": "Mini sorusu"})
    assert client.get("/api/history").json()["history"] and client.get("/api/saved").json()["saved"]

    client.post("/api/datasets/active", json={"name": "mini2"})

    assert client.get("/api/history").json()["history"] == []
    assert client.get("/api/saved").json()["saved"] == []

    client.post("/api/ask", json={"question": question})
    assert [item["dataset"] for item in client.get("/api/history").json()["history"]] == ["mini2"]
    client.post("/api/datasets/active", json={"name": "mini"})
    assert [item["dataset"] for item in client.get("/api/history").json()["history"]] == ["mini"]


def test_an_export_of_the_other_datasets_record_is_refused(client, session):
    answer = client.post("/api/ask", json={"question": golden(session, "Q01")["question"]}).json()
    assert client.get(f"/api/export/{answer['audit_id']}.csv").status_code == 200

    client.post("/api/datasets/active", json={"name": "mini2"})

    refused = client.get(f"/api/export/{answer['audit_id']}.csv")
    assert refused.status_code == 409
    assert refused.json() == {"detail": "Bu kayıt başka bir veri kümesine ait."}


def test_a_dataset_without_a_database_is_refused_and_the_old_one_stays(client):
    response = client.post("/api/datasets/active", json={"name": "eksik"})

    assert response.status_code == 409
    assert "Veritabanı yok" in response.json()["detail"]
    assert "eksik" in response.json()["detail"]
    assert client.get("/api/health").json()["dataset"]["name"] == "mini"


def test_an_unknown_dataset_is_404(client):
    response = client.post("/api/datasets/active", json={"name": "olmayan"})

    assert response.status_code == 404
    assert "olmayan" in response.json()["detail"]
    assert client.get("/api/health").json()["dataset"]["name"] == "mini"


def test_only_an_mssql_switch_carries_a_notice(client):
    mssql = client.post("/api/datasets/active", json={"name": "mini2"}).json()

    assert mssql["active"] == "mini2"
    assert mssql["dataset"] == {
        "name": "mini2", "display_name": "Mini 2 (Sunucu)", "connection": "mssql",
    }
    assert mssql["notice"]["login_script_url"] == "/api/datasets/mini2/login-script.sql"
    assert mssql["notice"]["env"] == "BILGIN_MSSQL_CONN"
    assert "BILGIN_MSSQL_CONN" in mssql["notice"]["message"]
    assert client.post("/api/datasets/active", json={"name": "mini"}).json()["notice"] is None


def test_the_switch_stores_the_active_dataset_for_the_next_serve(project, session):
    users = UserStore(project / "app.db")
    users.add_user("admin", PAROLA, "admin")
    client = TestClient(
        create_app(
            session,
            saved_path=project / "bilgin.db",
            static_dir=project / "static",
            users=users,
        )
    )
    assert client.post("/api/auth/login", json={"username": "admin", "password": PAROLA}).status_code == 200

    assert client.post("/api/datasets/active", json={"name": "mini2"}).status_code == 200
    assert users.get_setting(ACTIVE_SETTING) == "mini2"


# ------------------------------------------------------------------ login-script.sql


def test_the_login_script_keeps_the_password_placeholder(client):
    response = client.get("/api/datasets/mini/login-script.sql")

    assert response.status_code == 200
    assert "__DEGISTIR__" in response.text
    assert "DENY SELECT" in response.text
    assert client.get("/api/datasets/olmayan/login-script.sql").status_code == 404


def test_a_script_the_folder_already_carries_is_served_as_is(client, project):
    script = "-- kümenin kendi betiği __DEGISTIR__\n"
    (project / "datasets" / "mini" / "readonly_login.sql").write_text(script, encoding="utf-8")

    assert client.get("/api/datasets/mini/login-script.sql").text == script


# ------------------------------------------------------------------ CLI serve


def test_serve_picks_the_stored_dataset_and_an_explicit_one_wins(project, capsys, monkeypatch):
    seen = {}
    capsys.readouterr()
    monkeypatch.setenv("BILGIN_APP_DB", str(project / "app.db"))
    users = UserStore(project / "app.db")
    users.add_user("admin", PAROLA, "admin")
    users.set_setting(ACTIVE_SETTING, "mini2")
    monkeypatch.setattr(cli, "run_server", lambda app, host, port: seen.update(host=host, port=port))

    assert cli.serve(llm_kind="fake") == 0
    assert "veri kümesi mini2" in capsys.readouterr().out

    assert cli.serve(llm_kind="fake", dataset="mini") == 0
    assert "veri kümesi mini" in capsys.readouterr().out
    assert (seen["host"], seen["port"]) == ("127.0.0.1", 8777)


def test_a_stored_dataset_that_no_longer_loads_falls_back_with_a_note(project, capsys, monkeypatch):
    capsys.readouterr()
    monkeypatch.setenv("BILGIN_APP_DB", str(project / "app.db"))
    users = UserStore(project / "app.db")
    users.add_user("admin", PAROLA, "admin")
    users.set_setting(ACTIVE_SETTING, "kaybolmus")
    # Updated 2026-10-26 (Eren: "otomatik olsun"): since T357 (Run 8 brief) a lost stored dataset falls back to the
    # demo dataset - the first one with an index - and the server opens with a one-line note instead of exiting 2.
    served = []
    monkeypatch.setattr(cli, "run_server", lambda app, host, port: served.append(app))

    assert cli.serve(llm_kind="fake") == 0 and served
    out = capsys.readouterr().out
    assert "kayıtlı veri kümesi kaybolmus" in out
    assert cli._demo_dataset() in out
