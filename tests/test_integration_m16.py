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

DATASET = "synthetic_erp"
DATASETS = ("synthetic_erp", "wwi")
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
    """sentetik dünyanın tmp'de kurulu hali: db kümenin builder'ından, indeks gerçek ``build-index``ten.

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

@pytest.mark.parametrize("mode", MODES)
def test_ambiguous_and_narrate_keep_the_plain_runs_accuracy(world, mode, tmp_path):
    code, plain = run_eval(world, mode, tmp_path / "plain")
    assert code == 0
    assert plain["narration"] is None, "çıplak koşu anlatmaz"
    assert plain["metrics"]["clarify_recall"] is None, "çıplak koşu netleştirme ölçmez"

    code, out = run_eval(world, mode, tmp_path / "ambiguous", ambiguous=True, narrate=True)
    assert code == 0
    metrics = out["metrics"]
    # Sahte kayıt belirsiz soruyu sorar, altın soruyu sorup tahmin etmez: ikisi de 1 (R5-12).
    assert metrics["clarify_precision"] == 1.0 and metrics["clarify_recall"] == 1.0
    # Belirsiz set altın cevabın yerine geçmez: doğruluk çıplak koşunun skoruyla aynı orandır.
    assert metrics["accuracy"] == round(plain["score"]["passed"] / plain["score"]["total"], 4)

    lines = datasets.load_dataset(DATASET).ambiguous()
    ambiguous = [question for question in out["questions"] if question["kind"] == "ambiguous"]
    assert [question["id"] for question in ambiguous] == [line["id"] for line in lines]
    assert {question["outcome"] for question in ambiguous} == {"clarified"}
    assert all(question["clarification"]["options"] for question in ambiguous), "şık satırda durur"

    submitted = [question for question in out["questions"] if question["submitted"]]
    assert sum(out["narration"][key] for key in SOURCES) == len(submitted)


# ------------------------------------------------- API: sorulan soru, şıklar, her şıkkın kendi cevabı


def test_a01_asks_first_and_every_option_answers_with_its_own_reading(world, api):
    session, client = api
    line = next(item for item in world[1].ambiguous() if item["id"] == "A01")

    asked = ask(client, line["question"])
    assert asked["status"] == "needs_clarification" and asked["mode"] == API_MODE
    assert asked["clarification"]["options"] == [r["label"] for r in line["readings"]]
    assert asked["sql"] == "" and asked["rows"] == [], "sorulan sorunun koşmuş bir SQL'i olmaz"

    answers = []
    for reading in line["readings"]:
        chosen = ask(client, line["question"], choice=reading["label"])
        assert chosen["status"] == "answered", "seçim aynı turda yeniden sormaz"
        assert chosen["choice"] == reading["label"] and chosen["clarification"] is None
        assert chosen["sql"] == reading["sql"]
        expected = session.executor.execute(reading["sql"], UI, "m16")
        assert chosen["columns"] == list(expected.columns)
        assert chosen["rows"] == [list(row) for row in expected.rows]
        answers.append((chosen["columns"], chosen["rows"]))
    given = {json.dumps(answer, ensure_ascii=False) for answer in answers}
    assert len(given) == len(line["readings"]), "her okunuş kendi cevabını vermeli"


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
