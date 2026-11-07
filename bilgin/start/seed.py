# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""Kümenin tohum hazır soruları: ilk açılışta bir kez deposuna yazılır (PLAN R7-19).

Bir hazır soru normalde bir yöneticinin onayladığı sorudur; tohum satırı ise kümenin klasöründeki
``ready_questions.json``dan gelir ve onaylı doğar - SQL'i altın kayıt ya da elle denetlenmiş bir
değişmezdir, böylece başlangıç ekranı taze bir kurulumda da boş kalmaz. Tohum burada yürütülmez:
satır yalnız yürütücünün politika süzgecinden geçer, yani olmayan bir tablo ya da kapalı bir kolon
ekranda hata kartı olmak yerine tek satırlık bir notla düşer. Yürütmesi kart açıldığında, kullanıcının
önünde olur.

"Bir kez" ayarı kullanıcı deposunun ayarlarındadır (``ready_seeded:<küme>``, ``active_dataset`` gibi):
ikinci bir açılış ya da küme geçişi aynı satırları bir daha yazmaz - yönetici bir kartı sildiğinde
bir daha geri gelmesi beklenmez.
"""

from __future__ import annotations

from bilgin import config
from bilgin.policy import policy

# Sözleşme "settings": anahtar kümenin adını taşır, değeri yazılan satır sayısıdır.
SETTING = "ready_seeded:{name}"
SKIPPED = "Hazır soru tohumu atlandı ({dataset}/{title}): {reason}"


def ensure_seeded(store, users_store, dataset, executor) -> int:
    """Kümenin tohum satırlarını bir kez ``store``a yazar; yazılan satır sayısını döndürür.

    Tohumun onayı yürütücünün süzgecidir (R7-17'nin onayıyla aynı kapı), yürütmesi değil: böyle bir
    açılışta veritabanına hiç ihtiyaç yoktur, yani SQL Server kümesinin tohumu sunucu ayakta
    olmadan da yazılır. ``users_store`` yoksa ayar yazılamayacağı için tohum da yazılmaz - tek
    kullanıcılı modda (Run 5) başlangıç ekranının sahibi de yoktur.
    """
    # ASSUMPTION: ``dataset`` None olabilir (kümesiz oturum) - o zaman ölçülen dünya config'indir
    # ve tohumu sorulacak bir küme klasörü yoktur.
    if users_store is None or dataset is None or dataset.ready_questions_path is None:
        return 0
    key = SETTING.format(name=dataset.name)
    if users_store.get_setting(key) is not None:
        return 0
    seeded = 0
    for line in dataset.ready_questions():
        reason = _policy_reason(executor, line["sql"])
        if reason is not None:
            print(SKIPPED.format(dataset=dataset.name, title=line["title"], reason=reason))
            continue
        store.add(
            dataset.name,
            line["business_role"],
            line["title"],
            line["question"],
            line["sql"],
            line["display"],
            position=line["position"],
            approved=True,
        )
        seeded += 1
    users_store.set_setting(key, str(seeded))
    return seeded


def _policy_reason(executor, sql: str) -> str | None:
    """Cümle yürütücünün kendi süzgecinden geçiyor mu; geçmiyorsa reddin cümlesi.

    ASSUMPTION: süzgeç yürütücünün kendinden okunur - kart da o yürütücüden koşacağı için tohum aynı
    allowlist ve kapalı kolon kümesine bakmalı, aksi halde ekranda yürümeyen bir kart durur.
    """
    verdict = policy.check(
        sql,
        executor._allowlist,
        config.TOP_N,
        pii=executor._pii_map,
        deny=executor._deny,
        keys=executor._count_keys,
    )
    return None if verdict.ok else verdict.reason
