# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Model anahtarlarının sır klasörü: ``NL2SQL_HOME/secrets`` (PLAN R8-21).

Bir Windows servisinin ortam değişkeni yoktur: WinSW XML'ine anahtar yazılmaz (R8-23), anahtar
``<ENV>.bin`` dosyasında DPAPI blobu olarak durur. Makine kapsamıdır, yani servisi çalıştıran
sanal hesap da blobu açabilir; klasörün ACL'ini kurulum betiği sıkılaştırır.
Entropy dosya adının kendisidir (``bilgin-secret:<ENV>``), o yüzden bir blob başka bir değişkenin
adıyla yazılsa bile yerine geçmez - yanlış ad açmayı çözülemez bir hataya çevirir.

Okuma hiçbir zaman patlamaz: dosya yoksa, makine Windows değilse ya da blob bu entropiyle
mühürlenmemişse cevap ``None``dır, yani çağıran için sır yoktur. Bağlantı şifrelerinin kutusu
``engine/dpapi.py``de kalır (R7-22); burası yalnız model anahtarlarıdır.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from nl2sql import config
from nl2sql.engine import dpapi

ENTROPY_PREFIX = "bilgin-secret:"
SUFFIX = ".bin"

log = logging.getLogger(__name__)


def secret_path(env_name: str, home: Path | None = None) -> Path:
    """``<ENV>.bin``in yolu: ``home`` söylenmezse ``NL2SQL_HOME``ın sır klasörü (R8-20)."""
    folder = config.SECRETS_DIR if home is None else Path(home) / "secrets"
    return folder / f"{env_name}{SUFFIX}"


def entropy_for(env_name: str) -> bytes:
    """Blobun kendi sırrı: ``bilgin-secret:<ENV>`` UTF-8 olarak - kurulum betiği de aynısını verir."""
    return (ENTROPY_PREFIX + env_name).encode("utf-8")


def read_secret(env_name: str, home: Path | None = None) -> str | None:
    """Blobun içindeki metin; sır yoksa ``None`` - okuma hiçbir nedenle fırlatmaz."""
    if sys.platform != "win32":
        return None
    path = secret_path(env_name, home)
    try:
        blob = path.read_bytes()
    except FileNotFoundError:
        return None
    try:
        return dpapi.unprotect(blob, entropy_for(env_name)).decode("utf-8")
    except ValueError as exc:
        # Yanlış entropy ya da bozuk blob: kullanıcı için sonuç "sır yok"tur, iz tek satıra düşer.
        log.warning("%s çözülemedi: %s", path, exc)
        return None


def write_secret(env_name: str, value: str, home: Path | None = None) -> Path:
    """``value``yı mühürleyip ``<ENV>.bin``e yazar; yazdığı dosyanın yolunu döndürür."""
    path = secret_path(env_name, home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(dpapi.protect(value.encode("utf-8"), entropy_for(env_name)))
    return path
