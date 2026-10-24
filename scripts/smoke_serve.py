"""``serve`` dumanı: API'yi gerçekten ayağa kaldırır, üç adımın üstünden HTTP ile geçer.

Komut satırı araçları zaten test ediliyor; burada ölçülen şey sunucunun kendisi — ``python -m
nl2sql serve`` bir alt süreç olarak açılır, portu dinlemeye başlayana kadar beklenir, sonra
``/api/health`` → ``POST /api/ask`` → ``GET /api/export/<id>.csv`` sırası koşar. Soru kümenin ilk
altın sorusudur: sahte model onu birebir bildiği için cevap ``answered`` olmak zorundadır, yani
dumanın geçti "bir şey döndü" değil "uçtan uca cevap döndü" demektir.

Sunucu her durumda kapatılır; biriktirdiği çıktı yalnız adım tökezlerse ekrana dökülür, böylece
eksik veritabanı gibi bir açılış hatası kendi cümlesiyle görünür. ``--ui`` şimdilik kabul edilip
yok sayılır (arayüzün kendisi T204'te sınanacak).
"""

from __future__ import annotations

import argparse
import codecs
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # betik nereden çağrılırsa çağrılsın nl2sql görünsün

from nl2sql import config, datasets  # noqa: E402

HOST = "127.0.0.1"
DEFAULT_PORT = 8778
HEALTH_TIMEOUT_S = 30.0  # oturum açılışı + uvicorn; yavaş diskte de bitmeli
POLL_S = 0.25
HTTP_TIMEOUT_S = 60.0  # soru ajanı gerçekten koşuyor
BOM = codecs.BOM_UTF8


class SmokeError(Exception):
    """Bir adımın geçme sebebi; adımın adı satırda zaten yazılı."""


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dataset = args.dataset or config.DEFAULT_DATASET
    question = datasets.load_dataset(dataset).golden()[0]["question"]

    server = _start_server(args.port, args.dataset)
    try:
        code = _run_steps(args.port, question, server)
    finally:
        log = _stop_server(server)
    if code and log:
        print(log, file=sys.stderr)
    return code


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="serve'in uçtan uca dumanı")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="sunucunun bağlanacağı port")
    parser.add_argument("--dataset", default=None, help="kurulu veri kümesi (varsayılan: config)")
    # ASSUMPTION: --ui arayüzün kendi sınamasıdır (T204); burada henüz yalnız kabul ediliyor.
    parser.add_argument("--ui", action="store_true", help="derlenmiş arayüzü de dener (T204)")
    return parser.parse_args(argv)


def _run_steps(port: int, question: str, server: subprocess.Popen) -> int:
    """Adımlar sırayla; ilki tökezlerse durur, geçeni tek ✓ satırı olarak basar."""
    state: dict = {}
    steps = (
        ("sunucu hazır", lambda: _check_health(port, server)),
        ("soru cevaplandı", lambda: _check_ask(port, question, state)),
        ("dışa aktarım", lambda: _check_export(port, state)),
    )
    for name, step in steps:
        try:
            detail = step()
        except SmokeError as exc:
            print(f"✗ {name} — {exc}", file=sys.stderr)
            return 1
        print(f"✓ {name}  {detail}")
    return 0


def _check_health(port: int, server: subprocess.Popen) -> str:
    """Port dinlenene kadar yoklar; açılışta ölen sunucu bekletilmez."""
    base = f"http://{HOST}:{port}"
    started = time.monotonic()
    while True:
        try:
            payload = _get(f"{base}/api/health", timeout=2.0)
        except urllib.error.URLError as exc:
            if server.poll() is not None:
                raise SmokeError(f"sunucu kapandı (kod {server.returncode}): {exc.reason}") from None
            if time.monotonic() - started >= HEALTH_TIMEOUT_S:
                raise SmokeError(f"{HEALTH_TIMEOUT_S:.0f} sn içinde /api/health yanıt vermedi") from exc
            time.sleep(POLL_S)
            continue
        if payload.get("status") != "ok":
            raise SmokeError(f"/api/health status='ok' değil: {payload}")
        return f"{payload['dataset']['name']} · {payload['llm']['kind']}"


def _check_ask(port: int, question: str, state: dict) -> str:
    base = f"http://{HOST}:{port}"
    request = urllib.request.Request(
        f"{base}/api/ask",
        data=json.dumps({"question": question}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    payload = _send(request, "/api/ask")
    if payload.get("status") != "answered":
        error = payload.get("error") or {}
        raise SmokeError(
            f"{payload.get('status')}: {error.get('message') or 'cevap alınamadı'}"
            f" (audit {payload.get('audit_id')})"
        )
    state["audit_id"] = payload["audit_id"]
    return f"{payload['row_count']} satır · {payload['audit_id']}"


def _check_export(port: int, state: dict) -> str:
    audit_id = state["audit_id"]
    raw = _get(f"http://{HOST}:{port}/api/export/{audit_id}.csv", raw=True)
    if not raw.startswith(BOM):
        raise SmokeError(f"CSV {BOM!r} ile başlamıyor: {raw[:16]!r}")
    lines = raw.decode("utf-8-sig").splitlines()
    return f"{audit_id}.csv · {lines[0] if lines else 'boş'}"


def _get(url: str, timeout: float = HTTP_TIMEOUT_S, raw: bool = False):
    return _send(urllib.request.Request(url, method="GET"), url, timeout=timeout, raw=raw)


def _send(request, label: str, timeout: float = HTTP_TIMEOUT_S, raw: bool = False):
    """Tek HTTP kapısı: 4xx/5xx, gövdedeki ayrıntıyla birlikte SmokeError olur."""
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            content = response.read()
    except urllib.error.HTTPError as exc:
        raise SmokeError(
            f"{label} -> {exc.code}: {exc.read().decode('utf-8', 'replace')[:300]}"
        ) from exc
    return content if raw else json.loads(content.decode("utf-8"))


def _start_server(port: int, dataset: str | None) -> subprocess.Popen:
    argv = [sys.executable, "-m", "nl2sql", "serve", "--llm", "fake", "--port", str(port)]
    if dataset:
        argv += ["--dataset", dataset]
    return subprocess.Popen(
        argv,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding="utf-8",
        env={**os.environ, "NL2SQL_BACKEND": "sqlite", "PYTHONIOENCODING": "utf-8"},
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
