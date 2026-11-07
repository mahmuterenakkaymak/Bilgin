# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T455: M29 entegrasyonu — bir kurulumun yazıları gerçekten ``BILGIN_HOME``un altında doğuyor (PLAN R8-20, R8-23).

Elde elle kurulmuş tek sahte yok: sunucu ``python -m bilgin serve --llm fake``ın kendi süreci,
dünya wwi kümesinin kendi builder'ının kurduğu SQLite, indeks kurulum betiğinin ``index`` adımının
yaptığı kopyadır (R8-23), giriş kapının kendi bootstrap yöneticisi, soru kümenin kendi altın
satırlarından biri. İddiaların hepsi diskte okunur: ``/api/health`` 30 sn içinde cevap veriyor,
giriş ile soru ``HOME/data/bilgin.db``yi ve ``HOME/logs/asks.jsonl``i dolduruyor, deponun ``data``
ve ``logs`` klasörlerinde tek yeni dosya doğmuyor (var olan bir dosyaya da yazılmıyor), ``paths``
aynı ortamla o iki dosyanın adını söylüyor ve ``service-xml`` aynı Python'u, aynı portu ve aynı
HOME'u yazıyor.

Sıra dosya sırasıdır: soru bir kez sorulur (``asked``), deponun dokunulmadığını ölçen test en sonda
durur ki ``paths`` ve ``service-xml`` alt süreçleri de ona takılsın.
"""

import http.cookiejar
import json
import os
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from bilgin import config, datasets
from bilgin.auth.bootstrap import DEV_USERNAME
from bilgin.cli import main as cli
from bilgin.index.store import META_FILE

DATASET = "wwi"
# Sahtenin yedek sorgusu Q01'inki olduğu için soru ondan sonra bir satır olmalı: yalnız
# sonraki bir satır "gerçekten bu soru yürüdü" der.
GOLDEN_ID = "Q03"
HEALTH_TIMEOUT_S = 30.0  # R8-23'ün 60 sn'lik sağlık yoklaması değil, testin açılış sınırı
POLL_S = 0.25
HTTP_TIMEOUT_S = 60.0  # soru ajanı gerçekten koşuyor
# Taze bir kurulumun ortamı ölçülüyor: depodaki ``.env``in taşıyabileceği yol ve bağlantı
# değişkenleri çocuğa hiç gitmez, yazıların tek kökü BILGIN_HOME kalır.
_INHERIT_SKIP = ("BILGIN_APP_DB", "BILGIN_DATASETS_DIR", "BILGIN_REAL_DATASETS_DIR")


def _passphrase() -> str:
    """Girişin parolası: bir kez üretilir, hiçbir satıra, günlüğe ya da hataya düşmez."""
    return secrets.token_urlsafe(16)


PASSWORD = _passphrase()


# ------------------------------------------------------------------ dünyanın kurgulanması


def _free_port() -> int:
    """Boş bir port: ayıran soket hemen bırakılır, sunucu onu yeniden bağlar."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _env(home: Path) -> dict:
    """Sunucunun ve CLI alt süreçlerinin ortak ortamı: ikisi de aynı HOME'u okur, aynı yedeğe koşar."""
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in _INHERIT_SKIP and not key.startswith("BILGIN_MSSQL_CONN")
    }
    env.update(
        {
            "BILGIN_HOME": str(home),
            "BILGIN_BACKEND": "sqlite",
            "PYTHONIOENCODING": "utf-8",
            config.DEV_ADMIN_ENV: PASSWORD,
        }
    )
    return env


def _ensure_db(scratch: Path) -> None:
    """Kümenin veritabanı depoda hazır durduğu yerde durur; yoksa kümenin kendi builder'ı kurar.

    T-SQL betiği tmp'ye yazılır: testin ölçtüğü şey deponun ``data``sının dokunulmadığı, kurulumun
    kendi çıktısının ise orada yeni bir ad olmaması.
    """
    ds = datasets.load_dataset(DATASET)
    if not ds.db_path.is_file():
        ds.build_db(sql_path=scratch / "build_wwi.sql")


def _install_index(home: Path) -> None:
    """Kurulum betiğinin ``index`` adımı (R8-23): depoda bir kez kurulmuş indeks HOME'a taşınır."""
    repo_index = config.ROOT / "index" / DATASET
    if not (repo_index / META_FILE).is_file():
        assert cli.build_index("fake", dataset=DATASET) == 0
    shutil.copytree(repo_index, home / "index" / DATASET)


def _fingerprints(*folders: Path) -> dict[str, tuple[int, int]]:
    """Klasörlerin altındaki her dosyanın boyu ve değişim zamanı.

    Yalnız ad listesi yetmez: ``logs/asks.jsonl`` depoda zaten duruyor, yani HOME yok sayılıp
    oraya yazılırsa yeni bir ad doğmaz - fark edilen tek şey boy ve zaman damgasıdır.
    """
    found = {}
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in folder.rglob("*"):
            if path.is_file():
                stamp = path.stat()
                found[str(path.relative_to(folder.parent))] = (stamp.st_size, stamp.st_mtime_ns)
    return found


class World:
    """Koşan sunucu: tek süreç, tek çerez kavanozu, tek HOME; testler aynı dünyayı paylaşır."""

    def __init__(self, process: subprocess.Popen, port: int, home: Path, log: Path, before: dict):
        self.process = process
        self.port = port
        self.home = home
        self.log = log
        self.before = before
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )
        self._ready: tuple[float, int] | None = None

    def url(self, path: str) -> str:
        return f"http://127.0.0.1:{self.port}{path}"

    def ready(self) -> tuple[float, int]:
        """İlk HTTP cevabına kadar bekler, ölçtüğü süreyi saklar: 30 sn sınırı burada durur.

        Cevabın kendisi 401 olabilir - kapı oturum ister - ama bir durum kodu düşmüşse port
        dinleniyor demektir; henüz dinmeyen port ``URLError`` verir ve bekletilir.
        """
        if self._ready is None:
            self._ready = self._wait()
        return self._ready

    def _wait(self) -> tuple[float, int]:
        started = time.monotonic()
        while True:
            try:
                with urllib.request.urlopen(self.url("/api/health"), timeout=2.0) as response:
                    return time.monotonic() - started, response.status
            except urllib.error.HTTPError as exc:
                return time.monotonic() - started, exc.code
            except urllib.error.URLError as exc:
                if self.process.poll() is not None:
                    raise AssertionError(
                        self._failure(f"süreç {self.process.returncode} ile kapandı: {exc.reason}")
                    ) from exc
                if time.monotonic() - started >= HEALTH_TIMEOUT_S:
                    raise AssertionError(
                        self._failure(f"{HEALTH_TIMEOUT_S:.0f} sn içinde cevap yok: {exc.reason}")
                    ) from exc
                time.sleep(POLL_S)

    def _failure(self, why: str) -> str:
        """Hazır olamayışın sebebi, sunucunun kendi satırlarıyla: açılış hatası oradadır."""
        tail = self.log.read_text(encoding="utf-8", errors="replace")[-2000:] if self.log.is_file() else ""
        return f"sunucu hazır olmadı: {why}\n--- serve çıktısı ---\n{tail}"

    def login(self) -> dict:
        """Kapının bootstrap yöneticisiyle bir kez girer: çerez kavanozda kalır."""
        self.ready()
        status, body = self.post("/api/auth/login", {"username": DEV_USERNAME, "password": PASSWORD})
        assert status == 200, body
        return body

    def get(self, path: str) -> tuple[int, dict]:
        return self._send(urllib.request.Request(self.url(path)))

    def post(self, path: str, body: dict) -> tuple[int, dict]:
        request = urllib.request.Request(
            self.url(path),
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        return self._send(request)

    def _send(self, request) -> tuple[int, dict]:
        """Tek HTTP kapısı: reddin gövdesi de durum koduyla birlikte döner, fırlatılmaz."""
        try:
            with self.opener.open(request, timeout=HTTP_TIMEOUT_S) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8", "replace") or "{}")


@pytest.fixture(scope="module")
def world(tmp_path_factory):
    """tmp'de kurulmuş bir HOME: db depodan, indeks kurulumun kopyasıyla orada, sunucu gerçek ``serve``."""
    root = tmp_path_factory.mktemp("m29")
    home = root / "home"
    _ensure_db(root)
    _install_index(home)
    before = _fingerprints(config.ROOT / "data", config.ROOT / "logs")
    port = _free_port()
    log = root / "serve.log"
    with log.open("w", encoding="utf-8") as handle:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "bilgin",
                "serve",
                "--llm",
                "fake",
                "--dataset",
                DATASET,
                "--port",
                str(port),
            ],
            cwd=config.ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            env=_env(home),
        )
        try:
            yield World(process=process, port=port, home=home, log=log, before=before)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def golden_line() -> dict:
    """Ölçülen altın satır: soru da beklenen SQL de kümenin kendi dosyasından."""
    return next(item for item in datasets.load_dataset(DATASET).golden() if item["id"] == GOLDEN_ID)


@pytest.fixture(scope="module")
def asked(world: World) -> dict:
    """Giriş ve tek soru: cevabın yazdıkları sonra diskten okunur, dünya bir kez koşulur."""
    assert world.login()["username"] == DEV_USERNAME
    status, payload = world.post("/api/ask", {"question": golden_line()["question"]})
    assert status == 200, payload
    assert payload["status"] == "answered", payload.get("error")
    return payload


def _cli(args: list[str], home: Path) -> str:
    """Aynı ortamla koşan bir CLI alt süreci: çıktısı boş değilse test onu kendi görsün."""
    finished = subprocess.run(
        [sys.executable, "-m", "bilgin", *args],
        cwd=config.ROOT,
        capture_output=True,
        encoding="utf-8",
        env=_env(home),
    )
    assert finished.returncode == 0, finished.stdout + finished.stderr
    return finished.stdout


# ------------------------------------------------------------------ sunucu ayakta mı


def test_health_answers_within_thirty_seconds(world: World):
    """Açılışın sınırı 30 sn; cevabın 401 olması kapının oturum istediğidir, sunucunun öldüğü değil."""
    seconds, status = world.ready()
    assert seconds <= HEALTH_TIMEOUT_S
    assert status == 401

    world.login()
    status, body = world.get("/api/health")
    assert status == 200, body
    assert body["status"] == "ok"
    assert body["dataset"]["name"] == DATASET
    assert body["llm"]["kind"] == "fake"
    # İndeks HOME'un altında doğdu: tazelik, sunucunun kopyayı orada bulduğunun okunur cevabıdır.
    assert body["index"]["fresh"] is True, body["index"]["reason"]


# ------------------------------------------------------------------ yazıların yeri


def test_the_login_and_the_ask_wrote_inside_the_home(asked: dict, world: World):
    assert asked["sql"] == golden_line()["sql"]

    app_db = world.home / "data" / "bilgin.db"
    assert app_db.is_file(), "girişin oturumu HOME'un uygulama veritabanına yazılmadı"
    with sqlite3.connect(app_db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] >= 1

    lines = [
        json.loads(line)
        for line in (world.home / "logs" / "asks.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert [line["question"] for line in lines] == [golden_line()["question"]]
    assert lines[0]["status"] == "answered"
    assert lines[0]["dataset"] == DATASET
    assert lines[0]["username"] == DEV_USERNAME
    assert (world.home / "logs" / "audit.jsonl").is_file()


# ------------------------------------------------------------------ aynı dünyanın iki okunuşu


def test_paths_names_the_files_the_run_wrote(asked: dict, world: World):
    report = json.loads(_cli(["paths", "--json"], world.home))
    assert report["home"] == str(world.home)
    assert report["app_db"] == str(world.home / "data" / "bilgin.db")
    assert report["ask_log"] == str(world.home / "logs" / "asks.jsonl")
    assert report["logs"] == str(world.home / "logs")
    assert report["index"] == str(world.home / "index")
    for key in ("app_db", "ask_log", "audit_log"):
        assert Path(report[key]).is_file(), f"paths {key}i {report[key]} - koşulmuş bir dosya değil"


def test_service_xml_names_the_same_python_port_and_home(world: World, tmp_path: Path):
    out = tmp_path / "bilgin.xml"
    _cli(
        [
            "service-xml",
            "--port",
            str(world.port),
            "--dataset",
            DATASET,
            "--home",
            str(world.home),
            "--out",
            str(out),
        ],
        world.home,
    )

    service = ET.parse(out).getroot()
    assert service.findtext("executable") == sys.executable
    arguments = service.findtext("arguments")
    assert f"--port {world.port}" in arguments
    assert f"--dataset {DATASET}" in arguments
    assert service.findtext("workingdirectory") == str(config.ROOT)
    env = {item.get("key"): item.get("value") for item in service.findall("env")}
    assert env["BILGIN_HOME"] == str(world.home)
    assert env["BILGIN_BACKEND"] == "sqlite"
    assert service.findtext("logpath") == str(world.home / "logs")


# ------------------------------------------------------------------ deponun dokunulmadığı (en sonda)


def test_the_repository_data_and_logs_stay_untouched(asked: dict, world: World):
    """Sunucu HOME'u yok saysa ilk satırını depodaki ``logs/asks.jsonl``e eklerdi: boy ve zaman da ölçülür.

    En sondaki test bu: ``paths`` ve ``service-xml`` alt süreçleri de koşmuş haliyle bakılır.
    """
    assert _fingerprints(config.ROOT / "data", config.ROOT / "logs") == world.before
