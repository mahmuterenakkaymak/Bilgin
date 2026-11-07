# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""User-facing text from the catalogs: t(key, lang, **params), Turkish as the fallback (R8-2)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from nl2sql import config

CATALOG_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=None)
def _catalog(lang: str) -> dict[str, str]:
    return json.loads((CATALOG_DIR / f"{lang}.json").read_text(encoding="utf-8"))


def normalize_lang(value: object) -> str | None:
    """'tr'/'en' out of a user-supplied value ('EN-US' -> 'en'); None when it names no language."""
    if not isinstance(value, str):
        return None
    primary = value.strip().lower().replace("_", "-").split("-")[0]
    return primary if primary in config.LANGUAGES else None


def t(key: str, lang: str | None = None, **params) -> str:
    """Text of `key` in `lang`; lang None -> config.lang(), an unknown lang -> Turkish.

    A key the language lacks is read from Turkish; a key Turkish lacks raises KeyError, so a typo
    fails a test instead of showing the raw key on screen.
    """
    name = normalize_lang(config.lang() if lang is None else lang) or config.DEFAULT_LANG
    text = _catalog(name).get(key)
    if text is None:
        text = _catalog(config.DEFAULT_LANG)[key]
    return text.format(**params) if params else text
