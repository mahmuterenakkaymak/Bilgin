"""Görsel inceleme sunucusu: ``serve``, ama gördüğü dünya ``data/visual/`` altındadır (PLAN R6-20).

Kilometre taşı incelemesi tarayıcıdan akış koşuyor ve o akışın artık bir kullanıcısı var: giriş
kartı, oturum çipi, çıkış. Gerçek ``data/bilgin.db``nin yöneticisinin parolası bilinemez ve
değiştirilemez, o yüzden inceleme kendi boş dünyasında koşar — uygulama veritabanı da ekrandan
yüklenen gerçek kümeler de ``data/visual/`` altına yazılır ve her koşuda baştan kurulur. Yol
denetimi bu izolasyonun kendisidir: ``data/visual/`` dışındaki hiçbir yol silinmez, yani yanlışlıkla
gerçek veritabanına ya da depodaki ``real_datasets/``e dokunulamaz. Tek istisna haritanın örnek
kümesidir: ``ornek_fatura``nın veritabanı ve indeksi küme sözleşmesinin verdiği yollarda durur
(``data/ornek_fatura.db``, ``index/ornek_fatura``), o yüzden akış onları kum havuzunun dışında kurar
ve eski indeksi baştan siler.

``VISUAL_PASSWORD`` bilinçli olarak depoda durur: tek kullanımlık bir kum havuzu parolasıdır, iki
incelemeci hesabından başka bir şey korumaz ve ``.hybrid/visual.json`` da aynı değeri yazar. Ürünün
kodu onu tanımaz; ``nl2sql/`` altında arandığında boş dönmesinin sebebi bu. Sunucu ``serve``ı alt
süreç olarak açar, böylece inceleme de aynı komut satırı kapısından geçer.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # betik nereden çağrılırsa çağrılsın nl2sql görünsün

from nl2sql import config  # noqa: E402
from nl2sql.auth.store import UserStore  # noqa: E402
from nl2sql.schema_map import build, template, template_import  # noqa: E402
from nl2sql.web.map_api import SAMPLE_DATASET  # noqa: E402  # örnek kümenin adı arayüzle aynı kalsın

VISUAL_DIR = ROOT / "data" / "visual"
VISUAL_PASSWORD = "Gorsel-Dunya-2026"
# İki hesap, iki rol: inceleme yöneticinin gördüğü ekranları da kullanıcınınkileri de koşabilir.
USERS = (("admin", "admin"), ("analist", "user"))


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


def build_sample_db(path) -> Path:
    """Dolu örnek şablonun şemasından boş tablo kurar; ``path``e yazılan dosyayı döndürür.

    Harita bir küme uyguladığında veritabanı üretmez -- gerçek veritabanı zaten vardır -- ama
    incelemenin "Bu veri kümesine geç"i sorgulanacak bir dosya ister, yoksa ``open_session``
    örnek kümeyi 409'la reddeder ve akış geçiş adımında kalır.
    """
    with tempfile.TemporaryDirectory() as folder:
        book = Path(folder) / f"{SAMPLE_DATASET}.xlsx"
        book.write_bytes(template.filled_example_workbook(SAMPLE_DATASET))
        read = template_import.read_template(book)  # şablonun kendi okuması: model gerekmez
    build.write_sqlite({}, read["schema"], path)
    return Path(path)


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


def _require_visual(path) -> Path:
    """``path`` kum havuzunun içindeyse çözümlenmiş hali; değilse ``VisualError``."""
    target = Path(path).resolve()
    root = VISUAL_DIR.resolve()
    if not target.is_relative_to(root):
        raise VisualError(f"{target} {root} altında değil; görsel dünya buranın dışına yazamaz.")
    return target


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    VISUAL_DIR.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(real_datasets_dir(), ignore_errors=True)  # yüklenen kümeler de kum havuzundaydı
    real_datasets_dir().mkdir(parents=True, exist_ok=True)  # haritanın kuracağı küme bu köke doğar
    shutil.rmtree(sample_index(), ignore_errors=True)  # örnek kümenin indeksi her koşuda yeniden kurulur
    build_sample_db(sample_db())  # akışın geçeceği örnek kümenin sorgulanacak dosyası olsun
    users = seed_users(app_db())
    print(f"Görsel dünya: {VISUAL_DIR} · {', '.join(user['username'] for user in users)}")
    env = {
        **os.environ,
        "NL2SQL_APP_DB": str(app_db()),
        "NL2SQL_REAL_DATASETS_DIR": str(real_datasets_dir()),
    }
    return subprocess.call(
        [sys.executable, "-m", "nl2sql", "serve", "--llm", "fake", "--port", str(args.port)],
        cwd=ROOT,
        env=env,
    )


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="görsel inceleme için serve (data/visual dünyası)")
    parser.add_argument("--port", type=int, default=config.SERVE_PORT, help="sunucunun bağlanacağı port")
    return parser.parse_args(argv)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    raise SystemExit(main())
