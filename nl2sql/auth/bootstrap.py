"""Geliştirme yöneticisi: boş kullanıcı tablosuna bir kez admin sokan tek yol (PLAN R6-7).

Parolanın değeri yalnız ortam değişkeninde durur; koda, konfigürasyona, günlüğe ve ekrana düşmez.
Minimum uzunluk yalnız bu yolda aranmaz - geliştiricinin ve testlerin kısa parolası buradan geçer,
gerçek kullanıcı ``user add``in denetiminden geçer. Satır ``store.add_user``ile değil burada
yazılır, çünkü o denetim tam olarak orada durur ve bu yol ona girmek zorunda değildir.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from datetime import datetime, timezone

from nl2sql import config
from nl2sql.auth.passwords import hash_password

DEV_USERNAME = "admin"
DEV_ADMIN_WARNING = (
    "Geliştirme yöneticisi oluşturuldu: admin - NL2SQL_DEV_ADMIN_PASSWORD ortam değişkeninden; "
    "canlı kurulumda bu değişkeni tanımlamayın."
)


def dev_admin(store, environ: Mapping[str, str]) -> bool:
    """Boş tabloda değişkenle ``admin``/admin açar ve uyarır; yönetici varsa ya da değişken boşsa False.

    Dönen değer "bir yönetici var mı" değil "bootstrap bir şey yaptı mı": kullanıcı zaten varsa
    hiçbir satır yazılmaz, yani gerçek bir yöneticinin parolası asla ezilemez.
    """
    password = environ.get(config.DEV_ADMIN_ENV, "")
    if not password.strip() or store.count_users():
        return False
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite3.connect(store.path) as conn:
        conn.execute(
            "INSERT INTO users (username, password_hash, role, active, created_at)"
            " VALUES (?, ?, 'admin', 1, ?)",
            (DEV_USERNAME, hash_password(password), now),
        )
    print(DEV_ADMIN_WARNING)
    return True
