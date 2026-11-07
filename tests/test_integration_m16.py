# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T194: M16 entegrasyonu — Run 5'in üç yüzü aynı gerçek dünyada, elle kurulmuş tek sahte yok.

Veritabanı kümenin kendi builder'ı, indeks gerçek ``cli.build_index``i (FakeEmbedder), istemci
``cli.make_client("fake")``ın altın kaydı, kapı gerçek ``open_session``ın üstündeki gerçek
``create_app``. Fazın iddiası üç cümle: ``eval --ambiguous --narrate`` hem ``full_rules`` hem
``rag``da belirsiz setin her sorusunu sorar, netleştirme kesinliği ve duyarlılığı 1'dir ve
doğruluk, aynı dünyada çıplak koşulan ``eval``in doğruluğundan farklı değildir — belirsiz set
altın cevabın yerine geçmez; A01 gerçek ``/api/ask``ta önce netleştirme sorar ve her şık kendi
okunuşunun SQL'inin satırlarını döndürür; ``eval-retrieval --summaries on`` iki kümede de her
soru için hem taban hem özet varyantını yazar.
"""

import json

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from nl2sql import config, datasets
from nl2sql.app.session import open_session
from nl2sql.cli import main as cli
from nl2sql.engine.result import Budget
from nl2sql.web.app import create_app

DATASET = "wwi"
DATASETS = ("wwi", "wwi")
# Run 5'in netleştirmeyi ölçtüğü iki bağlam: birinde kurallar bağlamda, diğerinde vektörler diskte.
MODES = ("full_rules", "rag")
# API'nin koştuğu bağlam: gerçek indeksin üstünde, yani aramanın da geçtiği kol.
API_MODE = "rag"
# Contracts Narration: cümleyi kuran üç kaynak.
SOURCES = ("llm", "llm_retry", "template")
# Cevabın satırları arayüz bütçesiyle koşar; karşılaştırma aynı bütçeyi ister.
UI = Budget(max_rows=config.UI_MAX_ROWS)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """wwi kümesinin tmp'de kurulu hali: db kümenin builder'ından, indeks gerçek ``build-index``ten.

    ``config.ROOT`` tmp'ye çevrilir ki kümenin kendi ``db_path``ı ve ``index_dir``i de tmp'nin
    altında kalsın; ``datasets/`` klasörünün kendisi okunur, üzerine yazılmaz.
    """
    folder = tmp_path_factory.mktemp("m16")
    mp = MonkeyPatch()
    mp.setattr(config, "ROOT", folder)
    mp.setattr(config, "AUDIT_LOG", folder / "cli-audit.jsonl")
    mp.setattr(config, "ASK_LOG", folder / "cli-asks.jsonl")
    ds = datasets.load_dataset(DATASET)
    ds.db_path.parent.mkdir(parents=True, exist_ok=True)
    ds.build_db(db_path=ds.db_path, sql_path=folder / f"{DATASET}.sql")
    assert cli.build_index("fake", dataset=DATASET) == 0, "sahte indeks kurulamadı"
    yield folder, ds
    mp.undo()


@pytest.fixture(scope="module")
def api(world):
    """Gerçek kapı: ``open_session``ın oturumu ile ``create_app``ın ``/api/ask``ı."""
    folder, _ = world
    session = open_session(
        dataset=DATASET,
        llm="fake",
        audit_path=folder / "api-audit.jsonl",
        ask_log=folder / "api-asks.jsonl",
    )
    client = TestClient(
        create_app(session, saved_path=folder / "bilgin.db", static_dir=folder / "static")
    )
    return session, client


def run_eval(world, mode, out_dir, **flags):
    """``evaluate``ın tek çağrısı: sahte kayıt modun kendi konuşmasını oynatır, out_dir altındaki rapor döner."""
    folder, ds = world
    code = cli.evaluate(
        cli.make_client("fake", mode, ds),
        mode=mode,
        db_path=ds.db_path,
        audit_path=folder / f"audit-{mode}.jsonl",
        out_dir=out_dir,
        dataset=DATASET,
        **flags,
    )
    return code, json.loads((out_dir / "latest" / "report.json").read_text(encoding="utf-8"))


def ask(client, question, **flags):
    body = client.post("/api/ask", json={"question": question, "mode": API_MODE, **flags}).json()
    assert body.get("error") is None, body.get("error")
    return body


# ------------------------------------------------- eval: belirsiz set ölçümü çıplak koşunun önüne geçmez

# ------------------------------------------------- API: sorulan soru, şıklar, her şıkkın kendi cevabı


# ------------------------------------------------- eval-retrieval: iki küme, iki varyant, her soru


@pytest.mark.parametrize("name", DATASETS)
def test_retrieval_with_summaries_scores_every_question_in_both_variants(name, tmp_path):
    out_dir = tmp_path / name

    assert cli.eval_retrieval("fake", dataset=name, out_dir=out_dir, summaries=True) == 0

    data = json.loads((out_dir / "latest" / "report.json").read_text(encoding="utf-8"))
    ids = {question["id"] for question in data["questions"]}
    assert ids, "ölçülecek soru yok"
    for variant in ("base", "summaries"):
        assert set(data["variants"][variant]["questions"]) == ids, f"{name}/{variant}"
