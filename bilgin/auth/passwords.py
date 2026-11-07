# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Parola karması: standart kütüphane scrypt, dış bağımlılık yok.

Saklanan biçim ``scrypt$n$r$p$salt_b64$hash_b64``; maliyet etkenleri kendi içinde taşındığı
için ``config`` değerleri değişse de eski parolalar doğrulanmaya devam eder.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

from bilgin import config

SCHEME = "scrypt"
SALT_BYTES = 16
DKLEN = 32
# scrypt ~128*N*r bayt çalışma belleği ister; varsayılan 2**14x8 bunu aşınca hashlib'in
# 32 MB'lık varsayılan tavanı ValueError verirdi, o yüzden tavan açıkça yükseltiliyor.
MAXMEM = 256 * 1024 * 1024


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    """Parolayı tuzlu scrypt karmasına çevirir; aynı parola her çağrıda farklı üretilir."""
    salt = secrets.token_bytes(SALT_BYTES)
    return "$".join(
        (
            SCHEME,
            str(config.SCRYPT_N),
            str(config.SCRYPT_R),
            str(config.SCRYPT_P),
            _b64(salt),
            _b64(_scrypt(password, salt, config.SCRYPT_N, config.SCRYPT_R, config.SCRYPT_P)),
        )
    )


def verify_password(password: str, stored: str) -> bool:
    """Saklanan değerdeki n/r/p ve tuz ile yeniden hesaplar; bozuk değer False verir, patlamaz."""
    if not isinstance(stored, str):  # NULL/boş kolon değeri de False'a düşer
        return False
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != SCHEME:
            return False
        digest = _scrypt(password, base64.b64decode(salt_b64, validate=True), int(n), int(r), int(p))
        return hmac.compare_digest(digest, base64.b64decode(hash_b64, validate=True))
    except ValueError:  # yanlış parça sayısı, bozuk base64, int'e dönmeyen n/r/p, aşırı maliyet
        return False


def check_new_password(password: str) -> str | None:
    """Kabul edilmeyen yeni parola için gösterilecek Türkçe satır; uygunsa None."""
    if len(password) < config.PASSWORD_MIN_LEN:
        return f"Parola en az {config.PASSWORD_MIN_LEN} karakter olmalı."
    return None


def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=DKLEN, maxmem=MAXMEM
    )
