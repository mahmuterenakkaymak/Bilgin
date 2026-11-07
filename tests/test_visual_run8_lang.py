# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (c) 2026 Mahmut Eren Akkaymak

"""T444: İngilizce görsel akışlar (PLAN R8-25).

``.hybrid/visual.json``un üç İngilizce sayfası ``from: M28`` etiketli: ``test_visual_flows`` o
sayfaları M28 bitene kadar seçici denetiminin dışında tutar, yani burada kendimiz denetleriz.
Aynı dosya tek sunucuda koşar ve dil kullanıcının hesabında durur, o yüzden her sayfa
``button[data-lang='tr']`` ile bitmeli - aksi hâlde sıradaki sayfanın, hatta öteki genişliğin
kareleri İngilizce çekilir.
"""

import json
import re

from bilgin import config

VISUAL_PATH = config.ROOT / ".hybrid" / "visual.json"
GOLDEN_EN_PATH = config.ROOT / "datasets" / "wwi" / "golden_en.jsonl"
SRC_DIR = config.ROOT / "web" / "src"

PAGES = ("en-login", "en-ask-chart", "en-map-screen")
MILESTONE = "M28"

# Sayfaların dokunabileceği adlar: dil anahtarının kabi ve iki düğmesi, soru alanı, sor düğmesi,
# haritaya giden bağlantı ve haritanın örnek düğmesi.
# ASSUMPTION: PLAN R8-25 kanıtı ``#evidence`` ile açmayı söylüyor; ``#evidence`` kapalıyken
# ``hidden`` olan gövdedir, yani tıklayacak düğme değil - açan ``#evidence-toggle``.
ALLOWED = (
    "#lang-toggle",
    "button[data-lang='en']",
    "button[data-lang='tr']",
    "#question",
    "#ask-button",
    "#nav-map",
    "#map-try-sample",
    # her sayfanın girdiği kapı ve kanıt düğmesi: akışın gövdesi bunlarsız kurulmaz
    "#login-username",
    "#login-password",
    "#login-submit",
    "#evidence-toggle",
)

LANG_CLICK = re.compile(r"^button\[data-lang='(\w+)'\]$")


def visual() -> dict:
    return json.loads(VISUAL_PATH.read_text(encoding="utf-8"))


def page(name: str) -> dict:
    return next(p for p in visual()["pages"] if p["name"] == name)


def selectors(page_name: str) -> list[str]:
    steps = page(page_name)["steps"]
    found = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if "click" in step:
            found.append(step["click"])
        if "fill" in step:
            found.append(step["fill"][0])
    return found


def shots(page_name: str) -> list[str]:
    return [s for s in page(page_name)["steps"] if isinstance(s, str) and s.split(":")[0] == "shot"]


def source_text() -> str:
    """Bileşenlerin kaynak dosyaları: testler ve sabit veriler değil, üretilen arayüzün kendisi."""
    files = [
        path
        for path in sorted(SRC_DIR.rglob("*"))
        if path.suffix in (".js", ".jsx") and ".test." not in path.name and "fixtures" not in path.parts
    ]
    return "\n".join(path.read_text(encoding="utf-8") for path in files)


def missing_part(selector: str, text: str) -> str | None:
    """Seçicinin kaynakta okunur kalması gereken parçaları: ``#id`` -> ``id="id"``, ``[ad=..]`` -> ``ad=``."""
    for name in re.findall(r"#([\w-]+)", selector):
        if f'id="{name}"' not in text:
            return f"id {name}"
    for name in re.findall(r"\[\s*([\w-]+)", selector):
        if not re.search(rf"\b{re.escape(name)}\s*=", text):
            return f"özellik {name}"
    return None


def golden_en_question(golden_id: str) -> str:
    for line in GOLDEN_EN_PATH.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["id"] == golden_id:
            return row["question"]
    raise AssertionError(f"{golden_id} {GOLDEN_EN_PATH.name} içinde yok")


# ------------------------------------------------------------------ sayfalar


def test_the_three_english_pages_are_declared_for_m28():
    names = [p["name"] for p in visual()["pages"]]
    for name in PAGES:
        assert name in names, f"{name} akış listesinde yok: {names}"
        assert page(name)["from"] == MILESTONE, page(name)
        assert page(name)["path"].startswith("/"), page(name)
        assert page(name)["steps"], f"{name} hiç adım yok"


def test_the_english_pages_use_only_selectors_the_components_render():
    text = source_text()

    for name in PAGES:
        for selector in selectors(name):
            assert selector in ALLOWED, f"{name} beklenmeyen bir seçiciye dokunuyor: {selector}"
            gone = missing_part(selector, text)
            assert gone is None, f"{name} akışındaki {selector!r} artık kaynakta yok: {gone}"


def test_every_allowed_selector_still_exists_in_the_components():
    """Liste kendi kendine doğrulanmaz: içinden bir ad silinirse sayfaların onu kullanması da
    gerekmez - kabın kaynağa dokunduğunu burada denetleriz."""
    text = source_text()

    for selector in ALLOWED:
        gone = missing_part(selector, text)
        assert gone is None, f"{selector!r} artık kaynakta yok: {gone}"


# ------------------------------------------------------------------ soru


def test_the_ask_page_types_the_english_golden_question():
    """Kare İngilizce bir sorunun İngilizce cevabını göstermeli; Türkçe golden satırı ya da elle
    yazılmış bir cümle fake oynatıcıya takılmaz ve cevap Türkçe gelir."""
    fills = {
        step["fill"][0]: step["fill"][1]
        for step in page("en-ask-chart")["steps"]
        if isinstance(step, dict) and "fill" in step
    }
    assert fills["#question"] == golden_en_question("E01")


# ------------------------------------------------------------------ dil geri verilmeli


def test_every_page_hands_the_language_back_to_turkish():
    """Dil kullanıcının hesabında: TR'ye dönmeyen bir sayfa sunucuyu İngilizce bırakır ve
    sonraki her sayfanın karesi İngilizce çekilir."""
    for name in PAGES:
        langs = [
            LANG_CLICK.match(step["click"]).group(1)
            for step in page(name)["steps"]
            if isinstance(step, dict) and "click" in step and LANG_CLICK.match(step["click"])
        ]
        assert langs[:1] == ["en"], f"{name} İngilizceye geçmiyor: {langs}"
        assert langs[-1:] == ["tr"], f"{name} sunucuyu {langs[-1]!r} dilinde bırakıyor: {langs}"


def test_every_page_shoots_at_least_twice():
    for name in PAGES:
        assert len(shots(name)) >= 2, f"{name} incelemede görünecek iki kare bırakmıyor: {shots(name)}"
