"""T323: önerilen hazır sorular onaysız doğar, işin aşaması yoklanır (PLAN R7-20).

Dünya ``tests/test_web_start_api.py`` ile aynı - kopya, import değil: kurulmuş sentetik ERP, gerçek
oturum, tmp uygulama dosyası. Sahte model kümenin altın sorularını roller arasında dağıtır, yani
önerilen her cümle aynı sahte ajanın cevaplayabildiği bir cümledir: iş bittiğinde satırda yürümeyen
tek bir soru yoktur.

Ölçülen üç şey: satırların **onaysız** yatması (hiçbiri ``GET /api/start``a çıkmaz), çöp bir model
yanıtının işi cümlesiyle düşürmesi, ve indeks işinin bittiği yerde öneri işinin başlaması.
"""

import json
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from nl2sql import config, datasets
from nl2sql.agent.llm import ChatResponse
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.schema_map import build, onboard
from nl2sql.schema_map.template import filled_example_workbook
from nl2sql.schema_map.template_import import read_template, validate
from nl2sql.start import suggest
from nl2sql.start.suggest import SuggestError, SuggestJobs
from nl2sql.web.app import create_app

DATASET = "synthetic_erp"
PAROLA = "Bilgin2026!erp"
NO_JOB = "Öneri işi bulunamadı."
NAME = "deneme_kume"


class ScriptedSuggester:
    """Bir öneri çağrısının modeli: ne döndüreceğini test söyler, bir daha çağrılırsa sayar."""

    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = 0

    def chat(self, messages, tools=None) -> ChatResponse:
        self.calls += 1
        return ChatResponse(content=self.content)


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    """Kurulmuş sentetik ERP bir kez: öneriler gerçek veride koşar, veriler testler arasında değişmez."""
    path = tmp_path_factory.mktemp("suggest") / "test.db"
    build.build_db(config.SEED, path, path.with_suffix(".sql"))
    return path


@pytest.fixture
def world(db, tmp_path):
    """Uygulamanın dünyası: öneri işleri tmp veritabanına bakan kendi kurucusuyla kurulur.

    ``app.state.suggest`` buradaki nesneyle değiştirilir - uygulamanın kendi kurucusu kümenin
    ``data/`` altındaki veritabanına bakar, test ise kurduğu tmp kopyada koşar.
    """
    session = open_session(
        dataset=DATASET,
        llm="fake",
        db_path=db,
        audit_path=tmp_path / "audit.jsonl",
        ask_log=tmp_path / "asks.jsonl",
    )
    users = UserStore(tmp_path / "bilgin.db")
    users.add_user("yonetici", PAROLA, "admin", "yonetim")
    users.add_user("satis1", PAROLA, "user", "satis")
    app = create_app(
        session, saved_path=tmp_path / "bilgin.db", static_dir=tmp_path / "static", users=users
    )
    jobs = SuggestJobs(
        app.state.ready,
        lambda name: open_session(
            dataset=name,
            llm="fake",
            db_path=db,
            audit_path=tmp_path / "audit.jsonl",
            ask_log=tmp_path / "asks.jsonl",
        ),
    )
    app.state.suggest = jobs
    return SimpleNamespace(app=app, session=session, users=users, jobs=jobs, store=app.state.ready)


def as_user(app, username) -> TestClient:
    """Aynı uygulamanın ayrı çerez kavanozu olan ikinci tarayıcısı, girişi yapılmış hâli."""
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": username, "password": PAROLA})
    assert response.status_code == 200, f"{username} giriş yapamadı: {response.status_code}"
    return client


def wait_for_job(jobs: SuggestJobs, job_id: str, timeout: float = 120.0) -> dict:
    """Aşama bir daha değişmeyecek an: iş bitti ya da düştü."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = jobs.status(job_id)
        if status["phase"] in ("done", "failed"):
            return status
        time.sleep(0.02)
    raise AssertionError(f"iş bitmedi: {jobs.status(job_id)}")


def run_fake_job(world) -> dict:
    """Sahte modelin tam bir öneri koşumu: bitmiş işin kaydı, satırlar depoda kalmış."""
    return wait_for_job(world.jobs, world.jobs.start(DATASET, "yonetici")["job_id"])


def suggest_job(store, content: str, db, tmp_path) -> dict:
    """Verilen metni döndüren modelin öneri işi: işin aşaması ve cümlesi ölçülsün diye."""
    jobs = SuggestJobs(
        store,
        lambda name: open_session(
            dataset=name,
            llm="openai",
            db_path=db,
            audit_path=tmp_path / "audit.jsonl",
            ask_log=tmp_path / "asks.jsonl",
            client_factory=lambda mode: ScriptedSuggester(content),
        ),
    )
    return wait_for_job(jobs, jobs.start(DATASET, "yonetici")["job_id"])


# --------------------------------------------------------------------- önerinin kendisi


def test_the_model_writes_two_to_four_questions_per_role():
    """Modelin sözü sözlüktür, sayısı değil: üst sınır koddan kırpılır, altındakalınan rol düşer."""
    roles = list(config.BUSINESS_ROLES)
    many = {role: [f"{n}. soru?" for n in range(9)] for role in roles}
    many[roles[-1]] = ["Tek soru?"]
    model = ScriptedSuggester(json.dumps(many, ensure_ascii=False))

    texts = suggest.suggest_texts({"tables": []}, [], model)

    assert model.calls == 1
    assert roles[-1] not in texts
    assert all(len(texts[role]) == config.SUGGEST_PER_ROLE[1] for role in roles[:-1])


def test_a_reply_that_is_not_json_is_refused_with_a_sentence():
    with pytest.raises(SuggestError) as refused:
        suggest.suggest_texts({"tables": []}, [], ScriptedSuggester("Sorular: ciro, stok, fatura"))

    assert refused.value.args[0] == suggest.NOT_JSON


# ------------------------------------------------------------------------------ işin koşumu


def test_a_fake_run_stores_two_unapproved_rows_per_role(world):
    job = run_fake_job(world)

    assert job["phase"] == "done"
    assert job["message"] is None
    assert job["dataset"] == DATASET
    assert job["asked"] == job["stored"]
    assert job["stored"] >= 2 * len(config.BUSINESS_ROLES)

    rows = world.store.list_all(DATASET, pending=True)
    assert len(rows) == job["stored"]
    assert all(row["approved"] is False and row["sql"] for row in rows)
    for role in config.BUSINESS_ROLES:
        assert len([row for row in rows if row["business_role"] == role]) >= 2


def test_no_suggestion_ever_shows_on_the_start_screen(world):
    run_fake_job(world)
    satis = as_user(world.app, "satis1")

    assert satis.get("/api/start").json()["cards"] == []
    assert world.store.list_all(DATASET, pending=False) == []

    # Onaylanan tek satır ekrana çıkar: önerinin kendisi değil, yöneticinin onayı kart olur.
    mine = next(r for r in world.store.list_all(DATASET, pending=True) if r["business_role"] == "satis")
    world.store.update(mine["id"], approved=True)

    assert [c["title"] for c in satis.get("/api/start").json()["cards"]] == [mine["title"]]


def test_a_junk_model_answer_fails_the_job_with_its_sentence(world, tmp_path):
    job = suggest_job(world.store, "JSON nedir bilmiyorum.", world.session.db_path, tmp_path)

    assert job["phase"] == "failed"
    assert job["message"] == suggest.NOT_JSON
    assert job["stored"] == 0


# ----------------------------------------------------------------------------------- yollar


def test_the_admin_starts_the_job_and_polls_its_phase(world):
    admin = as_user(world.app, "yonetici")

    started = admin.post("/api/ready-questions/suggest", json={"dataset": DATASET})

    assert started.status_code == 200
    job = started.json()
    assert job["job_id"] and job["dataset"] == DATASET
    assert job["phase"] in ("asking", "done", "failed")

    final = wait_for_job(world.jobs, job["job_id"])
    assert admin.get(f"/api/ready-questions/suggest/{job['job_id']}").json() == final
    assert final["phase"] == "done"


def test_a_job_that_never_ran_has_no_phase(world):
    admin = as_user(world.app, "yonetici")

    response = admin.get("/api/ready-questions/suggest/" + "0" * 32)

    assert response.status_code == 404
    assert response.json() == {"detail": NO_JOB}


# --------------------------------------------------------------------- onboarding bağılantısı


@pytest.fixture
def roots(tmp_path, monkeypatch):
    """Küme klasörleri ve ``outputs``un ROOT'u tmp'de: repo ile ``data/`` hiç anılmaz."""
    (tmp_path / "datasets").mkdir()
    (tmp_path / "real_datasets").mkdir()
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(tmp_path / "datasets"))
    monkeypatch.setenv("NL2SQL_REAL_DATASETS_DIR", str(tmp_path / "real_datasets"))
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setattr(config, "MAP_PREVIEWS_DIR", tmp_path / "map_previews")
    monkeypatch.setattr(config, "MAP_CHANGES_LOG", tmp_path / "logs" / "map_changes.jsonl")
    return tmp_path


def apply_example(tmp_path, name: str = NAME) -> dict:
    """Yükleme raporundan küme klasörüne: indeks işinin önündeki iki adım (R6-16)."""
    path = tmp_path / f"{name}.xlsx"
    path.write_bytes(filled_example_workbook(name))
    read = read_template(str(path))
    errors, _warnings, _db_check = validate(read)
    assert errors == []
    preview = {key: read[key] for key in ("dataset", "counts", "schema", "rules")}
    preview_id = onboard.save_preview(preview, "eren", "sablon.xlsx")
    onboard.apply_preview(onboard.load_preview(preview_id), "eren")
    return {"preview_id": preview_id, "name": name}


def wait_for_index(jobs: onboard.IndexJobs, preview_id: str, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = jobs.status(preview_id)
        if status["phase"] in ("done", "failed"):
            return status
        time.sleep(0.02)
    raise AssertionError(f"iş bitmedi: {jobs.status(preview_id)}")


def test_the_finished_index_hands_the_new_dataset_to_the_suggester(tmp_path, roots):
    applied = apply_example(tmp_path)
    jobs = onboard.IndexJobs()
    started = []

    jobs.start(applied["preview_id"], applied["name"], "fake", suggest=started.append)

    assert wait_for_index(jobs, applied["preview_id"])["phase"] == "done"
    assert started == [applied["name"]]
    assert (datasets.load_dataset(applied["name"]).index_dir / "meta.json").is_file()


def test_an_index_that_never_finished_never_asks_for_suggestions(tmp_path, roots):
    applied = apply_example(tmp_path)
    jobs = onboard.IndexJobs()
    started = []

    jobs.start(applied["preview_id"], applied["name"], "bozuk", suggest=started.append)

    assert wait_for_index(jobs, applied["preview_id"])["phase"] == "failed"
    assert started == []
