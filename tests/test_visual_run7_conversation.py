"""T314: konuşma akışlarının seçicileri (PLAN R7-15).

``.hybrid/visual.json`` üç konuşma sayfasını M23 için şimdiden ilan etti. ``test_visual_flows.py``
``from`` kapısı yüzünden kilometre taşının son kutusu işaretleşene kadar onların seçicilerini
sorgulamıyor; o gün geldiğinde akışın yürünür olması bugün hazırdır. Bu dosya kapıyı beklemez:
adımlardaki her seçici ile karelerin üstüne çizdirildiği çapalar kaynakta durmalı, yoksa
inceleme boşluğa tıklar ve yanlış bir kareyi "doğru" diye gösterir.
"""

import pytest

from test_visual_flows import parts, selectors, source_text, visual

PAGES = ("conversation-three-turns", "conversation-chart-refine", "new-conversation")

# Üçü de aynı kimlikle açılır: kullanıcı adı, parola, giriş düğmesi. Başka bir adım öne girerse
# akış oturumsuz bir sayfada tıklar ve hata sessiz kalır.
LOGIN = [
    {"fill": ["#login-username", "admin"]},
    {"fill": ["#login-password", "Gorsel-Dunya-2026"]},
    {"click": "#login-submit"},
]

# Karelerin konuşma ekranında baktığı çapalar. Bir kısmı adım seçicisi değil, ``shot`` adıdır
# (``shot:context-line``, ``shot:conversation-list``); inceleme onların üstüne çizdirilir.
ANCHORS = (
    "#thread",
    ".turn",
    "#question",
    "#ask-button",
    "#new-conversation",
    "#context-line",
    "#conversation-list",
    "#sidebar-toggle",
)


def page(name: str) -> dict:
    found = [item for item in visual()["pages"] if item["name"] == name]
    assert found, f"{name} visual.json'da yok: {[item['name'] for item in visual()['pages']]}"
    return found[0]


def missing_in_source(selectors_) -> list[str]:
    text = source_text()
    return [
        f"{selector} -> {kind} {part}"
        for selector in selectors_
        for kind, part, pattern in parts(selector, text)
        if not pattern.search(text)
    ]


def test_the_three_conversation_pages_are_declared():
    listed = [item["name"] for item in visual()["pages"]]

    for name in PAGES:
        assert name in listed, f"{name} visual.json'da yok: {listed}"


@pytest.mark.parametrize("page_name", PAGES)
def test_the_page_opens_with_the_login_steps(page_name):
    steps = page(page_name)["steps"]

    assert steps[: len(LOGIN)] == LOGIN, f"{page_name} girişten önce başka bir adımla açılıyor: {steps[:4]}"


@pytest.mark.parametrize("page_name", PAGES)
def test_every_step_selector_of_the_page_exists_in_the_web_source(page_name):
    found = [selector for step in page(page_name)["steps"] for selector in selectors(step)]
    assert found, f"{page_name} akışında denenecek seçici yok"

    gone = missing_in_source(found)
    assert not gone, f"{page_name} akışının seçicisi artık kaynakta yok: {gone}"


def test_the_anchors_the_conversation_frames_are_shot_on_exist():
    gone = missing_in_source(ANCHORS)
    assert not gone, f"konuşma karelerinin çapası artık kaynakta yok: {gone}"
