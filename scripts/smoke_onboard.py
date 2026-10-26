"""Şablondan veri kümesine onboarding dumanı: yeni bir veritabanını uçtan uca tanıtır (PLAN R6-22).

``scripts/smoke_serve`` sunucunun varlığını ölçüyor; burada ölçülen şey haritanın kendisi --
yönetici boş şablonu indiriyor, dolu bir örneği yüklüyor, kontrol raporu hatasız çıkıyor, küme
uygulanıp indeksi kuruluyor, yeni kümenin SQLite dosyası şemasından doğuyor, etkin küme ona
değiştiriliyor ve sahte model ondan bir soruyu cevaplıyor. Yani "harita çalışıyor"un anlamı
şablonun inmesi değil, uçta gerçek bir cevabın dönmesidir.

Duman gerçek hiçbir veriye dokunmaz: boş bir uygulama veritabanı (``NL2SQL_APP_DB``) ve geçici bir
gerçek-kümeler kökü (``NL2SQL_REAL_DATASETS_DIR``) üstünde koşar, yöneticinin parolası bir kez
üretilir ve hiçbir satıra düşmez. Kurulan kümenin adı sabittir (``smoke_fatura``), böylece işi
biten duman kendi ürettiği ``data/smoke_fatura.db``yi ve ``index/smoke_fatura``yı siler; depo
kökündeki ``real_datasets/`` hiç açılmaz. Sunucu her durumda kapatılır; biriktirdiği çıktı yalnız
adım tökezlerse ekrana dökülür.
"""

from __future__ import annotations

import argparse
import base64
import http.cookiejar
import json
import os
import secrets
import shutil
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
from nl2sql.schema_map import build, template  # noqa: E402

HOST = "127.0.0.1"
DEFAULT_PORT = 8782
HEALTH_TIMEOUT_S = 30.0  # oturum açılışı + uvicorn; yavaş diskte de bitmeli
POLL_S = 0.25
HTTP_TIMEOUT_S = 60.0
INDEX_TIMEOUT_S = 60.0  # R6-22: indeks işi bu kadar saniyede bitmiş olmalı
DATASET = "smoke_fatura"  # dumanın kurduğu küme; adı her yerde aynı, temizlik de ona göre
QUESTION = "Fatura sayısı kaç?"  # altın soru değil: sahte model kalıp sorguyu oynatır


class SmokeError(Exception):
    """Bir adımın geçme sebebi; adımın adı satırda zaten yazılı."""


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    app_db = _temp_db()
    real_dir = Path(tempfile.mkdtemp(prefix="bilgin-smoke-real-"))
    password = secrets.token_urlsafe(16)  # bir kez üretilir; hiçbir satıra, günlüğe, hataya düşmez
    # Ortamı hem bu süreç hem alt süreç görmeli: şemayı okuyup db'yi kurmak bu süreçte olur,
    # sunucu ise aynı geçici kökü alt süreçte okur -- depo kökündeki real_datasets/ açılmaz.
    os.environ["NL2SQL_APP_DB"] = app_db
    os.environ["NL2SQL_REAL_DATASETS_DIR"] = str(real_dir)
    os.environ[config.DEV_ADMIN_ENV] = password
    state: dict = {}
    server = _start_server(args.port)
    try:
        code = _run_steps(args.port, password, server, state)
    finally:
        log = _stop_server(server)
        _cleanup(real_dir, app_db, state)
    if code and log:
        print(log, file=sys.stderr)
    return code


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="şablondan veri kümesine onboarding dumanı")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="sunucunun bağlanacağı port")
    return parser.parse_args(argv)


def _run_steps(port: int, password: str, server: subprocess.Popen, state: dict) -> int:
    """Adımlar sırayla; ilki tökezlerse durur, geçeni tek ✓ satırı olarak basar."""
    opener = _opener()  # girişin açtığı oturum kavanozda durur, sonraki her adım onu taşır
    base = f"http://{HOST}:{port}"
    steps = [
        ("giriş", lambda: _check_login(opener, port, password, server)),
        ("şablon indirildi", lambda: _check_template(opener, base)),
        ("önizleme temiz", lambda: _check_preview(opener, base, state)),
        ("uygulandı", lambda: _check_apply(opener, base, state)),
        ("indeks hazır", lambda: _check_index(opener, base, state)),
        ("veritabanı kuruldu", lambda: _check_db()),
        ("küme etkin", lambda: _check_activate(opener, base)),
        ("soru cevaplandı", lambda: _check_ask(opener, base)),
    ]
    for name, step in steps:
        try:
            detail = step()
        except SmokeError as exc:
            print(f"✗ {name} — {exc}", file=sys.stderr)
            return 1
        print(f"✓ {name}  {detail}")
    return 0


def _check_login(opener, port: int, password: str, server: subprocess.Popen) -> str:
    """Geliştirme yöneticisiyle girilir; ilk adım olduğu için portun dinlenmesini de bekler."""
    request = _login_request(port, password)
    started = time.monotonic()
    while True:
        try:
            payload = _send(opener, request, "/api/auth/login")
            break
        except urllib.error.URLError as exc:  # henüz dinmeyen port; ölü sunucu bekletilmez
            if server.poll() is not None:
                raise SmokeError(f"sunucu kapandı (kod {server.returncode}): {exc.reason}") from None
            if time.monotonic() - started >= HEALTH_TIMEOUT_S:
                raise SmokeError(f"{HEALTH_TIMEOUT_S:.0f} sn içinde sunucu yanıt vermedi") from exc
            time.sleep(POLL_S)
    if payload.get("username") != DEV_USERNAME:
        raise SmokeError(f"giriş {payload} döndü; {DEV_USERNAME} bekleniyor")
    return f"{payload['username']} · {payload['role']}"


def _check_template(opener, base: str) -> str:
    """Boş şablon iniyor mu: .xlsx bir zip taşıyıcısıdır, yani PK ile başlar."""
    raw = _get(opener, f"{base}/api/schema-map/template.xlsx", raw=True)
    if not raw.startswith(b"PK"):
        raise SmokeError(f"şablon xlsx değil (zip imzası yok): {raw[:8]!r}")
    return f"{len(raw)} bayt"


def _check_preview(opener, base: str, state: dict) -> str:
    """Dolu örnek yüklenir ve kontrol raporu hatasız olmalı: uygulanacak rapor budur."""
    book = template.filled_example_workbook(DATASET)
    body = {"filename": f"{DATASET}.xlsx", "content_b64": base64.b64encode(book).decode("ascii")}
    payload = _send(opener, _post(f"{base}/api/schema-map/preview", body), "/api/schema-map/preview")
    errors = payload.get("errors") or []
    if errors:
        raise SmokeError(f"{len(errors)} hata: {errors[0]}")
    state["preview_id"] = payload["preview_id"]
    counts = payload.get("counts") or {}
    return f"{counts.get('tables', 0)} tablo · {counts.get('columns', 0)} kolon · 0 hata"


def _check_apply(opener, base: str, state: dict) -> str:
    """Rapor kümeye dönüşür ve indeks arka plana bırakılır; aşama yazılıyor/indexing olabilir."""
    body = {"preview_id": state["preview_id"]}
    payload = _send(opener, _post(f"{base}/api/schema-map/apply", body), "/api/schema-map/apply")
    if payload.get("phase") == "failed":
        raise SmokeError(payload.get("message") or "uygulama başarısız")
    return f"{payload.get('name')} · {payload.get('phase')}"


def _check_index(opener, base: str, state: dict) -> str:
    """İndeks işi done'a kadar yoklanır; failed ya da süre aşımı SmokeError."""
    url = f"{base}/api/schema-map/status/{state['preview_id']}"
    started = time.monotonic()
    while True:
        payload = _get(opener, url)
        phase = payload.get("phase")
        if phase == "done":
            return f"{payload.get('name')} · indeks hazır"
        if phase == "failed":
            raise SmokeError(payload.get("message") or "indeks kurulamadı")
        if time.monotonic() - started >= INDEX_TIMEOUT_S:
            raise SmokeError(f"{INDEX_TIMEOUT_S:.0f} sn içinde indeks bitmedi (aşama {phase})")
        time.sleep(POLL_S)


def _check_db() -> str:
    """Kümenin SQLite dosyası şemasından doğar: sorunun çarpacağı tablo artık diskte."""
    ds = datasets.load_dataset(DATASET)
    build.write_sqlite({}, ds.schema(), ds.db_path)
    if not ds.db_path.is_file():
        raise SmokeError(f"{ds.db_path} kurulmadı")
    return ds.db_path.relative_to(config.ROOT).as_posix()


def _check_activate(opener, base: str) -> str:
    """Etkin küme değiştirilir: sunucu artık yeni dünyanın şemasını, indeksini ve db'sini görür."""
    body = {"name": DATASET}
    payload = _send(opener, _post(f"{base}/api/datasets/active", body), "/api/datasets/active")
    if payload.get("active") != DATASET:
        raise SmokeError(f"etkin küme {payload.get('active')}; {DATASET} bekleniyor")
    return payload["active"]


def _check_ask(opener, base: str) -> str:
    """Uç: sahte model kalıp sorguyu yeni kümede oynatır ve cevap döner."""
    payload = _send(opener, _post(f"{base}/api/ask", {"question": QUESTION}), "/api/ask")
    if payload.get("status") != "answered":
        error = payload.get("error") or {}
        raise SmokeError(f"{payload.get('status')}: {error.get('message') or 'cevap alınamadı'}")
    return f"{payload['row_count']} satır"


def _post(url: str, body: dict) -> urllib.request.Request:
    return urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )


def _login_request(port: int, password: str) -> urllib.request.Request:
    return _post(
        f"http://{HOST}:{port}/api/auth/login",
        {"username": DEV_USERNAME, "password": password},
    )


def _opener():
    """Çerez kavanozlu istemci: ``/api/auth/login``ın açtığı oturum tek satır kod gerektirmez."""
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )


def _get(opener, url: str, raw: bool = False):
    return _send(opener, urllib.request.Request(url, method="GET"), url, raw=raw)


def _send(opener, request, label: str, raw: bool = False):
    """Tek HTTP kapısı: 4xx/5xx, gövdedeki ayrıntıyla birlikte SmokeError olur (bağlantı hatası değil)."""
    try:
        with opener.open(request, timeout=HTTP_TIMEOUT_S) as response:
            content = response.read()
    except urllib.error.HTTPError as exc:
        raise SmokeError(
            f"{label} -> {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}"
        ) from exc
    return content if raw else json.loads(content.decode("utf-8"))


def _start_server(port: int) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "nl2sql", "serve", "--llm", "fake", "--port", str(port)],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        env={
            **os.environ,
            "NL2SQL_BACKEND": "sqlite",
            "PYTHONIOENCODING": "utf-8",
            # NL2SQL_APP_DB / NL2SQL_REAL_DATASETS_DIR / NL2SQL_DEV_ADMIN_PASSWORD os.environ'da:
            # boş dünya -- dumanın kurduğu küme gerçek veriye dokunmaz.
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


def _cleanup(real_dir: Path, app_db: str, state: dict) -> None:
    """Kendi yarattıklarını siler: geçici kökler, kurulan db, kurulan indeks, bekleyen önizleme."""
    shutil.rmtree(real_dir, ignore_errors=True)
    Path(app_db).unlink(missing_ok=True)
    (config.ROOT / "data" / f"{DATASET}.db").unlink(missing_ok=True)
    shutil.rmtree(config.ROOT / "index" / DATASET, ignore_errors=True)
    preview_id = state.get("preview_id")
    if preview_id:
        (Path(config.MAP_PREVIEWS_DIR) / f"{preview_id}.json").unlink(missing_ok=True)


def _temp_db() -> str:
    fd, path = tempfile.mkstemp(suffix=".db")  # sunucunun boş kullanıcı dosyası, sonda silinir
    os.close(fd)
    return path


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
