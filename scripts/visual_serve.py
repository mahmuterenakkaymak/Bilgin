# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Görsel inceleme sunucusu: ``serve``, ama gördüğü dünya ``data/visual/`` altındadır (PLAN R6-20).

Kilometre taşı incelemesi tarayıcıdan akış koşuyor ve o akışın artık bir kullanıcısı var: giriş
kartı, oturum çipi, çıkış. Gerçek ``data/bilgin.db``nin yöneticisinin parolası bilinemez ve
değiştirilemez, o yüzden inceleme kendi boş dünyasında koşar — uygulama veritabanı da ekrandan
yüklenen gerçek kümeler de ``data/visual/`` altına yazılır ve her koşuda baştan kurulur. Yol
denetimi bu izolasyonun kendisidir: ``data/visual/`` dışındaki hiçbir yol silinmez, yani yanlışlıkla
gerçek veritabanına ya da depodaki ``real_datasets/``e dokunulamaz. Tek istisna haritanın
kurduğu kümelerdir: ``ornek_fatura``nın ve ``vitrin_kapali``nin veritabanı ile indeksi küme
sözleşmesinin verdiği yollarda durur (``data/ornek_fatura.db``, ``index/vitrin_kapali``), o yüzden
akış onları kum havuzunun dışında kurar ve eski indeksi baştan siler. Bağlantı yoklaması da
gerçek bir sunucuya değil ``data/visual/db_probe.json``e sorar (R7-26): incelemedeki yeşil ve
kırmızı nokta ile guard'ın "yazabiliyor" cevabı o dosyanın sözüdür, SQL Server gerekmez.

``VISUAL_PASSWORD`` bilinçli olarak depoda durur: tek kullanımlık bir kum havuzu parolasıdır, üç
incelemeci hesabından başka bir şey korumaz ve ``.hybrid/visual.json`` da aynı değeri yazar. Ürünün
kodu onu tanımaz; ``nl2sql/`` altında arandığında boş dönmesinin sebebi bu. Sunucu ``serve``ı alt
süreç olarak açar, böylece inceleme de aynı komut satırı kapısından geçer.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # betik nereden çağrılırsa çağrılsın nl2sql görünsün

from nl2sql import config  # noqa: E402
from nl2sql.auth.store import UserStore  # noqa: E402
from nl2sql.schema_map import build, onboard, template, template_import  # noqa: E402
from nl2sql.web.map_api import SAMPLE_DATASET  # noqa: E402  # örnek kümenin adı arayüzle aynı kalsın

VISUAL_DIR = ROOT / "data" / "visual"
VISUAL_PASSWORD = "Gorsel-Dunya-2026"
# İki hesap, iki rol: inceleme yöneticinin gördüğü ekranları da kullanıcınınkileri de koşabilir.
USERS = (("admin", "admin"), ("analist", "user"))
# Panonun kartları iş rolüne göre geliyor, o yüzden inceleme en az iki farklı rolün panosunu
# görmeli: yönetici "Yönetim", analist "Satış" kartlarını koşar. ``satinalma`` üçüncü rolün
# (Satın alma) panosunu ve yöneticinin kullanıcı tablosundaki üçüncü satırı taşır.
BUSINESS_USERS = (("admin", "yonetim"), ("analist", "satis"), ("satinalma", "satin_alma"))
# Vitrinin kapalı kümesi: haritadan doğmuş, SQL Server diyen bir küme. Bağlantıları ekranı yalnız
# SQL Server kümelerini listeler, yani akışın düzenleyeceği satır buradan doğar; "kapalı" olan şey
# sunucudur ve cevabı aşağıdaki dosya verir (R7-28).
VITRIN_DATASET = "vitrin_kapali"
# R7-26 yoklama dosyası: ``SELECT 1``in cevabı da guard'ın bağı da sunucudan değil buradan gelir.
# İki küme iki renk nokta; iki sunucu adı da bağın iki cevabıdır - biri yazabiliyor, biri yazamıyor.
PROBE = {
    "status": {"synthetic_erp": "ok", VITRIN_DATASET: "down"},
    "guard": {"ro.local": "readonly", "sa.local": "sysadmin"},
}


class VisualError(Exception):
    """Kum havuzunun yolu değil; mesajı neden reddedildiğini söy."""


def app_db() -> Path:
    """İncelemenin uygulama veritabanı; ``NL2SQL_APP_DB`` olarak çocuğa verilir."""
    return VISUAL_DIR / "bilgin.db"


def real_datasets_dir() -> Path:
    """Ekrandan yüklenen gerçek kümelerin indiği klasör; ``NL2SQL_REAL_DATASETS_DIR``."""
    return VISUAL_DIR / "real_datasets"


def sample_db() -> Path:
    """Örnek kümenin veritabanı; küme sözleşmesi çıktısını ``data/`` altında adlandırır."""
    return config.ROOT / "data" / f"{SAMPLE_DATASET}.db"


def sample_index() -> Path:
    """Örnek kümenin indeksi; önceki koşudan kalanı bu koşunun şemasıyla ilgili değildir."""
    return config.ROOT / "index" / SAMPLE_DATASET


def probe_file() -> Path:
    """Yoklama dosyası; ``serve``a ``--db-probe-file`` olarak verilir, kum havuzunun içindedir."""
    return VISUAL_DIR / "db_probe.json"


def vitrin_db() -> Path:
    """Vitrin kümesinin veritabanı; küme sözleşmesi çıktısını ``data/`` altında adlandırır."""
    return config.ROOT / "data" / f"{VITRIN_DATASET}.db"


def read_example(name: str, connection: str = "sqlite") -> dict:
    """Dolu örnek şablonun kendi okuması: model gerekmez, küme de veritabanı da ondan doğar."""
    with tempfile.TemporaryDirectory() as folder:
        book = Path(folder) / f"{name}.xlsx"
        book.write_bytes(template.filled_example_workbook(name, connection))
        return template_import.read_template(book)


def build_sample_db(path) -> Path:
    """Dolu örnek şablonun şemasından boş tablo kurar; ``path``e yazılan dosyayı döndürür.

    Harita bir küme uyguladığında veritabanı üretmez -- gerçek veritabanı zaten vardır -- ama
    incelemenin "Bu veri kümesine geç"i sorgulanacak bir dosya ister, yoksa ``open_session``
    örnek kümeyi 409'la reddeder ve akış geçiş adımında kalır.
    """
    build.write_sqlite({}, read_example(SAMPLE_DATASET)["schema"], path)
    return Path(path)


def build_vitrin_dataset() -> Path:
    """Örnek çalışma kitabını kum havuzunda vitrin kümesi olarak kurar: klasör, veritabanı, indeks.

    Klasör haritanın kendi yolundan doğar (``onboard.apply_preview``), yani akışın ``#map-apply``le
    kurduğu şeyin aynısıdır; veritabanı ile indeks de geçişi mümkün kılacak kadardır — "Bu kümeye
    geç" düğmesi indeksi olana açıktır. Düşük olan şey sunucudur, yani durumu yoklama dosyası söyler.
    """
    from nl2sql.cli import main as cli  # indeks işi CLI'ın kendi kapısından geçer

    root = config.real_datasets_dir()
    if root != real_datasets_dir():
        raise VisualError(f"{root} kum havuzu değil; vitrin kümesi oraya kurulamaz.")
    read = read_example(VITRIN_DATASET, "mssql")
    folder = onboard.apply_preview(read, "gorsel-inceleme")
    build.write_sqlite({}, read["schema"], vitrin_db())
    cli.build_index("fake", dataset=VITRIN_DATASET)
    return folder


def write_probe(path=None) -> Path:
    """Bekçinin de guard'ın da okuduğu dosya; yol denetimi yazarken de aynı (R7-26)."""
    target = _require_visual(probe_file() if path is None else Path(path))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(PROBE, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def seed_users(path) -> list[dict]:
    """``path``teki veritabanını sıfırlar ve iki incelemeci hesabını açar.

    Sıfırlama yol denetiminden sonra gelir, o yüzden çağrı kum havuzu dışındaki bir kullanıcı
    deposunu hiçbir zaman boşaltamaz. Her koşu boş tabloyla başladığından incelemede görünen
    kullanıcılar tam olarak ``USERS``tır.
    """
    db = _require_visual(path)
    db.unlink(missing_ok=True)
    store = UserStore(db)
    return [store.add_user(name, VISUAL_PASSWORD, role) for name, role in USERS]


def seed_business_roles(path) -> list[dict]:
    """``USERS``e iş rollerini verir, eksik rol hesabını aynı parolayla açar; hepsini döndürür.

    ``seed_users``tan sonra çağrılır: sıfırlanmış tablo üç satırla kurulur. Yol denetimi aynı,
    o yüzden reddedilen bir yol burada da kurulmuş olmaz.
    """
    db = _require_visual(path)
    store = UserStore(db)
    known = {user["username"]: user["id"] for user in store.list_users()}
    for username, business_role in BUSINESS_USERS:
        if username in known:
            store.update_user(known[username], business_role=business_role)
        else:
            store.add_user(username, VISUAL_PASSWORD, "user", business_role)
    return store.list_users()


def _require_visual(path) -> Path:
    """``path`` kum havuzunun içindeyse çözümlenmiş hali; değilse ``VisualError``."""
    target = Path(path).resolve()
    root = VISUAL_DIR.resolve()
    if not target.is_relative_to(root):
        raise VisualError(f"{target} {root} altında değil; görsel dünya buranın dışına yazamaz.")
    return target


def port_free(port: int, host: str = config.SERVE_HOST) -> bool:
    """``serve``ın bağlanacağı adres boşsa True; doluysa False.

    Soket bilinçli olarak çıplak: Windows'ta ``SO_REUSEADDR`` bağlamayı kazanan portu boş gösterir
    (uvicorn o seçeneği kendisi koyar), yani deneme tam da yakalamak istediği artığı kaçırır.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def prepare() -> Path:
    """Kum havuzunu baştan kurar ve yoklama dosyasının yolunu verir; ``serve`` henüz açılmaz.

    Yol denetimi burada da önce gelir: reddedilen bir yol ne silinir ne kurulur.
    """
    VISUAL_DIR.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(real_datasets_dir(), ignore_errors=True)  # yüklenen kümeler de kum havuzundaydı
    real_datasets_dir().mkdir(parents=True, exist_ok=True)  # haritanın kuracağı küme bu köke doğar
    shutil.rmtree(sample_index(), ignore_errors=True)  # örnek kümenin indeksi her koşuda yeniden kurulur
    build_sample_db(sample_db())  # akışın geçeceği örnek kümenin sorgulanacak dosyası olsun
    build_vitrin_dataset()  # bağlantıları ekranının tek satırı + düşmüş noktası
    seed_users(app_db())
    users = seed_business_roles(app_db())  # panonun iki rolü + yönetici tablosunun üçüncü satırı
    probe = write_probe()
    print(
        f"Görsel dünya: {VISUAL_DIR} · {', '.join(user['username'] for user in users)}"
        f" · yoklama: {probe}"
    )
    return probe


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    # Önce port sorulur: portu bir artık tutuyorsa ``serve`` ona bağlanır ve inceleme ağaçtaki
    # sürümü değil onu koşar, o yüzden burada hiçbir şey silinmeden çıkılır.
    if not port_free(args.port):
        print(f"Port {args.port} dolu: görsel dünya silinmedi, sunucu açılmadı; önce oradaki süreci kapatın.")
        return 1
    # Hazırlığın kendi süreci de kum havuzunu görmeli: ``apply_preview`` ve ``build_index`` yolu
    # configden okur. Alt süreç aynı ortamı taşır, yani iki dünya bir daha ayrılmaz.
    os.environ["NL2SQL_APP_DB"] = str(app_db())
    os.environ["NL2SQL_REAL_DATASETS_DIR"] = str(real_datasets_dir())
    probe = prepare()
    return subprocess.call(
        [
            sys.executable, "-m", "nl2sql", "serve",
            "--llm", "fake",
            "--port", str(args.port),
            "--db-probe-file", str(probe),
        ],
        cwd=ROOT,
        env=os.environ,
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="görsel inceleme için serve (data/visual dünyası)")
    parser.add_argument("--port", type=int, default=config.SERVE_PORT, help="sunucunun bağlanacağı port")
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
