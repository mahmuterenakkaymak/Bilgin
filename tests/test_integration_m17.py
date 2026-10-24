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

DATASET = "synthetic_erp"
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
    "sql_hint": "STHAR_GCKOD",
    "tables": ["TBLSTHAR"],
    "markers": ["hareket"],
}


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """tmp'de kurulu sentetik dünya; kümenin iki kopyası var: dünya ve kural turunun kopyası.

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


def test_q02_is_answered_with_the_rows_the_executor_measures(api, questions):
    session, client = api
    line = questions["Q02"]

    body = ask(client, line["question"])

    assert body["status"] == "answered" and body["mode"] == API_MODE
    assert body["sql"] == line["sql"]
    expected = session.executor.execute(line["sql"], UI, "m17")
    assert body["columns"] == list(expected.columns)
    assert body["rows"] == [list(row) for row in expected.rows]
    assert body["answer_text"] and body["clarification"] is None


def test_a01_asks_first_and_option_zero_answers_with_its_own_reading(api, questions):
    _, client = api
    line = questions["A01"]

    asked = ask(client, line["question"])
    assert asked["status"] == "needs_clarification"
    assert asked["clarification"]["options"] == [reading["label"] for reading in line["readings"]]

    option = asked["clarification"]["options"][0]
    chosen = ask(client, line["question"], choice=option)
    assert chosen["status"] == "answered" and chosen["choice"] == option
    assert chosen["clarification"] is None, "seçim aynı turda yeniden sormaz"
    assert chosen["sql"] == line["readings"][0]["sql"]


def test_an_answered_question_downloads_its_whole_csv(api, questions):
    _, client = api
    body = ask(client, questions["Q02"]["question"])

    download = client.get(f"/api/export/{body['audit_id']}.csv")

    assert download.status_code == 200
    assert download.headers["content-type"].startswith("text/csv")
    assert download.headers["content-disposition"].endswith(f'bilgin_{body["audit_id"]}.csv"')
    assert download.content.startswith(BOM), "Excel UTF-8'i BOM'suz tanımaz"
    lines = download.content.decode("utf-8-sig").splitlines()
    assert lines[0].split(";") == body["columns"]
    assert len(lines) == 1 + len(body["rows"])


def test_history_lists_the_newest_ask_first_without_rows(api, questions):
    _, client = api

    answered = ask(client, questions["Q02"]["question"])
    items = client.get("/api/history").json()["history"]
    assert items[0]["audit_id"] == answered["audit_id"]
    assert items[0]["status"] == "answered" and items[0]["question"] == questions["Q02"]["question"]
    assert "rows" not in items[0], "geçmiş veri satırı taşımaz"

    asked = ask(client, questions["A01"]["question"])
    items = client.get("/api/history").json()["history"]
    assert items[0]["audit_id"] == asked["audit_id"]
    assert items[0]["status"] == "needs_clarification", "sorulan soru da geçmişe düşer"


# ------------------------------------------------------------------ kural turu: tmp'deki kopyada


def test_a_rule_round_trips_through_the_api_and_the_copy_on_disk(rules_api, world):
    session, client = rules_api
    original = [rule["id"] for rule in session.rules]
    path = session.dataset.rules_path
    assert path.parent == world[0] / "rules" / DATASET, "kural turu tmp'deki kopyada koşar"
    assert client.get("/api/rules").json()["index"]["fresh"] is True

    added = client.post("/api/rules", json=NEW_RULE).json()
    assert [rule["id"] for rule in added["rules"]] == original + [NEW_RULE["id"]]
    assert added["index"]["fresh"] is False, "kurallar değişti, indeks bayatladı"
    assert json.loads(path.read_text(encoding="utf-8"))["rules"][-1] == NEW_RULE

    edited = client.put(f"/api/rules/{NEW_RULE['id']}", json={**NEW_RULE, "term": "net hareket"}).json()
    assert edited["rules"][-1]["term"] == "net hareket"

    removed = client.delete(f"/api/rules/{NEW_RULE['id']}").json()
    assert [rule["id"] for rule in removed["rules"]] == original
    assert removed["index"]["fresh"] is True, "kurallar başa döndü, indeks yine taze"
    assert datasets.load_dataset(DATASET).rules() == session.rules, "depodaki küme değişmedi"


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


@pytest.mark.parametrize("name", sorted(path.name for path in FIXTURES.glob("*.json")))
def test_a_frontend_example_carries_the_real_payloads_keys(name, real_payloads):
    example = json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    real = real_payloads[example["status"]]

    assert sorted(example) == sorted(real), f"{name}: {set(example) ^ set(real)}"
