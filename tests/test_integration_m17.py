"""T204: M17 entegrasyonu — derlenmiş ekranın arkasında gerçek dünya, elle kurulmuş tek sahte yok.

Veritabanı kümenin kendi builder'ı, indeks gerçek ``cli.build_index``i (sahte embedder), kapı
gerçek ``open_session``ın üstündeki gerçek ``create_app``, statik dizin ``npm --prefix web run
build``ın çıktısı. Uçtan uca dört cümle: ``/`` derlenmiş sayfayı ve onun ``/assets``ini sunar;
``/api/ask`` altın soruyu cevaplar, belirsiz soruyu sorar ve seçilen şıkkın SQL'ini koşar; cevabın
CSV'i ile geçmişi aynı ``audit_id``de birleşir; bir kural tmp'deki kopyada eklenip değiştirilip
silinir ve depodaki ``datasets/``e tek bayt yazılmaz. Son iddia cephenin kendi sözleşmesi:
``web/src/fixtures`` altındaki her örnek, aynı durumun gerçek ``/api/ask`` cevabıyla birebir aynı
anahtarları taşır — ekran örnekleri API'den koptuğu an burada kırmızı yanar.
"""

import codecs
import json
import re
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from nl2sql import config, datasets
from nl2sql.app.session import open_session
from nl2sql.cli import main as cli
from nl2sql.engine.result import Budget
from nl2sql.web.app import BUILD_COMMAND, NO_UI, create_app

DATASET = "wwi"
# Kuralın da aramanın da geçtiği kol: ``serve``in varsayılanı auto, auto da burada rag'a düşer.
API_MODE = "rag"
# Cevabın satırları arayüz bütçesiyle koşar; karşılaştırma aynı bütçeyi ister.
UI = Budget(max_rows=config.UI_MAX_ROWS)
ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "web" / "src" / "fixtures"
BOM = codecs.BOM_UTF8
ASSET = re.compile(r'(?:src|href)="(/assets/[^"]+)"')
# Contracts "rule": normalize_rule'un yedi alanı, sırasıyla; diskte okunacak biçim de budur.
NEW_RULE = {
    "id": "m17_kural",
    "term": "hareket",
    "synonyms": ["stok hareketi"],
    "definition": "Girişlerden çıkışlar düşülür.",
    "sql_hint": "HAREKET_YONU",
    "tables": ["STOK_HAREKET"],
    "markers": ["hareket"],
}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """tmp'de kurulu wwi kümesi; kümenin iki kopyası var: dünya ve kural turunun kopyası.

    ``config.ROOT`` tmp'ye çevrilir ki db ile indeks de oraya yazılsın; ``NL2SQL_DATASETS_DIR``
    kopyalara bakar, depodaki ``datasets/`` klasörü yalnız okunur.
    """
    folder = tmp_path_factory.mktemp("m17")
    mp = MonkeyPatch()
    mp.setattr(config, "ROOT", folder)
    mp.setenv("NL2SQL_DATASETS_DIR", str(folder / "datasets"))
    for name in ("datasets", "rules"):
        shutil.copytree(ROOT / "datasets" / DATASET, folder / name / DATASET)
    ds = datasets.load_dataset(DATASET)
    ds.db_path.parent.mkdir(parents=True, exist_ok=True)
    ds.build_db(db_path=ds.db_path, sql_path=folder / f"{DATASET}.sql")
    assert cli.build_index("fake", dataset=DATASET) == 0, "sahte indeks kurulamadı"
    yield folder, ds
    mp.undo()


def open_api(folder, name, datasets_dir, **flags):
    """Kümenin verilen kopyası üstünde gerçek oturum ve gerçek kapı; aynı db, aynı indeks."""
    mp = MonkeyPatch()
    mp.setenv("NL2SQL_DATASETS_DIR", str(datasets_dir))
    try:  # küme burada okunur; oturum yolları taşıdığı için env sonra geri alınabilir
        session = open_session(
            dataset=DATASET,
            llm="fake",
            audit_path=folder / f"{name}-audit.jsonl",
            ask_log=folder / f"{name}-asks.jsonl",
            **flags,
        )
    finally:
        mp.undo()
    client = TestClient(
        create_app(session, saved_path=folder / f"{name}.db", static_dir=config.STATIC_DIR)
    )
    return session, client


@pytest.fixture(scope="module")
def api(world):
    folder, ds = world
    return open_api(folder, "api", ds.root.parent)


@pytest.fixture(scope="module")
def rules_api(world):
    """Kural turunun kendi kapısı: ikinci kopya, böylece dünyanın indeksi taze kalır."""
    folder, _ = world
    return open_api(folder, "rules", folder / "rules")


@pytest.fixture(scope="module")
def no_index_api(world):
    """İndeksi olmayan oturum: rag'ın cevabı bir koşum değil, hatadır."""
    folder, ds = world
    return open_api(folder, "indeks", ds.root.parent, index_dir=folder / "indeks-yok")


@pytest.fixture(scope="module")
def questions(world):
    """API'nin koştuğu iki soru: birinin cevabı var, diğeri önce sormak zorunda."""
    ds = world[1]
    return {
        "Q02": next(line for line in ds.golden() if line["id"] == "Q02"),
        "A01": next(line for line in ds.ambiguous() if line["id"] == "A01"),
    }


def ask(client, question, **flags):
    body = client.post("/api/ask", json={"question": question, "mode": API_MODE, **flags}).json()
    assert body.get("error") is None, body["error"]
    return body


# ------------------------------------------------------------------ derlenmiş ekran


def test_the_built_page_and_every_asset_it_loads_are_served(api):
    if not (config.STATIC_DIR / "index.html").is_file():
        pytest.skip(f"arayüz derlenmemiş: {BUILD_COMMAND}")
    _, client = api

    page = client.get("/")

    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    assert "Bilgin" in page.text
    assert NO_UI not in page.text, "yedek sayfa geliyor, ekran değil"
    assets = ASSET.findall(page.text)
    assert assets, "derlenmiş sayfanın yüklediği bir dosya olmalı"
    for url in assets:
        assert client.get(url).status_code == 200, f"{url} sayfada var, sunucuda yok"


# ------------------------------------------------------------------ soru, şık, indirme, geçmiş


# ------------------------------------------------------------------ kural turu: tmp'deki kopyada


# ------------------------------------------------------------------ cephenin sözleşmesi


@pytest.fixture(scope="module")
def real_payloads(api, no_index_api, questions):
    """Her durumun gerçek cevabı API'den: cevaplı, sorulan ve başarısız."""
    _, client = api
    _, broken = no_index_api

    failed = broken.post("/api/ask", json={"question": questions["Q02"]["question"], "mode": API_MODE})
    assert failed.status_code == 200 and failed.json()["error"]["kind"] == "index"
    return {
        "answered": ask(client, questions["Q02"]["question"]),
        "needs_clarification": ask(client, questions["A01"]["question"]),
        "failed": failed.json(),
    }


