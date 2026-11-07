# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""İsteğin dili: kişinin tercihi, tarayıcının başlığı, programın dili (PLAN R8-5).

Tek kapı ``request_lang``: her yol arayüz metnini ondan sorar, böylece bir isteğin tüm cümleleri
aynı dilde kurulur. Cevabın dili bundan ayrıdır - o sorudan çözülür (R8-6).
"""

from __future__ import annotations

from fastapi import Request

from bilgin import config
from bilgin.i18n import normalize_lang


def request_lang(request: Request, user: dict | None) -> str:
    """Bu isteğin arayüz dili: ``user["lang"]`` > Accept-Language > program dili (R8-5).

    Tercih NULL (Run 7 dosyaları) ya da tanınmıyorsa başlığa düşülür; başlık da ``LANGUAGES``tan
    hiçbirini tanımlamıyorsa programın kendi dili konuşur.
    """
    if user:
        preferred = normalize_lang(user.get("lang"))
        if preferred:
            return preferred
    return _accept_lang(request.headers.get("accept-language", "")) or config.lang()


def _accept_lang(header: str) -> str | None:
    """Başlığın, programın tanıdığı ilk birincil etiketi (``en-US,en;q=0.9`` -> ``en``)."""
    for item in header.split(","):
        tag = normalize_lang(item.split(";")[0])
        if tag:
            return tag
    return None
