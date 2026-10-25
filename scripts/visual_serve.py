"""Görsel inceleme sunucusu: ``serve``, ama gördüğü dünya ``data/visual/`` altındadır (PLAN R6-20).

Kilometre taşı incelemesi tarayıcıdan akış koşuyor ve o akışın artık bir kullanıcısı var: giriş
kartı, oturum çipi, çıkış. Gerçek ``data/bilgin.db``nin yöneticisinin parolası bilinemez ve
değiştirilemez, o yüzden inceleme kendi boş dünyasında koşar — uygulama veritabanı da ekrandan
yüklenen gerçek kümeler de ``data/visual/`` altına yazılır ve her koşuda baştan kurulur. Yol
denetimi bu izolasyonun kendisidir: ``data/visual/`` dışındaki hiçbir yol silinmez, yani yanlışlıkla
gerçek veritabanına ya da depodaki ``real_datasets/``e dokunulamaz.

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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))  # betik nereden çağrılırsa çağrılsın nl2sql görünsün

from nl2sql import config  # noqa: E402
from nl2sql.auth.store import UserStore  # noqa: E402

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
