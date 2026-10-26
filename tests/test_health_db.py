"""T339: sağlıkta veritabanı çipi, düşmüş veritabanında hızlı red, serve'in yoklama kurulumu (PLAN R7-25, R7-26).

Dünya ``tests/test_web_api.py`` ile aynı - kopya, import değil: gerçek mini küme, sahte model,
tmp yollar. Canlı SQL Server yoktur: noktanın cevabı dışarıdan alınan bir ``ping``den, hızlı red
de ``app.state``teki bekçiden okunur. Modelin gerçekten koşup koşmadığı sayan bir istemciyle
ölçülür - "cevap yok" ile "model hiç koşmadı" aynı cümle değildir.
"""

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from nl2sql import config
from nl2sql.app.ask import DB_DOWN_MESSAGE
from nl2sql.app.session import open_session
from nl2sql.auth.store import UserStore
from nl2sql.cli import main as cli
from nl2sql.engine import connections
from nl2sql.engine.connections import ConnectionStore
from nl2sql.engine.dbstatus import DOWN_MESSAGE, DbStatus
from nl2sql.engine.result import ExecError, Result
from nl2sql.web.app import CONNECTIONS_URL, create_app

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "datasets"
PAROLA = "Bilgin2026!erp"
BAGLANTI = "DRIVER={ODBC Driver 18 for SQL Server};SERVER=10.0.0.5;DATABASE=WWI;UID=bilgin_ro;"
# Sürücünün bağlanamama cümlesi: bekçinin "bu bir bağlantı hatası" dediği hâlin kendisi.
SURUCU_HATASI = "[08001] [Microsoft][ODBC Driver 18]TCP Provider: Bağlantı kurulamadı."
SORGU_HATASI = "Incorrect syntax near 'FROM'."


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.delenv("NL2SQL_MSSQL_CONN", raising=False)
    monkeypatch.delenv("NL2SQL_BACKEND", raising=False)
    monkeypatch.delenv("NL2SQL_MSSQL_CONN_MINI", raising=False)
    monkeypatch.setattr(config, "ROOT", tmp_path)
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(FIXTURE_ROOT))
    cli.build_database(dataset="mini")
    return tmp_path


def oturum_ac(project, client_factory=None):
    return open_session(
        dataset="mini",
        llm="fake",
        audit_path=project / "audit.jsonl",
        ask_log=project / "asks.jsonl",
        client_factory=client_factory,
    )


def kur(project, bekci=None, users=None, oturum=None):
    return TestClient(
        create_app(
            oturum or oturum_ac(project),
            saved_path=project / "bilgin.db",
            static_dir=project / "static",
            users=users,
            dbstatus=bekci,
        )
    )


def girisli(app, username: str) -> TestClient:
    """Aynı uygulamanın girişi yapılmış ayrı bir tarayıcısı."""
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"username": username, "password": PAROLA})
    assert response.status_code == 200
    return client


def birinci_soru(oturum) -> str:
    return next(item for item in oturum.dataset.golden() if item["id"] == "Q01")["question"]


def dusmus_bekci() -> DbStatus:
    """Gerçek bekçi, sahte pingi her yoklamada düşen bir bağlantı: çip kırmızıdır."""
    status = DbStatus(lambda _veri_kumesi: {"source": "stored", "conn_str": BAGLANTI},
                      ping=_dusen_ping)
    status.check_now("mini")
    return status


def _dusen_ping(conn_str: str, timeout=None) -> None:
    raise RuntimeError(SURUCU_HATASI)


class SayanIstemci:
    """Ajanın koştuğunu yakalayan istemci: bir kez bile çağrılsa test düşer."""

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        raise AssertionError("veritabanı düşmüşken model koştu")


class SahteBekci:
    """Bekçinin yolu: durumun kendisi ve kaçıncı kez bekletildiği."""

    def __init__(self, durum: str = "ok") -> None:
        self.durum = durum
        self.bekletme = 0

    def state(self, dataset: str) -> dict:
        return {"state": self.durum, "checked_at": None, "message": None, "message_admin": None}

    def kick(self) -> None:
        self.bekletme += 1


def yurutmeyi_dusur(monkeypatch, oturum, mesaj: str) -> None:
    """Cevabın yürüyüşü düşer, ajanın kendi ``run_sql``i sağ kalır (R7-25).

    Bekçiyi uyandıran şey cevabın ardındaki bağlantı hatasıdır; ajanın aracına kadar sıçrarsa
    ölçülen şey koşumun kendisi olur. Arayüz yürüyüşünün ölçütü bütçesidir - ``ask_payload``
    cevabı ``UI_MAX_ROWS`` ile koşar.
    """
    gercek = oturum.executor.execute

    def execute(sql, budget, source, **kwargs):
        if getattr(budget, "max_rows", None) != config.UI_MAX_ROWS:
            return gercek(sql, budget, source, **kwargs)
        return Result(error=ExecError(kind="sql", message=mesaj))

    monkeypatch.setattr(oturum.executor, "execute", execute)


# ------------------------------------------------------------------ /api/health db


def test_a_dataset_with_no_connection_is_none_for_everyone(project):
    """Sentetik küme SQLite'a bakıyor: sorulacak bir sunucu yok, çip de yokluğu söylüyor."""
    store = ConnectionStore(project / "app.db")
    bekci = DbStatus(lambda ad: connections.resolve(ad, store, ad))

    assert bekci.state("synthetic_erp")["state"] == "none"
    assert kur(project, bekci=bekci).get("/api/health").json()["db"] == {
        "state": "none", "checked_at": None, "message": None,
        "message_admin": None, "connections_url": CONNECTIONS_URL,
    }


def test_the_state_follows_the_injected_pinger():
    cevap = {"saglam": True}

    def ping(conn_str, timeout=None):
        if not cevap["saglam"]:
            raise RuntimeError(SURUCU_HATASI)

    bekci = DbStatus(lambda _veri_kumesi: {"source": "stored", "conn_str": BAGLANTI}, ping=ping)

    assert bekci.state("wwi_real")["state"] == "unknown", "ilk okuma yalnız sorar, beklemez"
    assert bekci.check_now("wwi_real")["state"] == "ok"

    cevap["saglam"] = False
    dusuk = bekci.check_now("wwi_real")
    assert dusuk["state"] == "down"
    assert dusuk["message"] == DOWN_MESSAGE


def test_the_admin_gets_the_driver_sentence_and_a_user_does_not(project):
    users = UserStore(project / "bilgin.db")
    users.add_user("yonetici", PAROLA, "admin")
    users.add_user("kullanici", PAROLA, "user")
    client = kur(project, bekci=dusmus_bekci(), users=users)

    yonetici = girisli(client.app, "yonetici").get("/api/health").json()["db"]
    kullanici = girisli(client.app, "kullanici").get("/api/health").json()["db"]

    assert yonetici["state"] == "down" and yonetici["message"] == DOWN_MESSAGE
    assert "08001" in yonetici["message_admin"], "nedeni düzeltecek olan yöneticidir"
    assert yonetici["connections_url"] == CONNECTIONS_URL
    assert kullanici["state"] == "down" and kullanici["message"] == DOWN_MESSAGE
    assert "message_admin" not in kullanici and "connections_url" not in kullanici


# ------------------------------------------------------------------ düşmüş veritabanında soru


def test_a_question_while_the_database_is_down_never_reaches_the_model(project):
    sayan = SayanIstemci()
    oturum = oturum_ac(project, client_factory=lambda mod: sayan)
    client = kur(project, bekci=dusmus_bekci(), oturum=oturum)

    body = client.post("/api/ask", json={"question": birinci_soru(oturum)}).json()

    assert body["status"] == "failed"
    assert body["error"] == {"kind": "db_down", "message": DB_DOWN_MESSAGE}
    assert body["answer_text"] == DB_DOWN_MESSAGE
    assert body["sql"] == "" and body["rows"] == [] and body["chart"] is None
    assert sayan.calls == 0
    satir = json.loads((project / "asks.jsonl").read_text(encoding="utf-8").strip())
    assert satir["source"] == "web" and satir["status"] == "failed" and satir["error"] == "db_down"


def test_a_connection_error_kicks_the_checker_and_a_query_error_does_not(project, monkeypatch):
    bekci = SahteBekci()
    oturum = oturum_ac(project)
    client = kur(project, bekci=bekci, oturum=oturum)
    soru = birinci_soru(oturum)

    yurutmeyi_dusur(monkeypatch, oturum, SURUCU_HATASI)
    assert client.post("/api/ask", json={"question": soru}).json()["error"]["kind"] == "exec:sql"
    assert bekci.bekletme == 1, "nokta kendi turunu beklemez"

    yurutmeyi_dusur(monkeypatch, oturum, SORGU_HATASI)
    client.post("/api/ask", json={"question": soru})
    assert bekci.bekletme == 1, "bozuk bir sorgu sunucunun ulaşılabilir olduğunu söyler"


# ------------------------------------------------------------------ serve'in yoklama dosyası


def refuse(app, host, port):
    raise AssertionError("reddedilen bir sunucu dinlemeye başlamaz")


def test_serve_refuses_a_probe_file_without_the_fake_model(project, capsys, monkeypatch):
    capsys.readouterr()
    monkeypatch.setattr(cli, "run_server", refuse)

    assert cli.serve(llm_kind="openai", dataset="mini", db_probe_file=project / "probe.json") == 2
    assert "--db-probe-file yalnız --llm fake ile kullanılır" in capsys.readouterr().out
