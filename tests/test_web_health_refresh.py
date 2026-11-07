# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T218: başlıktaki sağlık noktası kendini tazelemeli (PLAN R5-18 header).

Nokta ``/api/health`` çıktısını, kural ekranındaki ``#index-stale`` bandı ise aynı ``index.fresh``
alanının öteki yüzünü gösterir. Kayıt, silme ve yeniden kurma bandı tazeliyordu; nokta açılışta
okuduğu renkte kalıyor, yani arayüz aynı gerçeği iki yerden birini yalan söylüyordu. Burada
tarayıcı yok: test ``web/src/App.jsx`` kaynağına bakıp tazelemenin gerçekten bağlanıp bağlanmadığını
denetler — isteğin adı konmuş bir işlev olması, hem açılış effect'inde hem kural akışının geri
çağrısı olarak çağırılması ve ErrorCard'ın yeniden kurma düğmesinin o tazelemeye ulaşması.
"""

import re

from nl2sql import config

APP = config.ROOT / "web" / "src" / "App.jsx"
SOURCE = APP.read_text(encoding="utf-8")


def body(head: str, text: str = SOURCE) -> str:
    """``head`` imzasının gövdesi: parametre parantezi kapandıktan sonraki ilk dengeli blok.

    ``({ onChanged })`` gibi açılımlı parametreler gövde sayılmasın diye imzanın ilk ``)`` işaretine
    kadar ilerlenir; iç içe küme parantezleri (JSX ifadeleri, nesne değişmezleri) sayılır.
    """
    start = text.index("{", text.index(")", text.index(head)))
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise AssertionError(f"{head!r} gövdesi kapanmıyor")


def test_the_health_fetch_is_a_named_function():
    health = body("const refreshHealth")

    assert "HEALTH_URL" in health
    assert "setHealth" in health, "işlev sonucu başlığa taşımıyordu"


def test_the_header_reads_health_on_open_and_every_time_a_rule_flow_changes():
    app = body("export default function App")

    assert re.search(r"useEffect\(\(\) => refreshHealth\(\), \[\]\s*\)", app), "açılışta tazeleme yok"
    assert "onChanged={refreshHealth}" in app, "kural akışına tazeleme geri çağrısı verilmedi"
    assert "onChanged={onChanged}" in body("function Screen"), "geri çağrı RulesFlow'a inmiyor"


def test_the_rules_flow_refreshes_the_header_after_re_reading_its_own_data():
    refresh = body("const refresh", body("function RulesFlow"))

    assert "rulesList()" in refresh and "tables()" in refresh, "kendi verisini okumayı bıraktı"
    assert re.search(r"onChanged\s*\?\.\s*\(\)", refresh), "bant tazelendi, başlık tazelemiyor"


def test_the_error_card_rebuild_refreshes_the_header_too():
    app = body("export default function App")

    assert re.search(r"api\.rebuild\(\)[\s\S]{0,40}refreshHealth", app), "ErrorCard'ın kurması başlığa ulaşmıyor"
    assert re.search(r"<ErrorCard[\s\S]*?onRebuild=\{onRebuild\}", body("function AskScreen"))
