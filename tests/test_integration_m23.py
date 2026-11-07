# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T315: M23 entegrasyonu — zincir, threadin okunuşu ve replay tek gerçek kapıda (PLAN R7-13, R7-14).

Elle kurulmuş sahte parça yok: oturum ``open_session``dan, model ``cli.make_client``ın altın kaydı,
kapı ``create_app``ten, uygulamanın kendi veritabanı tmp'de. F02 zinciri ``POST /api/ask``tan tur
tur geçer ve kimlikler yalnız yanıtlardan okunur. İddia: üç tur tek konuşmadır; threadi
``GET /api/conversations/{id}`` ile okumak yürütücünün denetim günlüğünü büyütmez; birinci turun
``audit_id``si ``POST /api/replay``de modelsiz aynı SQL olarak yeniden koşar ve konuşmaya tur
eklemez; ``eval --followups --llm fake`` kümenin bütün zincirlerini ``report.json``a %100 yazar.
"""

import json
from pathlib import Path
from typing import NamedTuple

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from nl2sql import config
from nl2sql.app.session import Session, open_session
from nl2sql.cli import main as cli
from nl2sql.datasets import load_dataset
from nl2sql.web.app import create_app

REPO = Path(__file__).resolve().parents[1]
DATASET = "synthetic_erp"
MODE = "full"
CHAINS = {chain["id"]: chain for chain in load_dataset(DATASET).followups()}
F02 = CHAINS["F02"]
# Konsolun ardışık soru toplamı (R7-14): üç doğruluğun hepsi yüzde olarak okunur.
PERFECT = "Toplam: tur %100,00 · zincir %100,00 · bağlam %100,00"


class World(NamedTuple):
    """Akışın koştuğu tmp dünyası: oturum, kapı ve uygulamanın kendi dosyalarının kökü."""

    root: Path
    session: Session
    client: TestClient


def ask(client, question, conversation_id=None) -> dict:
    """``POST /api/ask``ın cevabı; cevaplanmayan bir soru testin kendisini düşürür."""
    response = client.post(
        "/api/ask",
        json={"question": question, "mode": MODE, "conversation_id": conversation_id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "answered", body.get("error")
    return body


def lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines()) if path.is_file() else 0


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """Kümenin kendi kurduğu dünya: ``config.ROOT`` tmp'de, ``datasets/`` okunur, uygulama dosyası tmp'de.

    ``evaluate``ın denetim günlüğü argümanla geçilmez ve varsayılanı import'da bağlandığı için
    gerçek koşum repoya yazardı; burada yalnız yolu değiştirilir, çağrılan fonksiyon gerçektir.
    """
    root = tmp_path_factory.mktemp("m23")
    mp = MonkeyPatch()
    mp.setattr(config, "ROOT", root)
    mp.setenv("NL2SQL_DATASETS_DIR", str(REPO / "datasets"))
    mp.setenv("NL2SQL_REAL_DATASETS_DIR", str(root / "real_datasets"))
    mp.setenv("NL2SQL_APP_DB", str(root / "bilgin.db"))
    mp.setenv("NL2SQL_BACKEND", "sqlite")
    evaluate = cli.evaluate
    mp.setattr(
        cli, "evaluate", lambda **kwargs: evaluate(audit_path=root / "eval-audit.jsonl", **kwargs)
    )

    load_dataset(DATASET).build_db()
    session = open_session(
        dataset=DATASET,
        llm="fake",
        audit_path=root / "logs" / "audit.jsonl",
        ask_log=root / "logs" / "asks.jsonl",
    )
    client = TestClient(
        create_app(session, saved_path=root / "bilgin.db", static_dir=root / "static")
    )
    yield World(root, session, client)
    mp.undo()


@pytest.fixture(scope="module")
def thread(world):
    """F02 ekranın kapısından geçip tek konuşma olmuş: ``(kimlik, payloadlar)``; kimlik yanıttan."""
    payloads = []
    for turn in F02["turns"]:
        payloads.append(
            ask(world.client, turn["question"],
                payloads[0]["conversation_id"] if payloads else None)
        )
    assert len({item["conversation_id"] for item in payloads}) == 1, "üç tur tek konuşmadır"
    return payloads[0]["conversation_id"], payloads


# ------------------------------------------------------------------ F02 /api/asktan


def test_the_three_turns_of_the_chain_are_one_conversation(thread):
    conversation_id, payloads = thread

    assert [item["turn"] for item in payloads] == [1, 2, 3]
    assert [item["dataset"] for item in payloads] == [DATASET] * 3
    assert [item["sql"] for item in payloads] == [turn["sql"] for turn in F02["turns"]]
    assert payloads[0]["context"] is None, "ilk turun dayandığı tur yok"
    assert payloads[1]["context"]["uses_turns"] == [1]
    assert payloads[2]["context"]["refines_sql_of"] == 2, "sunum değişikliği ikinci turun sorgusuna bakar"
    assert payloads[2]["chart"]["type"] == "bar" and payloads[2]["rows"] == payloads[1]["rows"]


# ------------------------------------------------------------------ GET /api/conversations/{id}


def test_reading_the_thread_back_runs_no_query(world, thread):
    conversation_id, payloads = thread
    before = lines(world.session.audit_path)
    assert before > 0, "zincir koşarken denetim satırı bıraktı"

    body = world.client.get(f"/api/conversations/{conversation_id}").json()

    assert lines(world.session.audit_path) == before, "threadi okumak SQL koşmaz"
    assert body["conversation"]["id"] == conversation_id
    assert body["conversation"]["dataset"] == DATASET
    assert body["conversation"]["title"] == payloads[0]["question"][: config.CONV_TITLE_CHARS]
    assert [turn["n"] for turn in body["turns"]] == [1, 2, 3]
    for turn, item in zip(body["turns"], payloads):
        assert turn["status"] == "answered" and turn["sql"] == item["sql"]
        assert turn["question"] == item["question"] and turn["answer_text"] == item["answer_text"]
        assert turn["audit_id"] == item["audit_id"], "tur kendi denetim satırına bağlıdır"
        assert turn["summary"]["columns"] == item["columns"]
        assert turn["summary"]["row_count"] == item["row_count"]
        assert len(turn["summary"]["rows"]) == min(item["row_count"], config.CONV_KEEP_ROWS)
    assert body["turns"][1]["summary"]["context"]["uses_turns"] == [1]
    assert body["turns"][2]["summary"]["chart_kind"] == "bar"


# ------------------------------------------------------------------ POST /api/replay/{audit_id}


def test_the_first_turn_replays_from_its_own_stored_query(world, thread):
    conversation_id, payloads = thread

    body = world.client.post(f"/api/replay/{payloads[0]['audit_id']}").json()

    assert body["status"] == "answered" and body["error"] is None
    assert body["sql"] == payloads[0]["sql"], "replay kayıtlı SQLi aynıyla koşar"
    assert body["rows"] == payloads[0]["rows"] and body["row_count"] == payloads[0]["row_count"]
    assert [step["tool"] for step in body["steps"]] == ["replay"], "model SQL yazmadı"
    assert body["audit_id"] != payloads[0]["audit_id"], "yeniden koşum kendi satırını açar"

    history = world.client.get("/api/history").json()["history"]
    assert [item["audit_id"] for item in history] == [
        body["audit_id"], *[item["audit_id"] for item in reversed(payloads)]
    ]
    turns = world.client.get(f"/api/conversations/{conversation_id}").json()["turns"]
    assert [turn["n"] for turn in turns] == [1, 2, 3], "replay konuşmaya tur ekmez"


# ------------------------------------------------------------------ eval --followups


def test_the_chain_eval_through_the_command_line_writes_a_full_score(world, capsys):
    capsys.readouterr()

    code = cli.main(["eval", "--dataset", DATASET, "--llm", "fake", "--followups"])
    out = capsys.readouterr().out

    assert code == 0, out
    report = json.loads(
        (world.root / "eval_out" / MODE / "latest" / "report.json").read_text(encoding="utf-8")
    )
    followups = report["followups"]
    assert followups["chains"] == len(CHAINS)
    assert followups["turn_accuracy"] == 1.0
    assert followups["chain_accuracy"] == 1.0
    assert followups["context_accuracy"] == 1.0
    assert PERFECT in out
