"""T211: ``serve`` kümesi söylenmemiş dünyayı da sunar (R5-11, R5-15).

``--dataset`` yazılmadığında başlığın çipi ``synthetic_erp`` diyordu ama oturum kümesiz kuruluyordu:
sahte istemci belirsiz kaydı hiç görmediği için A01 kart açacağı yerde ``fake_fallback_sql``in
satırlarını döndürüyordu - README'nin model olmadan kurulan demosunda R5-11'in kartı hiç
görünmüyordu. Burada dünya gerçek: db kümenin kendi builder'ı, indeks ``cli.build_index``in sahte
embedder'ı, kapı ``cli.serve``in kurduğu kapı. Sunucu ayağa kalkmaz, ``run_server`` yerine geçilir.
"""

import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from nl2sql import config, datasets
from nl2sql.cli import main as cli
from nl2sql.web import app as web_app

DATASET = "synthetic_erp"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """tmp'de kurulu sentetik dünya; depodaki ``datasets/`` yalnız okunur."""
    folder = tmp_path_factory.mktemp("serve-default")
    mp = MonkeyPatch()
    mp.setattr(config, "ROOT", folder)
    mp.setenv("NL2SQL_DATASETS_DIR", str(folder / "datasets"))
    shutil.copytree(ROOT / "datasets" / DATASET, folder / "datasets" / DATASET)
    ds = datasets.load_dataset(DATASET)
    ds.db_path.parent.mkdir(parents=True, exist_ok=True)
    ds.build_db(db_path=ds.db_path, sql_path=folder / f"{DATASET}.sql")
    assert cli.build_index("fake", dataset=DATASET) == 0, "sahte indeks kurulamadı"
    yield folder, ds
    mp.undo()


def serve_app(folder, dataset):
    """Gerçek ``serve``ın kurduğu oturum ve kapı; günlükler ve kayıtlar tmp'de, sunucu kapalı."""
    mp = MonkeyPatch()
    mp.setenv("NL2SQL_DATASETS_DIR", str(folder / "datasets"))
    mp.setattr(config, "AUDIT_LOG", folder / "audit.jsonl")
    mp.setattr(config, "ASK_LOG", folder / "asks.jsonl")
    create_app = web_app.create_app
    mp.setattr(
        web_app,
        "create_app",
        lambda session: create_app(
            session, saved_path=folder / "bilgin.db", static_dir=folder / "static"
        ),
    )
    seen: dict = {}
    mp.setattr(cli, "run_server", lambda app, host, port: seen.update(app=app))
    try:  # küme burada okunur; oturum yolları taşıdığı için env sonra geri alınabilir
        assert cli.serve(llm_kind="fake", dataset=dataset) == 0
    finally:
        mp.undo()
    return seen["app"].state.session, TestClient(seen["app"])


def test_serve_without_a_dataset_serves_the_world_the_chip_names(world):
    folder, ds = world

    session, client = serve_app(folder, None)

    assert session.dataset is not None, "çip küme adını söylüyor, sunulan dünya değil"
    assert session.dataset.name == DATASET
    assert client.get("/api/health").json()["dataset"]["name"] == DATASET
    assert session.db_path == ds.db_path and session.index_dir == ds.index_dir


@pytest.mark.parametrize("dataset", [None, DATASET])
def test_the_ambiguous_question_asks_its_three_readings(world, dataset):
    """Küme söylenmiş de söylenmemiş de olsun, A01 üç okunuşu birden sorar."""
    folder, ds = world
    line = next(item for item in ds.ambiguous() if item["id"] == "A01")
    _, client = serve_app(folder, dataset)

    body = client.post("/api/ask", json={"question": line["question"]}).json()

    assert body["error"] is None, body["error"]
    assert body["dataset"] == DATASET
    assert body["status"] == "needs_clarification", "kart açılmadı, cevap düşmüş"
    assert body["clarification"]["options"] == [reading["label"] for reading in line["readings"]]
