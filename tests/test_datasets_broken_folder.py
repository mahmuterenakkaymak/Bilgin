"""T283: bozuk bir veri kümesi klasörü tüm listeyi düşürür (M20 review 2).

``real_datasets/`` altındaki bir klasör yarım kalmış bir apply'ın (R6-16: ``dataset.json`` yazıldı,
``schema.json`` henüz yazılmadı) ya da elle düzenlenmiş bir tanımın izini taşıyabilir. Tek bir bozuk
klasör ``GET /api/datasets``ı 500 yaparsa harita ekranı ne listeyi gösterir ne raporu ne de eski
kümesine dönebilir. Liste bozuk klasörü atlar, şeması okunamayanı "İndeks yok" satırı olarak
yayınlar; tek tek yollar yine kendi 404/409 cümlelerini söyler.
"""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nl2sql import config, datasets
from nl2sql.app.session import open_session
from nl2sql.cli import main as cli
from nl2sql.web.app import create_app
from nl2sql.web.datasets_api import BROKEN_DATASET, INDEX_UNREADABLE

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"

# Yarım kalan iki koşum: birinin tanımı okunamıyor, ötekinde tanım var ama şema henüz yazılmamış.
JUNK = '{"name": "bozuk_json", "as_of": '
DOC = {
    "name": "semasiz",
    "as_of": "2026-09-30",
    "builder": "builder.py:build_db",
    "generator": "builder.py:generate",
    "references": "builder.py:REFERENCES",
}


@pytest.fixture
def world(tmp_path, monkeypatch, capsys):
    """İki kök: ölçülmüş ``mini``, ``real_datasets``te iki bozuk klasör."""
    root, real = tmp_path / "datasets", tmp_path / "real_datasets"
    shutil.copytree(FIXTURE_ROOT / "mini", root / "mini")
    (real / "bozuk_json").mkdir(parents=True)
    (real / "bozuk_json" / "dataset.json").write_text(JUNK, encoding="utf-8")
    (real / "semasiz").mkdir()
    (real / "semasiz" / "dataset.json").write_text(
        json.dumps(DOC, ensure_ascii=False), encoding="utf-8"
    )

    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(root))
    monkeypatch.setenv("NL2SQL_REAL_DATASETS_DIR", str(real))
    assert cli.build_database(dataset="mini") == 0
    assert cli.build_index("fake", dataset="mini") == 0
    capsys.readouterr()
    return tmp_path


@pytest.fixture
def client(world, capsys):
    capsys.readouterr()
    session = open_session(
        dataset="mini",
        llm="fake",
        audit_path=world / "audit.jsonl",
        ask_log=world / "asks.jsonl",
    )
    return TestClient(
        create_app(session, saved_path=world / "bilgin.db", static_dir=world / "static")
    )


# ------------------------------------------------------------------ GET /api/datasets


def test_the_list_survives_the_broken_folders(client):
    response = client.get("/api/datasets")

    assert response.status_code == 200
    body = response.json()
    assert body["active"] == "mini"
    assert [item["name"] for item in body["datasets"]] == ["mini", "semasiz"]
    assert {item["name"]: item["active"] for item in body["datasets"]} == {
        "mini": True,
        "semasiz": False,
    }


def test_a_folder_without_a_schema_is_listed_as_having_no_index(client):
    item = next(
        item for item in client.get("/api/datasets").json()["datasets"] if item["name"] == "semasiz"
    )

    assert item["index"] == {"exists": False, "fresh": False, "reason": INDEX_UNREADABLE}


# ------------------------------------------------------------------ datasets


def test_all_datasets_omits_the_junk_folder_but_not_its_name(world):
    assert [item["name"] for item in datasets.all_datasets()] == ["mini", "semasiz"]
    assert datasets.name_taken("bozuk_json")
    assert datasets.name_taken("semasiz")


# ------------------------------------------------------------------ tek tek yollar


def test_a_broken_definition_still_answers_404(client):
    switch = client.post("/api/datasets/active", json={"name": "bozuk_json"})

    assert switch.status_code == 404
    assert "bozuk_json" in switch.json()["detail"]
    assert client.get("/api/datasets/bozuk_json/login-script.sql").status_code == 404
    assert client.get("/api/health").json()["dataset"]["name"] == "mini"


def test_a_folder_without_a_schema_still_answers_409(client):
    switch = client.post("/api/datasets/active", json={"name": "semasiz"})

    assert switch.status_code == 409
    assert "Veritabanı yok" in switch.json()["detail"]
    script = client.get("/api/datasets/semasiz/login-script.sql")
    assert script.status_code == 409
    assert script.json()["detail"] == BROKEN_DATASET.format(name="semasiz")
    assert client.get("/api/health").json()["dataset"]["name"] == "mini"
