"""``python -m nl2sql service-check`` (PLAN R8-23, Contracts ``service-check``).

Kurulum betiği bu yoklamayı *uyarı* olarak okur, o yüzden üç şey sabitlenir: kapalı bir uç nokta ya
da yazabilen bir giriş çıkış koduna hiç geçmez, ``--json``ın anahtarları sözleşmenin satırıdır
(betiği onları okur), ve bağlantı dizesinin sırrı hiçbir satıra düşmez. Model yoklaması ``llm.ping``in
yerini alan bir bağraçla, sunucu ``connect``inkiyle oynanır - ne bir SQL Server ne bir model gerekir.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from nl2sql import config
from nl2sql.cli import main as cli
from nl2sql.i18n import t

REPO = Path(config.__file__).resolve().parent.parent
MINI = REPO / "tests" / "fixtures" / "datasets" / "mini"

URL = "http://127.0.0.1:8080/v1"
MODEL = "strata"
DOWN = f"[Errno 8] {URL} bağlantı kurulamadı"
SECRET = "gizli-anahtar-123"
CONN_STR = f"DRIVER={{ODBC Driver 18 for SQL Server}};SERVER=sunucu;DATABASE=erp;UID=ro;PWD={SECRET};"

# Contracts "service-check": anahtarlar ve sıraları sözleşmenin satırıdır.
CONTRACT = {"model": ["ok", "message"], "connection": ["source", "ok", "lines"]}


class FakeConnection:
    """Guard'ın yoklama sorgularına yanıt veren sahte bağlantı (R7-24'ün ``connect`` yeri).

    ``powers`` ad parçalarıdır: sorgu onlardan birini içeriyorsa giriş o güce sahiptir, yani 1.
    """

    def __init__(self, powers: tuple[str, ...]) -> None:
        self._powers = powers
        self._sql = ""

    def execute(self, sql: str) -> "FakeConnection":
        self._sql = sql
        return self

    def fetchone(self) -> tuple[int]:
        return (1 if any(power in self._sql for power in self._powers) else 0,)

    def close(self) -> None:
        pass


def connector(*powers: str):
    """Verildiği güçleri 1 yanıtlayan bağdaç: ``connector("sysadmin")`` bir yönetici girişi."""

    def connect(conn_str: str) -> FakeConnection:
        return FakeConnection(powers)

    return connect


def failing_connect(conn_str: str):
    """Sürücünün yaptığı gibi bağlantı dizesini kendine döndüren başarısız bağdaç."""
    raise ConnectionError(f"[08001] Login failed. {conn_str}")


def up(profile):
    """Açık uç noktanın cevabı: sebep yok."""
    return None


@pytest.fixture
def world(tmp_path, monkeypatch):
    """İki küme: SQLite'ınki ``mini``, SQL Server'ınki ``erp``; ortamda canlı sunucu ya model yok."""
    shutil.copytree(MINI, tmp_path / "datasets" / "mini")
    shutil.copytree(MINI, tmp_path / "datasets" / "erp")
    _rewrite(tmp_path / "datasets" / "erp" / "dataset.json", "erp")
    monkeypatch.setenv("NL2SQL_DATASETS_DIR", str(tmp_path / "datasets"))
    monkeypatch.setenv("NL2SQL_APP_DB", str(tmp_path / "app.db"))
    monkeypatch.setenv("NL2SQL_LLM_BASE_URL", URL)
    monkeypatch.setenv("NL2SQL_LLM_MODEL", MODEL)
    for name in (
        "NL2SQL_MSSQL_CONN",
        "NL2SQL_BACKEND",
        "NL2SQL_MSSQL_CONN_MINI",
        "NL2SQL_MSSQL_CONN_ERP",
    ):
        monkeypatch.delenv(name, raising=False)
    return tmp_path


def _rewrite(path: Path, name: str) -> None:
    """Kopyalanan tanımın adı, bağlantısı ve çıktıları; küme klasörü kendi adını taşır."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["name"] = name
    raw["connection"] = "mssql"
    raw["outputs"] = {
        "db": f"data/{name}.db",
        "mssql_script": f"db/mssql/build_{name}.sql",
        "index_dir": f"index/{name}",
        "eval_out": f"eval_out/{name}",
    }
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")


def check(capsys, dataset: str = "mini", **kwargs) -> tuple[int, dict]:
    """``service-check --json``: (çıkış kodu, basılan sözlük)."""
    code = cli.service_check(dataset, json_out=True, **kwargs)
    return code, json.loads(capsys.readouterr().out)


def test_an_unreachable_endpoint_is_a_warning_not_a_failure(world, capsys):
    code, data = check(capsys, ping=lambda profile: DOWN)

    assert code == 0
    assert data["model"] == {"ok": False, "message": DOWN}
    assert cli.service_check("mini", ping=lambda profile: DOWN) == 0
    assert DOWN in capsys.readouterr().out


def test_the_model_probe_asks_the_endpoint_the_service_would_use(world, capsys):
    asked: list = []

    def probe(profile):
        asked.append(profile)
        return DOWN

    code, data = check(capsys, ping=probe)

    assert code == 0
    assert (asked[0].base_url, asked[0].model) == (URL, MODEL)
    assert data["model"] == {"ok": False, "message": DOWN}


def test_a_reachable_endpoint_says_which_model_answered(world, capsys):
    code, data = check(capsys, ping=up)

    assert code == 0
    assert data["model"] == {
        "ok": True,
        "message": t("cli.check.model_ok", "tr", model=MODEL, url=URL),
    }
    assert cli.service_check("mini", ping=up) == 0
    assert capsys.readouterr().out.startswith(f"{t('cli.check.model', 'tr')}: ✓ ")


def test_a_sqlite_dataset_has_no_connection_to_check(world, capsys):
    code, data = check(capsys, ping=up)

    assert code == 0
    assert data["connection"] == {
        "source": "none",
        "ok": None,
        "lines": [t("cli.check.sqlite", "tr")],
    }


def test_an_mssql_dataset_without_a_connection_points_at_the_admin_panel(world, capsys):
    code, data = check(capsys, "erp", ping=up)

    assert code == 0
    assert data["connection"] == {
        "source": "none",
        "ok": None,
        "lines": [t("cli.check.no_connection", "tr")],
    }


def test_a_sysadmin_login_is_refused_by_the_guard(world, capsys, monkeypatch):
    monkeypatch.setenv("NL2SQL_MSSQL_CONN_ERP", CONN_STR)
    code, data = check(capsys, "erp", ping=up, connect=connector("sysadmin"))

    assert code == 0
    assert data["connection"]["source"] == "env_dataset"
    assert data["connection"]["ok"] is False
    assert t("guard.power", "tr") in data["connection"]["lines"]


def test_a_readonly_login_passes_the_guard(world, capsys, monkeypatch):
    monkeypatch.setenv("NL2SQL_MSSQL_CONN_ERP", CONN_STR)
    code, data = check(capsys, "erp", ping=up, connect=connector())

    assert code == 0
    assert data["connection"]["source"] == "env_dataset"
    assert data["connection"]["ok"] is True
    assert data["connection"]["lines"]


def test_json_keys_are_exactly_the_contract(world, capsys, monkeypatch):
    monkeypatch.setenv("NL2SQL_MSSQL_CONN_ERP", CONN_STR)
    _, data = check(capsys, "erp", ping=up, connect=connector())

    assert list(data) == list(CONTRACT)
    for name, keys in CONTRACT.items():
        assert list(data[name]) == keys
    assert isinstance(data["model"]["ok"], bool)
    assert isinstance(data["model"]["message"], str)
    assert data["connection"]["ok"] in (True, False, None)
    assert all(isinstance(line, str) for line in data["connection"]["lines"])


@pytest.mark.parametrize("json_out", [True, False])
def test_the_connection_string_never_appears_in_either_output(world, capsys, monkeypatch, json_out):
    monkeypatch.setenv("NL2SQL_MSSQL_CONN_ERP", CONN_STR)

    code = cli.service_check("erp", json_out=json_out, ping=up, connect=failing_connect)
    printed = capsys.readouterr().out

    assert code == 0
    assert SECRET not in printed
    assert CONN_STR not in printed


def test_the_text_follows_lang(world, capsys):
    assert cli.service_check("mini", ping=up, lang="en") == 0
    printed = capsys.readouterr().out

    assert printed.startswith(f"{t('cli.check.model', 'en')}: ✓ ")
    assert t("cli.check.sqlite", "en") in printed
    assert not set(printed) & set("çğıöşüÇĞİÖŞÜ")
