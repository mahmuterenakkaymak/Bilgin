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

``--conversation`` Run 7'nin ardışık soru zincirini aynı sunucuda ve aynı yöneticinin oturumuyla koşar
(M23, ``--roles``ın deseniyle): kümenin ilk zincirinin (F01) ilk turu ``conversation_id``siz sorulur ve
konuşmanın kimliği cevabın içinden okunur -- kimlik soruda değil cevapta doğar. İkinci tur o kimlikle
sorulur ve bağlam notunun birinci turu saydığı cevaptan okunur; üçüncü tur yalnız sunumu değiştirir, yani
model hiç koşurmamalı, ikinci turun SQL'ini aynıyla yürütüp grafiği pasta yapmalıdır. Son adım
``GET /api/conversations/{id}`nin üç tur döndürdüğünü ölçer: konuşma depoda gerçekten duruyor. Zincir
sunucunun ``/api/health``te söylediği kümeden okunur -- ``serve`` ``--dataset`` söylenmediğinde kendi
sırasını açar, betiğin varsaydığı adı sunmayabilir.

``--start`` Run 7'nin başlangıç ekranını aynı sunucuda koşar (R7-18, R7-19): yönetici ``/api/users``tan
iş rolü ``satis`` olan bir hesap açar, o kullanıcı kendi çerez kavanozuyla girer ve ``GET /api/start``
panoyu **yüküyle** döndürür -- hiçbir kartta hata satırı yoktur, sayının değeri, grafiğin seçeneği,
tablonun satırı vardır. Bir kartı açmak modelsiz bir cevaptır: ``answered``, tur 1 ve doğduğu konuşmanın
kimliği; aynı kimlikle sorulan takip sorusu tur 2 döner, yani kart bir daha sorulmayan bir cümle değil
devam eden bir sohbettir. Ölçülen pano tohumlu bir kümenin panosudur, o yüzden ``--start`` ``--dataset``
söylenmediğinde kümeyi kendisi söyler: ``serve``ın vitrin sırası hazır sorusu olmayan bir kümeye
düşebilir ve boş bir pano dumanın geçmesi değildir.
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
START_ROLE = "satis"  # --start panosunu süzer: tohum hazır soruların ilk rolü


class SmokeError(Exception):
    """Bir adımın geçme sebebi; adımın adı satırda zaten yazılı."""


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dataset = args.dataset or config.DEFAULT_DATASET
    question = datasets.load_dataset(dataset).golden()[0]["question"]
    # ASSUMPTION: --start tohumlu bir küme ölçer; --dataset söylenmemişse küme betikten söylenir, çünkü
    # serve'ın kendi sırası hazır sorusu olmayan bir kümeye düşebilir ve boş pano dumanın geçmesi değildir.
    served = dataset if args.start else args.dataset

    fd, app_db = tempfile.mkstemp(suffix=".db")  # sunucunun boş kullanıcı dosyası, sonda silinir
    os.close(fd)
    password = secrets.token_urlsafe(16)  # bir kez üretilir; hiçbir satıra, günlüğe, hataya düşmez
    server = _start_server(args.port, served, app_db, password)
    try:
        code = _run_steps(
            args.port, question, server, password,
            ui=args.ui, roles=args.roles, conversation=args.conversation, start=args.start,
        )
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
    parser.add_argument(
        "--conversation", action="store_true", help="ardışık soru zincirini de dener (R7-8, R7-10)"
    )
    parser.add_argument(
        "--start", action="store_true", help="başlangıç ekranını ve karttan açmayı da dener (R7-18)"
    )
    return parser.parse_args(argv)


def _run_steps(
    port: int,
    question: str,
    server: subprocess.Popen,
    password: str,
    ui: bool = False,
    roles: bool = False,
    conversation: bool = False,
    start: bool = False,
) -> int:
    """Adımlar sırayla; ilki tökezlerse durur, geçeni tek ✓ satırı olarak basar."""
    state: dict = {}
    opener = _opener()  # girişin açtığı oturum kavanozda durur, sonraki her adım onu taşır
    steps = [
        ("oturumsuz istek 401", lambda: _check_anonymous(port, server, question)),
        ("giriş", lambda: _check_login(opener, port, password)),
        ("sunucu hazır", lambda: _check_health(opener, port, state)),
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
    if conversation:
        # Zincirin turları konuşmanın kimliğiyle çoğalır: ilki onu doğurur, ötekiler taşır.
        steps += [
            ("konuşmanın ilk turu", lambda: _check_conversation_open(opener, port, state)),
            ("bağlamlı ikinci tur", lambda: _check_conversation_context(opener, port, state)),
            ("modelsiz sunum değişikliği", lambda: _check_conversation_refine(opener, port, state)),
            ("konuşmanın üç turu", lambda: _check_conversation_thread(opener, port, state)),
        ]
    if start:
        # Pano iş rolünün süzgecinden okunur: ekran bir satış kullanıcısının gözünden denenir.
        steps += [
            ("satış kullanıcısı", lambda: _check_user_added(opener, port, state, START_ROLE)),
            ("kullanıcı girişi", lambda: _check_user_login(port, state)),
            ("başlangıç ekranı kartları", lambda: _check_start(port, state)),
            ("karttan açılan konuşma", lambda: _check_card_open(port, state)),
            ("kartın ikinci turu", lambda: _check_card_followup(port, state, question)),
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


def _check_health(opener, port: int, state: dict) -> str:
    """Oturumla sağlık: hazır olduğundan artık emin olduğumuz sunucunun gördüğü dünya.

    Gördüğü küme ``state``e de yazılır: ``--conversation`` zinciri sunucunun gerçekten açtığı
    kümeden okumalı, betiğin varsaydığından -- ``serve`` ``--dataset``sız kendi sırasını açar.
    """
    payload = _get(opener, f"http://{HOST}:{port}/api/health")
    if payload.get("status") != "ok":
        raise SmokeError(f"/api/health status='ok' değil: {payload}")
    state["dataset"] = payload["dataset"]["name"]
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


def _check_user_added(opener, port: int, state: dict, business_role: str | None = None) -> str:
    """Yönetici ekranın kendi yolundan bir hesap açar: parolası burada doğar, burada kalır.

    ``business_role`` yalnız panoyu ölçen adım için söylenir -- kartların süzgeci iş rolüdür.
    """
    state["username"] = f"duman{secrets.token_hex(3)}"
    state["password"] = secrets.token_urlsafe(16)
    body = {"username": state["username"], "password": state["password"], "role": "user"}
    if business_role:
        body["business_role"] = business_role
    request = urllib.request.Request(
        f"http://{HOST}:{port}/api/users",
        data=json.dumps(body).encode("utf-8"),
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


def _check_conversation_open(opener, port: int, state: dict) -> str:
    """İlk tur ``conversation_id``siz sorulur: konuşmanın kimliği cevapta doğar (R7-8)."""
    payload = _ask_turn(opener, port, _chain(state)[0]["question"], state)
    if payload.get("turn") != 1:
        raise SmokeError(f"ilk turun tur numarası {payload.get('turn')}; 1 bekleniyor")
    state["conversation_id"] = payload["conversation_id"]
    return f"tur 1 · {state['conversation_id'][:8]}…"


def _check_conversation_context(opener, port: int, state: dict) -> str:
    """İkinci tur birincinin üstüne kurulur: bağlam notu ``uses_turns``ta 1'i sayar (R7-4, R7-5)."""
    payload = _ask_turn(opener, port, _chain(state)[1]["question"], state)
    if payload.get("turn") != 2:
        raise SmokeError(f"ikinci turun tur numarası {payload.get('turn')}; 2 bekleniyor")
    used = (payload.get("context") or {}).get("uses_turns")
    if used != [1]:
        raise SmokeError(f"ikinci turun bağlamı {used} turu kullandı; [1] bekleniyor")
    state["sql"] = payload["sql"]
    return "tur 2 · uses_turns [1]"


def _check_conversation_refine(opener, port: int, state: dict) -> str:
    """Sunum değişikliği modeli hiç koşurmaz: ikinci turun SQL'i aynıyla yürür, grafik pastadır (R7-10)."""
    payload = _ask_turn(opener, port, _chain(state)[2]["question"], state)
    if payload.get("turn") != 3:
        raise SmokeError(f"üçüncü turun tur numarası {payload.get('turn')}; 3 bekleniyor")
    if payload.get("sql") != state["sql"]:
        raise SmokeError("sunum değişikliği başka bir SQL koştu; ikinci turun sorgusu aynıyla yürümeli")
    chart = payload.get("chart") or {}
    if chart.get("type") != "pie":
        raise SmokeError(f"sunum değişikliğinin grafiği {chart.get('type')!r}; pasta bekleniyor")
    return "tur 3 · pasta · SQL yineleyendi"


def _check_conversation_thread(opener, port: int, state: dict) -> str:
    """Konuşma depoda üç turdur: ``GET`` turların kendisini sahibine döner (R7-8)."""
    thread = _get(opener, f"http://{HOST}:{port}/api/conversations/{state['conversation_id']}")
    stored = thread.get("turns") or []
    if len(stored) != 3:
        raise SmokeError(f"konuşma {len(stored)} tur döndürdü; 3 bekleniyor")
    return f"{len(stored)} tur"


def _check_start(port: int, state: dict) -> str:
    """Pano kartları yüküyle döner: yürümeyen ya da boş bir kart dumanın tökezlemesidir (R7-18)."""
    payload = _get(state["user_opener"], f"http://{HOST}:{port}/api/start")
    if payload.get("business_role") != START_ROLE:
        raise SmokeError(
            f"pano {payload.get('business_role')!r} rolünü söylüyor; {START_ROLE} bekleniyor"
        )
    cards = payload.get("cards") or []
    if not cards:
        raise SmokeError("pano kart döndürmedi; tohum hazır sorular yazılmamış")
    for card in cards:
        if card.get("error"):
            raise SmokeError(f"{card.get('title')!r} kartı yürümedi: {card['error']}")
        if not _loaded(card):
            raise SmokeError(f"{card.get('title')!r} kartının yükü boş ({card.get('display')})")
    state["card_id"] = cards[0]["id"]
    return f"{len(cards)} kart · {cards[0]['title']}"


def _loaded(card: dict) -> bool:
    """Kartın yükü gerçekten dolu mu: sayının değeri, grafiğin seçeneği, tablonun satırları."""
    if card.get("display") == "number":
        return card.get("value") is not None
    if card.get("display") == "chart":
        return bool(card.get("chart"))
    return bool(card.get("rows"))


def _check_card_open(port: int, state: dict) -> str:
    """Kartı açmak modelsiz bir cevaptır ve yeni bir konuşmanın 1. turudur (R7-18)."""
    label = f"/api/start/cards/{state['card_id']}/open"
    payload = _send(
        state["user_opener"],
        urllib.request.Request(f"http://{HOST}:{port}{label}", data=b"", method="POST"),
        label,
    )
    if payload.get("status") != "answered":
        error = payload.get("error") or {}
        raise SmokeError(f"{payload.get('status')}: {error.get('message') or 'cevap alınamadı'}")
    if payload.get("turn") != 1:
        raise SmokeError(f"kartın açtığı turun numarası {payload.get('turn')}; 1 bekleniyor")
    state["conversation_id"] = payload["conversation_id"]
    return f"tur 1 · {state['conversation_id'][:8]}…"


def _check_card_followup(port: int, state: dict, question: str) -> str:
    """Kartın konuşması takip sorusunu da taşır: aynı kimlikle sorulan tur 2 olur (R7-8)."""
    payload = _ask_turn(state["user_opener"], port, question, state)
    if payload.get("turn") != 2:
        raise SmokeError(
            f"kartın konuşmasında ikinci turun numarası {payload.get('turn')}; 2 bekleniyor"
        )
    return "tur 2 · aynı konuşma"


def _ask_turn(opener, port: int, question: str, state: dict) -> dict:
    """Zincirin bir turu: kimlik doğduysa gövde o kimlikle gider, cevaplanmayan tur dumanın tökezlemesidir."""
    payload = _send(
        opener,
        _ask_request(f"http://{HOST}:{port}/api/ask", question, state.get("conversation_id")),
        "/api/ask",
    )
    if payload.get("status") != "answered":
        error = payload.get("error") or {}
        raise SmokeError(
            f"{payload.get('status')}: {error.get('message') or 'cevap alınamadı'}"
            f" (audit {payload.get('audit_id')})"
        )
    return payload


def _chain(state: dict) -> list[dict]:
    """Ölçülen zincir: sunucunun açtığı kümenin ilk ardışık soru zincirinin turları (F01, R7-14)."""
    if "chain" not in state:
        chains = datasets.load_dataset(state["dataset"]).followups()
        turns = list((chains[0].get("turns") or []) if chains else [])
        if len(turns) < 3:
            raise SmokeError(f"{state['dataset']} zincirinde üç tur yok; --conversation koşamaz")
        state["chain"] = turns
    return state["chain"]


def _ask_request(url: str, question: str, conversation_id: str | None = None) -> urllib.request.Request:
    """Aynı istek gövdesi iki kez kurulmaz: oturumsuz denenenle cevaplanan soru birebir aynıdır.

    ``conversation_id`` yalnız verildiğinde gövdeye girer -- verilmemesi yeni bir konuşma demek (R7-8).
    """
    body = {"question": question}
    if conversation_id:
        body["conversation_id"] = conversation_id
    return urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
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
