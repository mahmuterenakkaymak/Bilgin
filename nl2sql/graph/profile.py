# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Join profili: hangi kolon adlarının aynı işi söylediği dosyada durur (PLAN R2-10).

ERP'lerde bir tablo cari kodu HESAP_KOD, öteki HESAP_KODU yazar; bu eşleşme Python'a gömülmez, çünkü
Python'un ERP bilgisi olmaması gerekiyor. Dosya silinir veya boş kalırsa graph yalnızca fk'ları tanır.
"""

from __future__ import annotations

import json
from pathlib import Path

from nl2sql import config


def load_profile(path: str | Path = config.PROFILE_PATH) -> list[dict]:
    """Profil çiftleri: {"left", "right", "confidence"}; confidence açık aralıkta (0,1) olmalı."""
    with open(path, encoding="utf-8") as handle:
        pairs = json.load(handle)["pairs"]
    for pair in pairs:
        confidence = pair["confidence"]
        if not isinstance(confidence, (int, float)) or not 0 < confidence < 1:
            raise ValueError(
                f"profile çifti {pair['left']} <-> {pair['right']}: confidence 0 ile 1 arasında olmalı"
                f" (ikisi hariç); bulunan {confidence!r}."
            )
    return pairs
