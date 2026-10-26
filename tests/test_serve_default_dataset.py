"""T211: ``serve`` kümesi söylenmemiş dünyayı da sunar (R5-11, R5-15).

``--dataset`` yazılmadığında başlığın çipi ``synthetic_erp`` diyordu ama oturum kümesiz kuruluyordu:
sahte istemci belirsiz kaydı hiç görmediği için A01 kart açacağı yerde ``fake_fallback_sql``in
satırlarını döndürüyordu - README'nin model olmadan kurulan demosunda R5-11'in kartı hiç
görünmüyordu. Burada dünya gerçek: db kümenin kendi builder'ı, indeks ``cli.build_index``in sahte
embedder'ı, kapı ``cli.serve``in kurduğu kapı. Sunucu ayağa kalkmaz, ``run_server`` yerine geçilir.

T357 (alttaki blok): ``--dataset`` söylenmemişse sıra ayardaki küme → vitrin kümesi → indeksi kurulu
ilk küme → ``DEFAULT_DATASET``; vitrin kümesi ``wwi``, yani model olmadan koşan incelemenin dünyasıdır.
"""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from nl2sql import config, datasets
from nl2sql.agent import fake
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.engine.executor import LocalExecutor
from nl2sql.engine.result import Budget
from nl2sql.index.store import META_FILE
from nl2sql.policy import policy
from nl2sql.schema_map import doc
from nl2sql.web import app as web_app
from nl2sql.web.datasets_api import ACTIVE_SETTING

DATASET = "synthetic_erp"
ROOT = Path(__file__).resolve().parent.parent
PAROLA = "Bilgin2026!erp"


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
    mp.setenv("NL2SQL_APP_DB", str(folder / "bilgin.db"))
    mp.setattr(config, "AUDIT_LOG", folder / "audit.jsonl")
    mp.setattr(config, "ASK_LOG", folder / "asks.jsonl")
    # R6-7: serve kullanıcı deposu olmadan dinlemeye başlamaz; dünyanın bir yöneticisi var.
    users = UserStore(folder / "bilgin.db")
    if not users.count_users():
        users.add_user("admin", PAROLA, "admin")
    create_app = web_app.create_app
    mp.setattr(
        web_app,
        "create_app",
        lambda session, **kwargs: create_app(session, static_dir=folder / "static", **kwargs),
    )
    seen: dict = {}
    mp.setattr(cli, "run_server", lambda app, host, port: seen.update(app=app))
    try:  # küme burada okunur; oturum yolları taşıdığı için env sonra geri alınabilir
        assert cli.serve(llm_kind="fake", dataset=dataset) == 0
    finally:
        mp.undo()
    # R6-9: serve ``saved_path``ı kendisi taşır; kayıtlar kullanıcının dosyasındadır.
    assert seen["app"].state.saved_path == folder / "bilgin.db"
    client = TestClient(seen["app"])
    # R6-7: sunulan kapı oturum ister, o yüzden soruyu soran ekran gibi önce giriş yapılır.
    login = client.post("/api/auth/login", json={"username": "admin", "password": PAROLA})
    assert login.status_code == 200, login.text
    return seen["app"].state.session, client


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


# ------------------------------------------------------------------ T357: hangi dünya sunulur

# Görsel akışın (.hybrid/visual.json) sorduğu iki soru ve zincirin devamı: vitrin kümesi bunların
# hepsine model olmadan kurulmuş bir cevap vermek zorunda, yoksa inceleme boş ekran görüntüler.
VISUAL_GOLDEN = "Eylül 2026'da en çok satan 5 ürün hangileri; kodu, adı ve toplam satış miktarı nedir?"
VISUAL_FOLLOW_UP = "Bunlardan hangisi en çok ciro yaptı?"
VISUAL_AMBIGUOUS = "Eylül 2026'da satışlarımız ne kadar?"

# Okumalar karşılaştırılacağı için satır kesilmez (PLAN Decision 8).
COMPARE = Budget(max_rows=config.COMPARE_MAX_ROWS)


def write_datasets(root: Path, names, indexed=()):
    """``root`` altına bir datasets kökü: her küme yalnız ``dataset.json``uyla, indeksi ``indexed`` söyler."""
    for name in names:
        folder = root / "datasets" / name
        folder.mkdir(parents=True)
        (folder / "dataset.json").write_text(
            json.dumps(
                {
                    "name": name,
                    "as_of": "2026-01-31",
                    "builder": "builder.py:build_db",
                    "generator": "builder.py:generate",
                    "references": "reference.py:REFERENCES",
                    "outputs": {"index_dir": f"index/{name}"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    for name in indexed:
        index = root / "index" / name
        index.mkdir(parents=True, exist_ok=True)
        (index / META_FILE).write_text("{}", encoding="utf-8")


def remember(name: str) -> None:
    """Ekranda yapılmış bir küme geçişinin ayara bıraktığı değer (R6-11)."""
    UserStore(config.app_db_path()).set_setting(ACTIVE_SETTING, name)


def asked(client, question: str, earlier=(), turns: int = 3):
    """Sahte istemcinin bir soru için kurduğu tur dizisi: araç adları, gönderilen SQL, şıklar.

    ``earlier`` konuşmanın önceki turlarının soruları: zincirin bir turu ancak onlarla tanınır,
    yani history bloğunun yazdığı ``Tur n sorusu:`` satırları buradan geliyor.
    """
    messages = [
        {
            "role": "system",
            "content": "\n".join(f"Tur {n} sorusu: {q}" for n, q in enumerate(earlier, 1)),
        },
        {"role": "user", "content": question},
    ]
    names, submitted, options = [], None, None
    for _ in range(turns):
        answer = client.chat(messages)
        for call in answer.tool_calls:
            names.append(call.name)
            submitted = call.arguments.get("sql", submitted)
            options = call.arguments.get("options", options)
        messages.append({"role": "assistant", "content": answer.content})
    return names, submitted, options


@pytest.fixture
def served(tmp_path, monkeypatch):
    """Sunucunun küme sırasının baktığı dünya: tmp kök, tmp ayar dosyası, sunucu hiç yok."""
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(tmp_path / "datasets"))
    monkeypatch.setenv("NL2SQL_APP_DB", str(tmp_path / "bilgin.db"))
    return tmp_path


@pytest.fixture(scope="module")
def demo_world(tmp_path_factory):
    """Vitrin kümesi depodaki klasörüyle: kurulu db'si, kendi şeması, kendi okuma dosyaları."""
    mp = MonkeyPatch()
    mp.delenv("NL2SQL_DATASETS_DIR", raising=False)  # yukarıdaki ``world`` tmp kökünü işaret edebilir
    folder = tmp_path_factory.mktemp("demo-visual")
    ds = datasets.load_dataset(cli.DEMO_DATASET)
    ds.build_db(db_path=folder / "wwi.db", sql_path=folder / "wwi.sql")
    schema = doc.load_schema(ds.schema_path)
    executor = LocalExecutor(
        "sqlite",
        folder / "wwi.db",
        allowlist=doc.allowlist(schema),
        pii_schema=schema,
        audit_path=folder / "audit.jsonl",
    )
    yield ds, executor
    mp.undo()


def test_nothing_remembered_serves_the_demo_world(served):
    write_datasets(served, [cli.DEMO_DATASET, DATASET], indexed=[cli.DEMO_DATASET])
    assert cli._served_dataset() == cli.DEMO_DATASET


def test_a_remembered_dataset_is_served_over_the_demo_world(served):
    write_datasets(served, [cli.DEMO_DATASET, DATASET], indexed=[cli.DEMO_DATASET, DATASET])
    remember(DATASET)
    assert cli._served_dataset() == DATASET


def test_a_remembered_dataset_that_no_longer_loads_falls_to_the_demo_world(served, capsys):
    write_datasets(served, [cli.DEMO_DATASET, DATASET], indexed=[cli.DEMO_DATASET])
    remember("kaybolmus")

    assert cli._served_dataset() == cli.DEMO_DATASET
    line = cli.STORED_LOST.format(name="kaybolmus", default=cli.DEMO_DATASET)
    assert line in capsys.readouterr().out


def test_without_the_demo_world_the_first_indexed_dataset_is_served(served):
    write_datasets(served, [DATASET], indexed=[DATASET])
    assert cli._served_dataset() == DATASET


def test_the_visual_questions_are_answered_on_the_demo_world(demo_world):
    """Akışın yazdığı sorular vitrin kümesinde karşılık bulur: cevap, devam, netleştirme."""
    ds, _ = demo_world
    client = fake.for_golden(
        ds.golden(), ds.fake_fallback_sql, "full", ds.ambiguous(), ds.followups()
    )
    turns = ds.followups()[0]["turns"]

    names, submitted, options = asked(client, VISUAL_GOLDEN)
    assert names[:3] == ["get_schema", "run_sql", "submit_sql"], "golden replay açılmadı"
    assert submitted == turns[0]["sql"] and options is None

    names, submitted, options = asked(client, VISUAL_FOLLOW_UP, earlier=[VISUAL_GOLDEN])
    assert submitted == turns[1]["sql"], "devam turu kendi SQL'ini göndermedi"

    names, submitted, options = asked(client, VISUAL_AMBIGUOUS)
    assert options == [reading["label"] for reading in ds.ambiguous()[0]["readings"]]
    assert submitted is None, "netleştirme sorulacağı yerde cevap düşmüş"


def test_every_visual_sql_passes_the_policy_and_measures_something(demo_world):
    """Vitrin kümesinin yeni SQL'i koruyucudan geçer, kurulu dünyada çalışır ve boş dönmez."""
    ds, executor = demo_world
    tables = doc.allowlist(doc.load_schema(ds.schema_path))
    readings = ds.ambiguous()[0]["readings"]
    sqls = [reading["sql"] for reading in readings]
    sqls += [turn["sql"] for chain in ds.followups() for turn in chain["turns"]]
    assert sqls

    answers = []
    for sql in sqls:
        verdict = policy.check(sql, tables)
        assert verdict.ok, f"{verdict.reason}: {sql}"
        result = executor.execute(sql, COMPARE, "visual")
        assert result.error is None, f"{result.error.message}: {sql}"
        assert result.rows, f"boş döndü: {sql}"
        answers.append(str(result.rows))
    # Şıklar aynı sayıya çıkıyorsa sorulan netleştirme boşuna sorulmuştur.
    assert len(set(answers[: len(readings)])) == len(readings)
