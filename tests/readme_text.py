# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""README denetimlerinin okuduğu metin (R8-14): README.md + README.tr.md.

İngilizce README yazıldığında işaret denetimleri tek dosyada kör kalmasın: iki metin tek bir dizide
birleşir. Olmayan dosya metne girmez, yani README.tr.md henüz yokken bugünkü tek dosya metni döner.
Yol ``config.ROOT``'tan çağrı anında okunur; kökü tmp'ye taşıyan testler aynı davranır.
"""

from bilgin import config


def readme_text() -> str:
    parts = []
    for name in ("README.md", "README.tr.md"):
        path = config.ROOT / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)
