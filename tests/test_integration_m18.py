"""T236: M18 entegrasyonu — kapının arkasında elle kurulmuş tek sahte yok.

Kullanıcı CLI'nin kendi ``user add``i (parolayı ``getpass``ten iki kez sorar), dosya tmp'deki
``NL2SQL_APP_DB``, kapı gerçek ``open_session``ın üstündeki gerçek ``create_app``, dünya mini
kümesinin kendi builder'ının kurduğu SQLite ve ``cli.build_index``in kurduğu sahte indeks. Uçtan
uca tek akış: giriş → kimim → cevaplı soru → kayıtlar → çıkış → kapının tekrar kapanması → beş
hatalı denemenin kilidi → dosyanın hâli. Son iki iddia Run 6'nın kendi sözleşmesi: ne soru
günlüğü ne uygulamanın kendi dosyası parolayı ya da ham oturum anahtarını görür; dosyada karması
ve anahtarın sha256 izi durur.
"""

import contextlib
import getpass
import hashlib
import io
import time
from pathlib import Path
from typing import NamedTuple

import pytest
from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from nl2sql import config, datasets
from nl2sql.app import asklog
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.web.app import create_app

DATASET = "mini"
# İndeksin gerçekten kullanıldığı mod: sahte indeks olmadan rag bir koşum değil, hatadır.
MODE = "rag"
# PASSWORD_MIN_LEN'den uzun; dosyada aranan şey tam olarak bu baytların geçmemesi.
PASSWORD = "Bilgin-2026-m18"
WRONG = "Bilgin-2026-yanlis"
FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "datasets"


class App(NamedTuple):
    """Akışın koştuğu dünya: oturum, kapı, depo, saat ve uygulamanın kendi dosyası."""

    session: object
    api: object
    client: TestClient
    store: UserStore
    clock: "Clock"
    app_db: Path
    ask_log: Path


class Clock:
    """Testin ilerlettiği saat: kilitlenme penceresi gerçek 15 dakikayı beklemez."""

    def __init__(self) -> None:
        self.now = time.time()

    def __call__(self) -> float:
        return self.now

    def advance(self, minutes: float) -> None:
        self.now += minutes * 60


def quiet(func, *args, **kwargs):
    """CLI kendi satırlarını basar; testin okuyacağı şey stdout değil dosyaların hâlidir."""
    buf = io.TextIOWrapper(io.BytesIO(), encoding="utf-8")
    with contextlib.redirect_stdout(buf):
        code = func(*args, **kwargs)
    buf.flush()
    return code, buf.buffer.getvalue().decode("utf-8")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """tmp'de kurulu mini dünyası: db kümenin kendi builder'ından, indeks gerçek ``build_index``ten.

    ``config.ROOT`` tmp'ye çevrilir ki kümenin db ve indeks çıktıları da oraya yazılsın;
    ``NL2SQL_APP_DB`` uygulamanın kendi dosyasını, ``NL2SQL_DATASETS_DIR`` fixture'ın kümesini
    gösterir — depodaki ``data/`` ve ``index/`` klasörlerine tek bayt yazılmaz.
    """
    folder = tmp_path_factory.mktemp("m18")
    mp = MonkeyPatch()
    mp.setattr(config, "ROOT", folder)
    mp.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    mp.setenv("NL2SQL_APP_DB", str(folder / "bilgin.db"))
    ds = datasets.load_dataset(DATASET)
    ds.db_path.parent.mkdir(parents=True, exist_ok=True)
    ds.build_db(db_path=ds.db_path, sql_path=folder / "mini.sql")
    code, out = quiet(cli.build_index, "fake", dataset=DATASET)
    assert code == 0, f"sahte indeks kurulamadı: {out}"
    yield folder, ds
    mp.undo()


@pytest.fixture(scope="module")
def app(world):
    """CLI'nin yazdığı yöneticinin üstünde duran gerçek kapı.

    Depo aynı dosyaya enjekte edilmiş bir saatle bakar: kilitlenme, kilidin bitmesi ve oturum
    süresi gerçek zamanı beklemeden sınanır.
    """
    folder, _ = world
    app_db = folder / "bilgin.db"

    mp = MonkeyPatch()
    mp.setattr(getpass, "getpass", lambda prompt="": PASSWORD)
    try:
        code, out = quiet(cli.main, ["user", "add", "admin", "--role", "admin"])
    finally:
        mp.undo()
    assert code == 0 and "✓ admin eklendi (rol admin)." in out, out

    clock = Clock()
    store = UserStore(app_db, clock=clock)
    session = open_session(
        dataset=DATASET,
        llm="fake",
        audit_path=folder / "audit.jsonl",
        ask_log=folder / "asks.jsonl",
    )
    api = create_app(session, saved_path=app_db, static_dir=config.STATIC_DIR, users=store)
    return App(
        session=session,
        api=api,
        client=TestClient(api),
        store=store,
        clock=clock,
        app_db=app_db,
        ask_log=session.ask_log,
    )


def login(client, username: str = "admin", password: str = PASSWORD):
    return client.post("/api/auth/login", json={"username": username, "password": password})


def ask(app: App, question: str) -> dict:
    body = app.client.post("/api/ask", json={"question": question, "mode": MODE}).json()
    assert body.get("error") is None, body.get("error")
    return body


# ------------------------------------------------------------------ CLI -> dosya -> kapı


def test_the_admin_the_cli_wrote_is_the_admin_the_file_holds(app: App):
    users = app.store.list_users()
    assert [(u["username"], u["role"], u["active"]) for u in users] == [("admin", "admin", True)]
    # Depo yeni kurulduğunda da okunuyor: komutun yazdığı bellek değil, dosyanın kendisi.
    assert UserStore(app.app_db).get_user("admin")["role"] == "admin"
    assert app.store.get_user("admin")["last_login_at"] is None, "henüz kimse giriş yapmadı"


def test_login_and_me_name_the_same_admin_and_nothing_else(app: App):
    signed_in = login(app.client)

    assert signed_in.status_code == 200
    assert signed_in.json() == {"username": "admin", "role": "admin"}
    assert app.client.cookies.get(config.SESSION_COOKIE), "anahtar yalnız çerezle gider"

    me = app.client.get("/api/auth/me")
    assert me.status_code == 200 and me.json() == signed_in.json()


# ------------------------------------------------------------------ soru, kayıt, çıkış


def test_an_answered_question_lands_in_the_log_without_the_password(app: App):
    line = next(item for item in app.session.dataset.golden() if item["id"] == "Q01")

    body = ask(app, line["question"])

    assert body["status"] == "answered" and body["mode"] == MODE
    assert body["sql"] == line["sql"] and body["answer_text"]
    assert body["dataset"] == DATASET and body["model"] == "fake"

    logged = asklog.find_ask(body["audit_id"], app.ask_log)
    assert logged["status"] == "answered" and logged["question"] == line["question"]
    assert logged["source"] == "web" and logged["dataset"] == DATASET
    assert PASSWORD not in app.ask_log.read_text(encoding="utf-8"), "günlük parolayı göremez"


def test_a_saved_question_comes_back_from_the_sidebar(app: App):
    question = "Her ürünün adı ile birlikte toplam kaç adet sipariş edildi?"

    added = app.client.post("/api/saved", json={"question": question, "mode": MODE, "sql": "SELECT 1"})

    assert added.status_code == 200
    assert added.json()["saved"]["question"] == question

    listed = app.client.get("/api/saved").json()["saved"]
    assert [item["question"] for item in listed] == [question]
    assert listed[0]["dataset"] == DATASET and listed[0]["sql"] == "SELECT 1"


def test_logout_closes_the_session_and_shuts_the_door(app: App):
    token = app.client.cookies.get(config.SESSION_COOKIE)
    assert app.client.get("/api/history").status_code == 200

    assert app.client.post("/api/auth/logout").status_code == 200

    assert app.client.get("/api/auth/me").status_code == 401
    assert app.client.get("/api/history").status_code == 401
    assert app.store.session_user(token) is None, "oturum dosyada da kapandı"


# ------------------------------------------------------------------ kilitlenme


def test_five_wrong_logins_lock_the_account_until_the_window_passes(app: App):
    client = TestClient(app.api)  # taze çerez kavanozu: kilit oturumla değil, adla ilgili

    for _ in range(config.LOGIN_MAX_FAILURES):
        assert login(client, password=WRONG).status_code == 401

    locked = login(client, password=WRONG)
    assert locked.status_code == 429 and "dakika" in locked.json()["detail"]
    assert login(client).status_code == 429, "kilit doğru parolayı da geri çevirir"

    app.clock.advance(config.LOCKOUT_MIN + 1)

    assert login(client).status_code == 200, "pencere geçince hesap kendiliğinden açılır"


# ------------------------------------------------------------------ dosyanın hâli


def test_the_app_db_holds_a_hash_and_a_digest_never_the_secret(app: App):
    signed_in = login(TestClient(app.api))
    assert signed_in.status_code == 200
    token = signed_in.cookies.get(config.SESSION_COOKIE)

    raw = app.app_db.read_bytes()

    assert b"scrypt$" in raw, "parola scrypt karması olarak durur"
    assert PASSWORD.encode("utf-8") not in raw
    assert token.encode("utf-8") not in raw, "ham oturum anahtarı diske yazılmaz"
    assert hashlib.sha256(token.encode("utf-8")).hexdigest().encode("utf-8") in raw
