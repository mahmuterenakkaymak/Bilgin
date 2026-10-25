"""``serve`` dumanı: API'yi gerçekten ayağa kaldırır, adımların üstünden HTTP ile geçer.

Komut satırı araçları zaten test ediliyor; burada ölçülen şey sunucunun kendisi — ``python -m
nl2sql serve`` bir alt süreç olarak açılır, portu dinlemeye başlayana kadar beklenir, sonra
çerezsiz ``POST /api/ask`` (401) → ``POST /api/auth/login`` → ``/api/health`` → ``POST /api/ask``
→ ``GET /api/export/<id>.csv`` sırası koşar. Soru kümenin ilk altın sorusudur: sahte model onu
birebir bildiği için cevap ``answered`` olmak zorundadır, yani dumanın geçti "bir şey döndü" değil
"uçtan uca cevap döndü" demektir.

R6-7'den beri ``serve`` oturumsuz hiçbir şey sunmadığı için dumanın da oturum açması gerekir:
sunucu boş bir uygulama veritabanı üstünde açılır -- geçici bir ``NL2SQL_APP_DB`` ve koşu sırasında
üretilen ``NL2SQL_DEV_ADMIN_PASSWORD`` --, giriş ondan sonra mümkün olur. Parolanın değeri hiçbir
satıra düşmez, geçici dosya iş bitince silinir; böylece duman ne gerçek ``data/bilgin.db``ye ne
gerçek bir kullanıcıya dokunur.

Sunucu her durumda kapatılır; biriktirdiği çıktı yalnız adım tökezlerse ekrana dökülür, böylece
eksik veritabanı gibi bir açılış hatası kendi cümlesiyle görünür. ``--ui`` ekranı da dener: ``/``
yanıtı derlenmiş arayüzün kendisi olmalı -- yedek sayfa değil -- ve sayfanın yüklediği ilk
``/assets`` dosyası inebilmeli, çünkü ikisi olmadan tarayıcıda boş bir perde vardır.

``--roles`` Run 6'nın rol kapılarını aynı sunucuda ve aynı yöneticinin üstünde koşar (PLAN R6-22):
yönetici ``/api/users``tan bir hesap açar, o kullanıcı kendi çerez kavanozuyla girer, kural
yazamaz (403), yöneticinin dışa aktarımını indiremez (404) ve yöneticinin sorusunu geçmişinde
görmez. Kullanıcının parolası da bir kez üretilir; ne bir satıra ne bir hataya düşmez.
"""

from __future__ import annotations

import argparse
import codecs
import http.cookiejar
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # betik nereden çağrılırsa çağrılsın nl2sql görünsün

from nl2sql import config, datasets  # noqa: E402
from nl2sql.auth.bootstrap import DEV_USERNAME  # noqa: E402
from nl2sql.web.app import BUILD_COMMAND, NO_UI  # noqa: E402

HOST = "127.0.0.1"
DEFAULT_PORT = 8778
HEALTH_TIMEOUT_S = 30.0  # oturum açılışı + uvicorn; yavaş diskte de bitmeli
POLL_S = 0.25
HTTP_TIMEOUT_S = 60.0  # soru ajanı gerçekten koşuyor
BOM = codecs.BOM_UTF8
ASSET = re.compile(r"/assets/[^\s\"'<>]+")  # derlenmiş sayfanın yüklediği hashli dosyalar


class SmokeError(Exception):
    """Bir adımın geçme sebebi; adımın adı satırda zaten yazılı."""


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dataset = args.dataset or config.DEFAULT_DATASET
    question = datasets.load_dataset(dataset).golden()[0]["question"]

    fd, app_db = tempfile.mkstemp(suffix=".db")  # sunucunun boş kullanıcı dosyası, sonda silinir
    os.close(fd)
    password = secrets.token_urlsafe(16)  # bir kez üretilir; hiçbir satıra, günlüğe, hataya düşmez
    server = _start_server(args.port, args.dataset, app_db, password)
    try:
        code = _run_steps(args.port, question, server, password, ui=args.ui, roles=args.roles)
    finally:
        log = _stop_server(server)
        Path(app_db).unlink(missing_ok=True)
    if code and log:
        print(log, file=sys.stderr)
    return code


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="serve'in uçtan uca dumanı")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="sunucunun bağlanacağı port")
    parser.add_argument("--dataset", default=None, help="kurulu veri kümesi (varsayılan: config)")
    parser.add_argument("--ui", action="store_true", help="derlenmiş arayüzü de dener")
    parser.add_argument("--roles", action="store_true", help="rol kapılarını da dener (R6-22)")
    return parser.parse_args(argv)


def _run_steps(
    port: int,
    question: str,
    server: subprocess.Popen,
    password: str,
    ui: bool = False,
    roles: bool = False,
) -> int:
    """Adımlar sırayla; ilki tökezlerse durur, geçeni tek ✓ satırı olarak basar."""
    state: dict = {}
    opener = _opener()  # girişin açtığı oturum kavanozda durur, sonraki her adım onu taşır
    steps = [
        ("oturumsuz istek 401", lambda: _check_anonymous(port, server, question)),
        ("giriş", lambda: _check_login(opener, port, password)),
        ("sunucu hazır", lambda: _check_health(opener, port)),
        ("soru cevaplandı", lambda: _check_ask(opener, port, question, state)),
        ("dışa aktarım", lambda: _check_export(opener, port, state)),
    ]
    if ui:
        steps.insert(3, ("derlenmiş ekran", lambda: _check_ui(opener, port)))  # boş perdenin önüne
    if roles:
        # Yöneticinin sorusu ve onun dışa aktarımı ölçülünce adımlar onların üstüne kurulur.
        steps += [
            ("yönetici kullanıcısı", lambda: _check_user_added(opener, port, state)),
            ("kullanıcı girişi", lambda: _check_user_login(port, state)),
            ("kural yazımı 403", lambda: _check_rule_denied(port, state)),
            ("yönetici çıktısı 404", lambda: _check_export_denied(port, state)),
            ("geçmiş kişiye özel", lambda: _check_history_scoped(opener, port, question, state)),
        ]
    for name, step in steps:
        try:
            detail = step()
        except SmokeError as exc:
            print(f"✗ {name} — {exc}", file=sys.stderr)
            return 1
        print(f"✓ {name}  {detail}")
    return 0


def _check_anonymous(port: int, server: subprocess.Popen, question: str) -> str:
    """Oturumsuz soru reddedilmeli; reddin kendisi portun dinlendiğinin de işaretidir.

    İlk adım olduğu için hazır olma bekleyişini de o taşır: henüz dinmeyen port bekletilir,
    açılışta ölen sunucu (eksik veritabanı gibi) bekletilmez.
    """
    request = _ask_request(f"http://{HOST}:{port}/api/ask", question)
    started = time.monotonic()
    while True:
        try:
            with urllib.request.urlopen(request, timeout=2.0) as response:  # çerez kavanozu yok
                status = response.status
            raise SmokeError(f"oturumsuz /api/ask {status} verdi; 401 bekleniyor")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            if exc.code != 401:
                raise SmokeError(f"oturumsuz /api/ask {exc.code}: {body}") from None
            return "401"
        except urllib.error.URLError as exc:
            if server.poll() is not None:
                raise SmokeError(f"sunucu kapandı (kod {server.returncode}): {exc.reason}") from None
            if time.monotonic() - started >= HEALTH_TIMEOUT_S:
                raise SmokeError(
                    f"{HEALTH_TIMEOUT_S:.0f} sn içinde sunucu /api/ask'a yanıt vermedi"
                ) from exc
            time.sleep(POLL_S)


def _check_login(opener, port: int, password: str) -> str:
    """Geliştirme yöneticisiyle oturum açar: çerez kavanoza girer, adımlar onu kullanır."""
    payload = _send(opener, _login_request(port, DEV_USERNAME, password), "/api/auth/login")
    if payload.get("username") != DEV_USERNAME:
        raise SmokeError(f"giriş {payload} döndü; {DEV_USERNAME} bekleniyor")
    return f"{payload['username']} · {payload['role']}"


def _check_health(opener, port: int) -> str:
    """Oturumla sağlık: hazır olduğundan artık emin olduğumuz sunucunun gördüğü dünya."""
    payload = _get(opener, f"http://{HOST}:{port}/api/health")
    if payload.get("status") != "ok":
        raise SmokeError(f"/api/health status='ok' değil: {payload}")
    return f"{payload['dataset']['name']} · {payload['llm']['kind']}"


def _check_ui(opener, port: int) -> str:
    """Ekran: yedek sayfa değil derlenmiş sayfa, ve yüklediği dosya gerçekten iniyor."""
    base = f"http://{HOST}:{port}"
    page = _get(opener, f"{base}/", raw=True).decode("utf-8")
    if "Bilgin" not in page:
        raise SmokeError(f"/ yanıtında 'Bilgin' okunmadı: {page[:120]!r}")
    if NO_UI in page:
        raise SmokeError(f"ekran derlenmemiş: {BUILD_COMMAND}")
    assets = ASSET.findall(page)
    if not assets:
        raise SmokeError("/ yanıtında /assets altında bir dosya yok; ekran eksik derlenmiş")
    if not _get(opener, f"{base}{assets[0]}", raw=True):
        raise SmokeError(f"{assets[0]} boş geldi")
    return assets[0]


def _check_ask(opener, port: int, question: str, state: dict) -> str:
    base = f"http://{HOST}:{port}"
    payload = _send(opener, _ask_request(f"{base}/api/ask", question), "/api/ask")
    if payload.get("status") != "answered":
        error = payload.get("error") or {}
        raise SmokeError(
            f"{payload.get('status')}: {error.get('message') or 'cevap alınamadı'}"
            f" (audit {payload.get('audit_id')})"
        )
    state["audit_id"] = payload["audit_id"]
    return f"{payload['row_count']} satır · {payload['audit_id']}"


def _check_export(opener, port: int, state: dict) -> str:
    audit_id = state["audit_id"]
    raw = _get(opener, f"http://{HOST}:{port}/api/export/{audit_id}.csv", raw=True)
    if not raw.startswith(BOM):
        raise SmokeError(f"CSV {BOM!r} ile başlamıyor: {raw[:16]!r}")
    lines = raw.decode("utf-8-sig").splitlines()
    return f"{audit_id}.csv · {lines[0] if lines else 'boş'}"


def _check_user_added(opener, port: int, state: dict) -> str:
    """Yönetici ekranın kendi yolundan bir hesap açar: parolası burada doğar, burada kalır."""
    state["username"] = f"duman{secrets.token_hex(3)}"
    state["password"] = secrets.token_urlsafe(16)
    request = urllib.request.Request(
        f"http://{HOST}:{port}/api/users",
        data=json.dumps(
            {"username": state["username"], "password": state["password"], "role": "user"}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    user = _send(opener, request, "/api/users").get("user") or {}
    if user.get("username") != state["username"] or user.get("role") != "user":
        raise SmokeError(f"/api/users {user} döndü; rolü user olan yeni hesap bekleniyor")
    return state["username"]


def _check_user_login(port: int, state: dict) -> str:
    """Kullanıcının çerez kavanozu yöneticininkiyle aynı kapıdan geçer, ama ayrı durur."""
    state["user_opener"] = _opener()
    payload = _send(
        state["user_opener"],
        _login_request(port, state["username"], state["password"]),
        "/api/auth/login",
    )
    if payload.get("role") != "user":
        raise SmokeError(f"giriş {payload} döndü; rol user bekleniyor")
    return f"{payload['username']} · {payload['role']}"


def _check_rule_denied(port: int, state: dict) -> str:
    """Rol kapısı: kullanıcı tanınıyor ama yetmiyor -- reddin adı 403, yokluk değil 403."""
    request = urllib.request.Request(
        f"http://{HOST}:{port}/api/rules",
        data=json.dumps(
            {"id": "duman_kurali", "term": "Duman terimi", "definition": "Dumanın kendi tarifi."}
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return _expect(state["user_opener"], request, "/api/rules", 403)


def _check_export_denied(port: int, state: dict) -> str:
    """Yöneticinin sorusu kullanıcı için yoktur: indirme 404 verir, yani yokluk gibi konuşır."""
    label = f"/api/export/{state['audit_id']}.csv"
    request = urllib.request.Request(f"http://{HOST}:{port}{label}", method="GET")
    return _expect(state["user_opener"], request, label, 404)


def _check_history_scoped(opener, port: int, question: str, state: dict) -> str:
    """Geçmiş kişiye özel: yöneticinin sorusu onun kendi listesinde, kullanıcınınkinde değil."""
    mine = _questions(opener, port)
    if question not in mine:
        raise SmokeError("yöneticinin geçmişi kendi sorduğu soruyu göstermiyor")
    theirs = _questions(state["user_opener"], port)
    if question in theirs:
        raise SmokeError("kullanıcı yöneticinin sorusunu kendi geçmişinde görüyor")
    return f"yönetici {len(mine)} satır · kullanıcı {len(theirs)} satır"


def _ask_request(url: str, question: str) -> urllib.request.Request:
    """Aynı istek gövdesi iki kez kurulmaz: oturumsuz denenenle cevaplanan soru birebir aynıdır."""
    return urllib.request.Request(
        url,
        data=json.dumps({"question": question}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def _login_request(port: int, username: str, password: str) -> urllib.request.Request:
    """Giriş isteği: yönetici de yeni açılan kullanıcı da aynı gövdeyle kapıya dayanır."""
    return urllib.request.Request(
        f"http://{HOST}:{port}/api/auth/login",
        data=json.dumps({"username": username, "password": password}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def _questions(opener, port: int) -> list[str]:
    """Geçmişin soruları, en yeni önce: geçmişin kimin olduğu sorusunun okunur cevabı."""
    payload = _get(opener, f"http://{HOST}:{port}/api/history")
    return [item["question"] for item in payload.get("history", [])]


def _opener():
    """Çerez kavanozlu istemci: ``/api/auth/login``ın açtığı oturum tek satır kod gerektirmez."""
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


def _get(opener, url: str, timeout: float = HTTP_TIMEOUT_S, raw: bool = False):
    return _send(opener, urllib.request.Request(url, method="GET"), url, timeout=timeout, raw=raw)


def _send(opener, request, label: str, timeout: float = HTTP_TIMEOUT_S, raw: bool = False):
    """Tek HTTP kapısı: 4xx/5xx, gövdedeki ayrıntıyla birlikte SmokeError olur."""
    try:
        with opener.open(request, timeout=timeout) as response:
            content = response.read()
    except urllib.error.HTTPError as exc:
        raise SmokeError(
            f"{label} -> {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}"
        ) from exc
    return content if raw else json.loads(content.decode("utf-8"))


def _expect(opener, request, label: str, code: int) -> str:
    """Reddi ölçen kapı: beklenen durum kodu dışında her şey SmokeError, kabul de öyle."""
    try:
        with opener.open(request, timeout=HTTP_TIMEOUT_S) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        if exc.code != code:
            raise SmokeError(
                f"{label} -> {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}"
            ) from exc
        return f"{code}"
    raise SmokeError(f"{label} {code} yerine cevap verdi; kapı açık kalmış")


def _start_server(
    port: int, dataset: str | None, app_db: str, password: str
) -> subprocess.Popen:
    argv = [sys.executable, "-m", "nl2sql", "serve", "--llm", "fake", "--port", str(port)]
    if dataset:
        argv += ["--dataset", dataset]
    return subprocess.Popen(
        argv,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        env={
            **os.environ,
            "NL2SQL_BACKEND": "sqlite",
            "PYTHONIOENCODING": "utf-8",
            "NL2SQL_APP_DB": app_db,  # boş dünya: dumanın kullanıcısı gerçek veriye dokunmaz
            config.DEV_ADMIN_ENV: password,
        },
    )


def _stop_server(server: subprocess.Popen) -> str:
    """Sunucuyu kapatır ve biriktirdiği çıktıyı döndürür: açılış hatası o çıktının içindedir."""
    if server.poll() is None:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait(timeout=10)
    try:
        return (server.communicate(timeout=10)[0] or "").strip()
    except (subprocess.TimeoutExpired, ValueError):
        return ""


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
