"""T217: ``GET /api/examples`` belirsiz soruyu da önerir (PLAN R5-15).

Dünya gerçek: kümenin kendi builder'ı tmp'de db kurar, oturum gerçek ``open_session``, kapı gerçek
``create_app``; indeks bu yolun işi değil, kurulmaz. İki iddia: sentetik kümenin çipleri altın
soruların ardından ``ambiguous.jsonl``in ilk satırını tek bir ``ambiguous`` çipi olarak taşır, ve
belirsiz dosyası olmayan kümede çiplerin hepsi ``golden``kalır - yani eski davranış bozulmaz.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from nl2sql import config, datasets
from nl2sql.app.session import open_session
from nl2sql.cli import main as cli
from nl2sql.web.app import create_app

ROOT = Path(__file__).resolve().parent.parent
DATASET = "synthetic_erp"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "datasets"


def first_ambiguous_question() -> str:
    """Kümenin belirsiz setinin ilk satırının sorusu, dosyadan bağımsız okunur."""
    lines = (ROOT / "datasets" / DATASET / "ambiguous.jsonl").read_text(encoding="utf-8")
    for line in lines.splitlines():
        if line.strip():
            return json.loads(line)["question"]
    raise AssertionError("kümenin belirsiz seti boş")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    """tmp'de kurulu sentetik dünya; depodaki ``datasets/`` yalnız okunur."""
    folder = tmp_path_factory.mktemp("examples")
    mp = MonkeyPatch()
    mp.setattr(config, "ROOT", folder)
    mp.setenv("NL2SQL_DATASETS_DIR", str(ROOT / "datasets"))
    try:
        ds = datasets.load_dataset(DATASET)
        ds.db_path.parent.mkdir(parents=True, exist_ok=True)
        ds.build_db(db_path=ds.db_path, sql_path=folder / f"{DATASET}.sql")
        session = open_session(
            dataset=DATASET,
            llm="fake",
            audit_path=folder / "audit.jsonl",
            ask_log=folder / "asks.jsonl",
        )
    finally:
        mp.undo()
    return TestClient(
        create_app(session, saved_path=folder / "bilgin.db", static_dir=folder / "static")
    )


def test_examples_offer_the_first_ambiguous_question_after_the_golden_ones(client):
    examples = client.get("/api/examples").json()["examples"]
    golden, rest = examples[: config.EXAMPLES_N], examples[config.EXAMPLES_N:]

    assert {item["kind"] for item in golden} == {"golden"}
    assert [rest] == [[{"question": first_ambiguous_question(), "kind": "ambiguous"}]]
    assert all(sorted(item) == ["kind", "question"] for item in examples)


def test_mini_dataset_without_an_ambiguous_file_stays_all_golden(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    cli.build_database(dataset="mini")
    session = open_session(
        dataset="mini",
        llm="fake",
        audit_path=tmp_path / "audit.jsonl",
        ask_log=tmp_path / "asks.jsonl",
    )
    api = TestClient(
        create_app(session, saved_path=tmp_path / "bilgin.db", static_dir=tmp_path / "static")
    )

    examples = api.get("/api/examples").json()["examples"]
    assert examples and {item["kind"] for item in examples} == {"golden"}
    assert [item["question"] for item in examples] == [
        line["question"] for line in session.dataset.golden()[: len(examples)]
    ]
