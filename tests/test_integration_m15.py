# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T183: M15 entegrasyonu — iki gerçek dünya, gerçek indeks, rapor katmanının kendi hükmü.

Dünya gerçek ``load_dataset``ın kendi builder'ı, indeks gerçek ``cli.build_index``i (FakeEmbedder),
kapı gerçek ``open_session``ın üstündeki gerçek ``create_app``: elle kurulmuş tek bir
Session/Result/Fact yok. Fazın iddiası üç cümle: iki dünyanın her altın sorusu ``rag`` modunda
``/api/ask``ta cevaplanır ve dönen grafiğin her biri ya hiç yoktur ya da ``validate_option``den temiz
geçer; her cevabın cümlesi kendi satırları ve kendi olgularıyla bekçinin sayı listesini geçer;
kural API'sinden giren bir kural diskteki indeksi ``FileStore.load_checked`` için bayatlatır ve
``POST /api/index/rebuild`` onu yeniden taze yapar. Anlatının kaynağı sayılır ve yazılır — kaç cümleyi
LLM'in kurduğu bir gözlemdir, iddia değil.
"""

import shutil
from collections import Counter

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from bilgin import config, datasets
from bilgin.app.session import open_session
from bilgin.cli import main as cli
from bilgin.index.store import FileStore, StaleIndexError, content_hash
from bilgin.report import guard
from bilgin.report.chart import validate_option
from bilgin.web.app import create_app

DATASETS = ("synthetic_erp", "wwi")
# M15'in indeksi gerçek: altın kayıt diskteki sahte vektör uzayının üstünde oynanır.
MODE = "rag"
# Contracts Narration: cümleyi kuran üç kaynak.
SOURCES = ("llm", "llm_retry", "template")

# Kural API'sinden giren kural: kümenin gerçek şemasındaki gerçek bir tabloyu anlatır ve kimliği
# kümenin kendi kurallarında yoktur (olsaydı POST 409'a düşerdi).
RULE = {
    "id": "sepet_ortalamasi",
    "term": "Sepet ortalaması",
    "synonyms": ["ortalama fatura"],
    "definition": "Fatura başına ortalama tutar: iptal edilmemiş faturaların toplamının fatura sayısına bölünmesi.",
    "sql_hint": "SUM(GENELTOPLAM) / COUNT(DISTINCT FISHDRK)",
    "tables": ["TBLFATUIRS"],
    "markers": [r"COUNT\s*\(\s*DISTINCT\s*(?:\w+\.)?FISHDRK"],
}


def ask(client, question):
    body = client.post("/api/ask", json={"question": question, "mode": MODE}).json()
    assert body["status"] == "answered", body.get("error")
    return body


def signature(session) -> str:
    """Oturumun bugün ölçtüğü içerik imzası: meta'daki imzadan farkı, indeksin bayatlığının kendisi."""
    return content_hash(session.schema, session.rules)


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """İki dünyanın tmp'de kurulu dünyası: db gerçek builder'dan, indeks gerçek ``build-index``ten.

    ``config.ROOT`` tmp'ye çevrilir ki kümenin kendi ``db_path``ı ve ``index_dir``i de tmp'nin
    altında kalsın; ``datasets/`` klasörünün kendisi okunur, üzerine yazılmaz.
    """
    folder = tmp_path_factory.mktemp("m15")
    mp = MonkeyPatch()
    mp.setattr(config, "ROOT", folder)
    mp.setattr(config, "AUDIT_LOG", folder / "cli-audit.jsonl")
    mp.setattr(config, "ASK_LOG", folder / "cli-asks.jsonl")
    built = {}
    for name in DATASETS:
        ds = datasets.load_dataset(name)
        ds.db_path.parent.mkdir(parents=True, exist_ok=True)
        ds.build_db(db_path=ds.db_path, sql_path=folder / f"{name}.sql")
        assert cli.build_index("fake", dataset=name) == 0, "sahte indeks kurulamadı"
        session = open_session(
            dataset=name,
            llm="fake",
            audit_path=folder / f"{name}-audit.jsonl",
            ask_log=folder / f"{name}-asks.jsonl",
        )
        client = TestClient(
            create_app(session, saved_path=folder / f"bilgin-{name}.db", static_dir=folder / "static")
        )
        built[name] = (ds, session, client)
    yield folder, built
    mp.undo()


@pytest.fixture(scope="module")
def answers(world):
    """Her altın sorunun gerçek ``/api/ask`` cevabı: üç denetim tek koşumun üstünde okunur."""
    out = {}
    for name in DATASETS:
        ds, _, client = world[1][name]
        out[name] = [(line, ask(client, line["question"])) for line in ds.golden()]
    return out


@pytest.fixture
def editable(tmp_path, monkeypatch, capsys):
    """Kümenin tmp kopyası: kural API'si kural dosyasını buraya yazar, asıl küme okunur kalır."""
    name = "synthetic_erp"
    root = tmp_path / "datasets"
    shutil.copytree(datasets.load_dataset(name).root, root / name)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("BILGIN_DATASETS_DIR", str(root))
    ds = datasets.load_dataset(name)
    ds.db_path.parent.mkdir(parents=True, exist_ok=True)
    ds.build_db(db_path=ds.db_path, sql_path=tmp_path / f"{name}.sql")
    assert cli.build_index("fake", dataset=name) == 0
    capsys.readouterr()
    session = open_session(
        dataset=name,
        llm="fake",
        audit_path=tmp_path / "audit.jsonl",
        ask_log=tmp_path / "asks.jsonl",
    )
    client = TestClient(
        create_app(session, saved_path=tmp_path / "bilgin.db", static_dir=tmp_path / "static")
    )
    return session, client


# ------------------------------------------------- grafik: ya yok ya da çizilebilir

@pytest.mark.parametrize("name", DATASETS)
def test_every_chart_is_none_or_a_valid_option(name, answers):
    for line, body in answers[name]:
        chart = body["chart"]
        assert chart is None or validate_option(chart["option"]) == [], line["id"]


# ------------------------------------------------- cümle: kendi satır ve olgularının sayılarıyla

@pytest.mark.parametrize("name", DATASETS)
def test_every_answer_text_passes_the_number_guard(name, answers):
    for line, body in answers[name]:
        allowed = guard.allowed_values(
            body["columns"], body["rows"], body["facts"], body["question"]
        )
        verdict = guard.check_text(body["answer_text"], allowed)
        assert verdict.ok, f"{line['id']}: {verdict.offending} satırlarda ve olgularda yok"


# ------------------------------------------------- anlatımın kaynağı: sayılır, yazılır

@pytest.mark.parametrize("name", DATASETS)
def test_narration_sources_are_counted(name, answers):
    sources = Counter(body["narration_source"] for _, body in answers[name])

    assert set(sources) <= set(SOURCES)
    assert all(body["answer_text"] for _, body in answers[name]), "cevap cümlesiz bırakılamaz"
    print(
        f"{name}: {len(answers[name])} soru, anlatım {dict(sources)}, "
        f"grafikli {sum(1 for _, body in answers[name] if body['chart'])}"
    )


# ------------------------------------------------- kural -> bayat indeks -> yeniden kurma

def test_a_rule_written_by_the_api_stales_the_index_and_the_rebuild_clears_it(editable):
    session, client = editable
    store = FileStore(session.index_dir)
    dataset = session.dataset.name
    store.load_checked(signature(session), dataset)

    assert client.post("/api/rules", json=RULE).status_code == 200
    assert client.get("/api/health").json()["index"]["fresh"] is False
    with pytest.raises(StaleIndexError):
        store.load_checked(signature(session), dataset)

    rebuilt = client.post("/api/index/rebuild")

    assert rebuilt.status_code == 200
    assert sum(rebuilt.json()["counts"].values()) > 0
    store.load_checked(signature(session), dataset)
    assert client.get("/api/health").json()["index"]["fresh"] is True
